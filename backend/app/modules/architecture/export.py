"""
Module: modules.architecture.export

The Architecture module's contribution to the organisation and project bundles:
the organisation's default element and connection types and symbols, and a project's own types
and symbols with the organisation defaults it has hidden, its elements (with ports, tags, places)
and connections, and the links between them and Requirements. Registered through
`ModuleOrgBundleHooks` and `ModuleProjectBundleHooks`, so no core export file
names this module.

Design decisions:
- A project exports the configuration it owns (rows and tombstones), not an
  ancestor's it merely inherits: the project the bundle is imported into has its own
  ancestors.
- Types travel by name. An import skips a name the target already lists (so a fresh
  organisation's seeded defaults are not doubled) and reports a hidden default the
  organisation does not have.
- An element or connection travels with its original code as information only; an
  import numbers its records afresh, and the codes key the parent, the two ends of
  a connection and the links within the bundle. The `version` counter is not carried
  (an imported record starts at 1). A record's type is matched by name among the
  organisation's rows and the project's own, including a default the project hides;
  a type the target lacks is created in the project so the record keeps its type.
- Links travel through the shared `services.bundle_links`, so only links to records
  in this bundle and to Requirements are carried.
- Symbols: an organisation's library travels in the organisation bundle (its files embedded) and a project's own
  uploads in the project bundle, with the organisation symbols the project hides. A symbol travels by name and an
  upload with its file, which an import checks and sanitises again like an upload; a built-in travels by key
  alone. A type or element names its symbol as `{"tier", "name"}`, never by id, and an import takes no id from a
  bundle, so a bundle can never point a record at a symbol of another organisation.
- The four vocabulary keys are template configuration; the records, the collections and their links
  are template records, reset to fresh drafts without creator or archived records.
- Sharing: a collection and its members (element codes) travel in its owner's bundle, **grants never do**, so
  an import can never publish anything to a project or a group by itself. An organisation bundle carries the
  organisation-owned elements (ports, no tags or places, which an organisation-owned record does not have) and
  collections. A connection end another owner shares travels as a reference (the owner's code and the
  element's code, never a name); an import resolves it through `visibility` for the person importing, and
  drops the connection with a warning when it cannot be read.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.architecture.enums import PortDirection, RecordStatus
from app.modules.architecture.models import (
    ArchitectureCollection,
    ArchitectureCollectionMember,
    ArchitectureConnection,
    ArchitectureElement,
    ArchitecturePort,
    ArchitectureSymbol,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_CODE_PREFIX,
    CONNECTION_TYPES,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
    ELEMENT_TYPES,
    SYMBOLS,
    ArchitectureVocabulary,
)
from app.modules.architecture.symbols import BUILTIN_SVG, clean_symbol_svg
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.services import definition_suppression, report_images
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file
from app.services.bundle_links import export_artefact_links, import_artefact_links
from app.services.placements import prime_record_placements, record_placements, restore_record_placements
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.report_raster import ImageRejectedError
from app.services.sequences import generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags
from app.services.template_reset import fresh_drafts

ORG_ELEMENT_TYPES_KEY = "architecture_element_types"
ORG_CONNECTION_TYPES_KEY = "architecture_connection_types"
PROJECT_ELEMENT_TYPES_KEY = "architecture_project_element_types"
PROJECT_CONNECTION_TYPES_KEY = "architecture_project_connection_types"
HIDDEN_ELEMENT_TYPES_KEY = "architecture_hidden_element_types"
HIDDEN_CONNECTION_TYPES_KEY = "architecture_hidden_connection_types"

#: Each vocabulary with the bundle key of its organisation rows, its project rows and its hidden defaults.
_VOCABULARIES: tuple[tuple[ArchitectureVocabulary, str, str, str], ...] = (
    (ELEMENT_TYPES, ORG_ELEMENT_TYPES_KEY, PROJECT_ELEMENT_TYPES_KEY, HIDDEN_ELEMENT_TYPES_KEY),
    (CONNECTION_TYPES, ORG_CONNECTION_TYPES_KEY, PROJECT_CONNECTION_TYPES_KEY, HIDDEN_CONNECTION_TYPES_KEY),
)

ELEMENTS_KEY = "architecture_elements"
CONNECTIONS_KEY = "architecture_connections"
LINKS_KEY = "architecture_links"
COLLECTIONS_KEY = "architecture_collections"
ORG_ELEMENTS_KEY = "architecture_org_elements"
ORG_COLLECTIONS_KEY = "architecture_org_collections"
ORG_SYMBOLS_KEY = "architecture_org_symbols"
PROJECT_SYMBOLS_KEY = "architecture_project_symbols"
HIDDEN_SYMBOLS_KEY = "architecture_hidden_symbols"

#: Project bundle keys of the vocabularies and the symbol library, for the template classification (configuration).
PROJECT_KEYS = frozenset(
    key for _v, _o, project_key, hidden_key in _VOCABULARIES for key in (project_key, hidden_key)
) | {PROJECT_SYMBOLS_KEY, HIDDEN_SYMBOLS_KEY}
#: Project bundle keys of the records, for the template classification (records).
RECORD_KEYS = frozenset({ELEMENTS_KEY, CONNECTIONS_KEY, LINKS_KEY, COLLECTIONS_KEY})


def _row_json(vocabulary: ArchitectureVocabulary, row, symbol_refs: dict[UUID, dict[str, str]]) -> dict[str, Any]:
    """A row's bundle form: every column except identity, owner and timestamps, with a symbol as a `symbol` reference
    (`{"tier", "name"}`) in place of its id."""
    entry = {column: getattr(row, column) for column in vocabulary.copied_columns() if column != "symbol_id"}
    if vocabulary is ELEMENT_TYPES:
        entry["symbol"] = symbol_refs.get(row.symbol_id) if row.symbol_id else None
    return entry


def _symbol_refs(db: Session, symbol_ids: Iterable[UUID | None]) -> dict[UUID, dict[str, str]]:
    """`{symbol id: {"tier": "organisation" or "project", "name"}}` for the given ids, in one statement."""
    wanted = {i for i in symbol_ids if i}
    if not wanted:
        return {}
    return {
        r.id: {"tier": "organisation" if r.organization_id is not None else "project", "name": r.name}
        for r in db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.id.in_(wanted)))
    }


def _add_rows(
    db: Session, vocabulary: ArchitectureVocabulary, entries: list[dict[str, Any]], *, taken: set[str], owner: dict[str, Any],
    symbol_for: Callable[[Any], UUID | None],
) -> None:
    """Adds the bundle rows whose name is not in `taken`, keeping their order after the owner's existing rows.

    A symbol is never read from the entry as an id: `symbol_for` turns its `symbol` reference into one of the owner's.
    """
    columns = set(vocabulary.copied_columns()) - {"symbol_id"}
    for entry in entries:
        name = entry.get("name")
        if not name or name.lower() in taken:
            continue
        extra = {"symbol_id": symbol_for(entry.get("symbol"))} if vocabulary is ELEMENT_TYPES else {}
        db.add(vocabulary.model(**owner, **{k: v for k, v in entry.items() if k in columns}, **extra))
        taken.add(name.lower())
    db.flush()


# --- Symbols -----------------------------------------------------------------


def _symbol_entries(db: Session, rows: Sequence[ArchitectureSymbol], assets: dict[UUID, FileAsset]) -> list[dict[str, Any]]:
    """Symbol rows in bundle form: name, order and either the built-in key or the file (added to `assets`)."""
    files = {
        a.id: a for a in db.scalars(select(FileAsset).where(FileAsset.id.in_([r.file_asset_id for r in rows if r.file_asset_id])))
    } if any(r.file_asset_id for r in rows) else {}
    out = []
    for row in rows:
        entry: dict[str, Any] = {"name": row.name, "sort_order": row.sort_order, "builtin_key": row.builtin_key}
        asset = files.get(row.file_asset_id) if row.file_asset_id else None
        if asset is not None:
            assets[asset.id] = asset
            entry.update(file_ref=f"{asset.id}_{asset.filename}", filename=asset.filename)
        if row.builtin_key is not None or asset is not None:
            out.append(entry)
    return out


def _import_symbols(
    db: Session, entries: list[dict[str, Any]], file_bytes: dict[str, bytes], *, project_id: UUID | None,
    organization_id: UUID, actor_id: UUID, taken: set[str], warnings: BundleImportWarnings,
) -> None:
    """Recreates the bundle's symbols for one owner. A name the owner already lists is skipped; a built-in whose key is
    unknown, or an upload with no file or an unsafe one, is reported. A file is checked and sanitised again, as an upload
    is, and stored under the importing organisation."""
    for entry in entries:
        name = str(entry.get("name") or "").strip()[:100]
        if not name or name.lower() in taken:
            continue
        fields: dict[str, Any]
        key = entry.get("builtin_key")
        if key is not None:
            if key not in BUILTIN_SVG or project_id is not None:
                warnings.add(f"Symbol {name!r} skipped — it is not a built-in symbol of this version.")
                continue
            fields = {"builtin_key": key}
        else:
            data = file_bytes.get(str(entry.get("file_ref", "")))
            if data is None:
                warnings.add(f"Symbol {name!r} skipped — its file is not in the bundle.")
                continue
            try:
                clean = clean_symbol_svg(data)
            except ImageRejectedError as exc:
                warnings.add(f"Symbol {name!r} skipped — {str(exc).rstrip('.').lower()}.")
                continue
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=actor_id, filename=str(entry.get("filename") or f"{name}.svg"),
                content_type=report_images.SVG_TYPE, data=clean,
            )
            fields = {"file_asset_id": asset.id}
        SYMBOLS.create(db, project_id=project_id, organization_id=organization_id, name=name, **fields)
        taken.add(name.lower())
    db.flush()


def _symbol_lookup(
    db: Session, organization_id: UUID, project_id: UUID | None, warnings: BundleImportWarnings, context: str,
) -> Callable[[Any], UUID | None]:
    """A function turning a bundle `symbol` reference into the id of a symbol this owner may use, else `None` (with a
    warning). A project looks in its own symbols and the organisation's (a hidden one included, as for a type); an
    organisation only in its own."""
    own = {r.name.casefold(): r.id for r in SYMBOLS.project_rows(db, project_id)} if project_id is not None else {}
    org = {r.name.casefold(): r.id for r in SYMBOLS.org_rows(db, organization_id)}

    def lookup(ref: Any) -> UUID | None:
        if not isinstance(ref, dict) or not ref.get("name"):
            return None
        wanted = str(ref["name"]).casefold()
        found = (own.get(wanted) or org.get(wanted)) if ref.get("tier") == "project" else (org.get(wanted) or own.get(wanted))
        if found is None:
            warnings.add(f"{context}: symbol {ref['name']!r} was not found here — the type's shape is drawn.")
        return found

    return lookup


# --- Organisation level ------------------------------------------------------


def _org_element_json(db: Session, org: Organization) -> list[dict[str, Any]]:
    """The organisation-owned elements in bundle form (ports included; no tags or places)."""
    elements = list(db.scalars(
        select(ArchitectureElement).where(ArchitectureElement.organization_id == org.id).order_by(ArchitectureElement.unique_code)
    ))
    codes = {e.id: e.unique_code for e in elements}
    type_names = {
        **{r.id: r.name for r in db.scalars(select(ELEMENT_TYPES.model).where(ELEMENT_TYPES.model.organization_id == org.id))},
        **{r.id: r.name for r in db.scalars(select(CONNECTION_TYPES.model).where(CONNECTION_TYPES.model.organization_id == org.id))},
    }
    ports: dict[UUID, list[ArchitecturePort]] = {}
    if elements:
        for port in db.scalars(
            select(ArchitecturePort).where(ArchitecturePort.element_id.in_(list(codes)))
            .order_by(ArchitecturePort.sort_order, ArchitecturePort.name)
        ):
            ports.setdefault(port.element_id, []).append(port)
    emails = _emails(db, {*(e.creator_id for e in elements), *(e.archived_by for e in elements)})
    symbol_refs = _symbol_refs(db, (e.symbol_id for e in elements))
    return [
        {
            "unique_code": e.unique_code, "name": e.name, "description": e.description,
            "type_name": type_names.get(e.element_type_id), "parent_code": codes.get(e.parent_id) if e.parent_id else None,
            "symbol": symbol_refs.get(e.symbol_id) if e.symbol_id else None,
            "owner": principal_to_bundle(db, e.owner_type, e.owner_id), "status": e.status,
            "ports": [
                {
                    "name": p.name, "direction": p.direction, "sort_order": p.sort_order,
                    "connection_type_name": type_names.get(p.connection_type_id) if p.connection_type_id else None,
                }
                for p in ports.get(e.id, ())
            ],
            "created_by_email": _email(emails, e.creator_id), "created_at": _stamp(e.created_at),
            "is_archived": e.is_archived, "archived_at": _stamp(e.archived_at), "archived_by_email": _email(emails, e.archived_by),
        }
        for e in elements
    ]


def _collections_json(db: Session, owner_filter: Any, codes_of: Any) -> list[dict[str, Any]]:
    """Collections matching `owner_filter` with their members as element codes. Grants are never included."""
    collections = list(db.scalars(select(ArchitectureCollection).where(owner_filter).order_by(ArchitectureCollection.name)))
    members: dict[UUID, list[str]] = {}
    if collections:
        for collection_id, element_id in db.execute(
            select(ArchitectureCollectionMember.collection_id, ArchitectureCollectionMember.element_id)
            .where(ArchitectureCollectionMember.collection_id.in_([c.id for c in collections]))
        ):
            code = codes_of(element_id)
            if code:
                members.setdefault(collection_id, []).append(code)
    return [
        {"name": c.name, "description": c.description, "members": sorted(members.get(c.id, []))} for c in collections
    ]


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's default element and connection types, its own elements
    (with ports) and its collections with their members. Grants are never exported."""
    org_types = {vocabulary: vocabulary.org_rows(db, org.id) for vocabulary, _o, _p, _h in _VOCABULARIES}
    symbol_refs = _symbol_refs(db, (r.symbol_id for r in org_types[ELEMENT_TYPES]))
    data: dict[str, Any] = {
        org_key: [_row_json(vocabulary, row, symbol_refs) for row in org_types[vocabulary]]
        for vocabulary, org_key, _project_key, _hidden_key in _VOCABULARIES
    }
    data[ORG_ELEMENTS_KEY] = _org_element_json(db, org)
    codes = dict(db.execute(
        select(ArchitectureElement.id, ArchitectureElement.unique_code).where(ArchitectureElement.organization_id == org.id)
    ).tuples().all())
    data[ORG_COLLECTIONS_KEY] = _collections_json(
        db, ArchitectureCollection.organization_id == org.id, lambda element_id: codes.get(element_id),
    )
    return data


def export_org_files(db: Session, org: Organization, assets: dict[UUID, FileAsset]) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export_files`: the organisation's symbols; each upload's file is added to `assets`."""
    return {ORG_SYMBOLS_KEY: _symbol_entries(db, SYMBOLS.org_rows(db, org.id), assets)}


def import_org_files(
    db: Session, org: Organization, data: dict[str, Any], file_bytes: dict[str, bytes], actor: User, warnings: BundleImportWarnings,
) -> None:
    """`ModuleOrgBundleHooks.import_files`: recreates the organisation's symbols (before its types and elements, which
    name them). A name the organisation already lists is kept as it is, so a fresh organisation's built-ins are not doubled."""
    _import_symbols(
        db, data.get(ORG_SYMBOLS_KEY, []), file_bytes, project_id=None, organization_id=org.id, actor_id=actor.id,
        taken={r.name.lower() for r in SYMBOLS.org_rows(db, org.id)}, warnings=warnings,
    )


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates the defaults (skipping names the organisation already has), then its
    elements, numbered afresh from the organisation's counter, and its collections. No grant is created."""
    symbol_for = _symbol_lookup(db, org.id, None, warnings, "Element type")
    for vocabulary, org_key, _project_key, _hidden_key in _VOCABULARIES:
        rows = vocabulary.org_rows(db, org.id)
        taken = {r.name.lower() for r in rows}
        _add_rows(db, vocabulary, data.get(org_key, []), taken=taken, owner={"organization_id": org.id}, symbol_for=symbol_for)

    def type_row(vocabulary: ArchitectureVocabulary, name: str | None):
        if not name:
            return None
        found = next((r for r in vocabulary.org_rows(db, org.id) if r.name.casefold() == name.casefold()), None)
        if found is None:
            warnings.add(f"{vocabulary.label} {name!r} was not found here and was created.")
            found = vocabulary.create(db, project_id=None, organization_id=org.id, name=name)
        return found

    element_symbol_for = _symbol_lookup(db, org.id, None, warnings, "Element")
    created: dict[str, ArchitectureElement] = {}
    for entry in data.get(ORG_ELEMENTS_KEY, []):
        code = entry.get("unique_code", "")
        element_type = type_row(ELEMENT_TYPES, entry.get("type_name"))
        if code in created or element_type is None:
            warnings.add(f"Element {code or '?'} skipped — {'it appears more than once' if code in created else 'it has no type'}.")
            continue
        creator = users.resolve(entry.get("created_by_email"), required=True, context=f"Element {code} creator")
        archived = bool(entry.get("is_archived"))
        element = ArchitectureElement(
            organization_id=org.id,
            unique_code=generate_unique_code(db, org, ELEMENT_ARTEFACT_TYPE, ELEMENT_CODE_PREFIX),
            name=entry["name"], description=entry.get("description", ""), element_type_id=element_type.id, parent_id=None,
            symbol_id=element_symbol_for(entry.get("symbol")),
            status=entry.get("status", "draft"), version=1, creator_id=creator, is_archived=archived,
            archived_at=_instant(entry.get("archived_at")),
            archived_by=(users.resolve(entry.get("archived_by_email"), required=False, context=f"Element {code} archiver") or creator)
            if archived else None,
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=org.id, project_id=None, users=users,
                warnings=warnings, context=f"Element {code} owner", required=False,
            ),
        )
        created_at = _instant(entry.get("created_at"))
        if created_at is not None:
            element.created_at = created_at
        db.add(element)
        db.flush()
        created[code] = element
        for order, port in enumerate(entry.get("ports", [])):
            connection_type = type_row(CONNECTION_TYPES, port.get("connection_type_name"))
            db.add(ArchitecturePort(
                element_id=element.id, name=port["name"], direction=port.get("direction", PortDirection.BOTH.value),
                connection_type_id=connection_type.id if connection_type else None, sort_order=port.get("sort_order", order),
            ))
    for entry in data.get(ORG_ELEMENTS_KEY, []):
        parent_code = entry.get("parent_code")
        if parent_code and entry.get("unique_code") in created:
            if parent_code in created:
                created[entry["unique_code"]].parent_id = created[parent_code].id
            else:
                warnings.add(f"Element {entry['unique_code']}: parent {parent_code} is not in the bundle — left at the top level.")
    db.flush()
    _import_collections(
        db, data.get(ORG_COLLECTIONS_KEY, []), owner={"organization_id": org.id},
        owner_filter=ArchitectureCollection.organization_id == org.id,
        elements={code: e.id for code, e in created.items()}, creator_id=next((e.creator_id for e in created.values()), None),
        warnings=warnings,
    )


def _import_collections(
    db: Session, entries: list[dict[str, Any]], *, owner: dict[str, Any], owner_filter: Any, elements: dict[str, UUID],
    creator_id: UUID | None, warnings: BundleImportWarnings,
) -> None:
    """Recreates the bundle's collections for one owner: a name the owner already has is skipped, a member whose element
    is not in the bundle is reported. No grant is created: sharing is chosen in the target, never imported."""
    taken = {name.lower() for name in db.scalars(select(ArchitectureCollection.name).where(owner_filter))}
    for entry in entries:
        name = entry.get("name", "")
        if not name or name.lower() in taken or creator_id is None:
            if name:
                reason = "the owner already has one with that name" if name.lower() in taken else "it has no creator"
                warnings.add(f"Collection {name!r} skipped — {reason}.")
            continue
        taken.add(name.lower())
        collection = ArchitectureCollection(**owner, name=name, description=entry.get("description", ""), creator_id=creator_id)
        db.add(collection)
        db.flush()
        for code in entry.get("members", []):
            element_id = elements.get(code)
            if element_id is None:
                warnings.add(f"Collection {name!r}: element {code} is not in the bundle — not added.")
                continue
            db.add(ArchitectureCollectionMember(collection_id=collection.id, element_id=element_id))
    db.flush()


# --- Project level -----------------------------------------------------------


def _stamp(value: datetime | None) -> str | None:
    """An instant as ISO 8601 (it is already UTC), or `None`."""
    return value.isoformat() if value else None


def _instant(value: str | None) -> datetime | None:
    """The instant a bundle entry names, or `None`."""
    return datetime.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    """`{user id: email}` for the given ids."""
    wanted = {u for u in user_ids if u}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(wanted)))} if wanted else {}


def _email(emails: dict[UUID, str], user_id: UUID | None) -> str | None:
    """The email of `user_id`, or `None` for no user."""
    return emails.get(user_id) if user_id else None


def _foreign_refs(db: Session, element_ids: set[UUID]) -> dict[UUID, dict[str, str]]:
    """`{element id: reference}` for connection ends another owner owns: `{"owner": "project" or "organization",
    "owner_code", "code"}`, codes only (the project already holds them in its connection)."""
    if not element_ids:
        return {}
    rows = db.execute(
        select(
            ArchitectureElement.id, ArchitectureElement.unique_code, ArchitectureElement.project_id, Project.code,
            Organization.code,
        ).outerjoin(Project, Project.id == ArchitectureElement.project_id)
        .outerjoin(Organization, Organization.id == ArchitectureElement.organization_id)
        .where(ArchitectureElement.id.in_(element_ids))
    ).all()
    return {
        element_id: {
            "owner": "project" if project_id is not None else "organization",
            "owner_code": project_code if project_id is not None else org_code, "code": code,
        }
        for element_id, code, project_id, project_code, org_code in rows
    }


def _resolve_foreign(
    db: Session, project: Project, current_user: User, ref: dict[str, str] | None,
) -> UUID | None:
    """The element a foreign-end reference names, if the person importing may read it (else `None`)."""
    if not ref or not ref.get("owner_code") or not ref.get("code"):
        return None
    owner_code = ref["owner_code"].upper()
    if ref.get("owner") == "organization":
        found = db.scalar(
            select(ArchitectureElement.id).join(Organization, Organization.id == ArchitectureElement.organization_id).where(
                func.upper(Organization.code) == owner_code, Organization.id == project.organization_id,
                ArchitectureElement.unique_code == ref["code"],
            )
        )
    else:
        found = db.scalar(
            select(ArchitectureElement.id).join(Project, Project.id == ArchitectureElement.project_id).where(
                func.upper(Project.code) == owner_code, Project.organization_id == project.organization_id,
                ArchitectureElement.unique_code == ref["code"],
            )
        )
    if found is None or found not in visible_element_ids(db, Viewer.of_user(current_user, project), [found]):
        return None
    return found


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict]:
    """`ModuleProjectBundleHooks.export`: the project's own types and the organisation defaults it has hidden, its
    elements with ports, tags and places, its connections (an end another owner shares as a reference), its
    collections with their members (never their grants), and their links (archived records included: a bundle is
    a backup). The project's own symbols travel with their files (returned as the second value), and the
    organisation symbols it hides by name."""
    data: dict[str, Any] = {}
    assets: dict[UUID, FileAsset] = {}
    elements = list(db.scalars(
        select(ArchitectureElement).where(ArchitectureElement.project_id == project.id).order_by(ArchitectureElement.unique_code)
    ))
    own_types = {vocabulary: vocabulary.project_rows(db, project.id) for vocabulary, _o, _p, _h in _VOCABULARIES}
    symbol_refs = _symbol_refs(db, [*(r.symbol_id for r in own_types[ELEMENT_TYPES]), *(e.symbol_id for e in elements)])
    for vocabulary, _org_key, project_key, hidden_key in _VOCABULARIES:
        data[project_key] = [_row_json(vocabulary, row, symbol_refs) for row in own_types[vocabulary]]
        hidden = definition_suppression.get_suppressed_ids(db, project.id, vocabulary.kind)
        data[hidden_key] = [r.name for r in vocabulary.org_rows(db, project.organization_id) if r.id in hidden]
    data[PROJECT_SYMBOLS_KEY] = _symbol_entries(db, SYMBOLS.project_rows(db, project.id), assets)
    hidden_symbols = definition_suppression.get_suppressed_ids(db, project.id, SYMBOLS.kind)
    data[HIDDEN_SYMBOLS_KEY] = [r.name for r in SYMBOLS.org_rows(db, project.organization_id) if r.id in hidden_symbols]

    connections = list(db.scalars(
        select(ArchitectureConnection).where(ArchitectureConnection.project_id == project.id)
        .order_by(ArchitectureConnection.unique_code)
    ))
    element_ids = [e.id for e in elements]
    connection_ids = [c.id for c in connections]
    codes = {e.id: e.unique_code for e in elements}
    type_names = {
        **{r.id: r.name for r in db.scalars(select(ELEMENT_TYPES.model))},
        **{r.id: r.name for r in db.scalars(select(CONNECTION_TYPES.model))},
    }
    ports: dict[UUID, list[ArchitecturePort]] = {}
    port_names: dict[UUID, str] = {}
    if element_ids:
        for port in db.scalars(
            select(ArchitecturePort).where(ArchitecturePort.element_id.in_(element_ids))
            .order_by(ArchitecturePort.sort_order, ArchitecturePort.name)
        ):
            ports.setdefault(port.element_id, []).append(port)
            port_names[port.id] = port.name
    prime_record_tag_names(db, ELEMENT_ARTEFACT_TYPE, element_ids)
    prime_record_tag_names(db, CONNECTION_ARTEFACT_TYPE, connection_ids)
    prime_record_placements(db, ELEMENT_ARTEFACT_TYPE, element_ids)
    prime_record_placements(db, CONNECTION_ARTEFACT_TYPE, connection_ids)
    emails = _emails(
        db,
        {e.creator_id for e in elements} | {e.archived_by for e in elements}
        | {c.creator_id for c in connections} | {c.archived_by for c in connections},
    )

    data[ELEMENTS_KEY] = [
        {
            "unique_code": e.unique_code, "name": e.name, "description": e.description,
            "type_name": type_names.get(e.element_type_id), "parent_code": codes.get(e.parent_id) if e.parent_id else None,
            "symbol": symbol_refs.get(e.symbol_id) if e.symbol_id else None,
            "owner": principal_to_bundle(db, e.owner_type, e.owner_id), "status": e.status,
            "ports": [
                {
                    "name": p.name, "direction": p.direction, "sort_order": p.sort_order,
                    "connection_type_name": type_names.get(p.connection_type_id) if p.connection_type_id else None,
                }
                for p in ports.get(e.id, ())
            ],
            "created_by_email": _email(emails, e.creator_id), "created_at": _stamp(e.created_at),
            "is_archived": e.is_archived, "archived_at": _stamp(e.archived_at), "archived_by_email": _email(emails, e.archived_by),
            "tags": record_tag_names(db, ELEMENT_ARTEFACT_TYPE, e.id),
            "placements": record_placements(db, ELEMENT_ARTEFACT_TYPE, e.id),
        }
        for e in elements
    ]
    foreign = _foreign_refs(db, {
        end for c in connections for end in (c.source_element_id, c.target_element_id) if end not in codes
    })
    data[CONNECTIONS_KEY] = [
        {
            "unique_code": c.unique_code, "name": c.name, "type_name": type_names.get(c.connection_type_id),
            "source_code": codes.get(c.source_element_id), "source_port": port_names.get(c.source_port_id) if c.source_port_id else None,
            "source_ref": foreign.get(c.source_element_id),
            "target_code": codes.get(c.target_element_id), "target_port": port_names.get(c.target_port_id) if c.target_port_id else None,
            "target_ref": foreign.get(c.target_element_id),
            "protocol": c.protocol, "description": c.description, "status": c.status,
            "created_by_email": _email(emails, c.creator_id), "created_at": _stamp(c.created_at),
            "is_archived": c.is_archived, "archived_at": _stamp(c.archived_at), "archived_by_email": _email(emails, c.archived_by),
            "tags": record_tag_names(db, CONNECTION_ARTEFACT_TYPE, c.id),
            "placements": record_placements(db, CONNECTION_ARTEFACT_TYPE, c.id),
        }
        for c in connections
    ]
    data[COLLECTIONS_KEY] = _collections_json(
        db, ArchitectureCollection.project_id == project.id, lambda element_id: codes.get(element_id),
    )
    data[LINKS_KEY] = export_artefact_links(db, project, {
        ELEMENT_ARTEFACT_TYPE: {e.id: e.unique_code for e in elements},
        CONNECTION_ARTEFACT_TYPE: {c.id: c.unique_code for c in connections},
    })
    return data, assets


def reset_for_template(data: dict[str, Any]) -> None:
    """`ModuleProjectBundleHooks.template_reset`: starter elements and connections become fresh drafts (archived ones
    and their creators are dropped), and a connection or link whose element did not survive is removed. A
    connection that ended at an element another owner shares is removed too (a template points at nothing outside
    itself); a collection keeps only the members that survived."""
    fresh_drafts(data.get(ELEMENTS_KEY, []), status=RecordStatus.DRAFT.value)
    fresh_drafts(data.get(CONNECTIONS_KEY, []), status=RecordStatus.DRAFT.value)
    kept = {e["unique_code"] for e in data.get(ELEMENTS_KEY, [])}
    data[CONNECTIONS_KEY] = [
        c for c in data.get(CONNECTIONS_KEY, []) if c.get("source_code") in kept and c.get("target_code") in kept
    ]
    for collection in data.get(COLLECTIONS_KEY, []):
        collection["members"] = [code for code in collection.get("members", []) if code in kept]
    surviving = {
        ELEMENT_ARTEFACT_TYPE: kept, CONNECTION_ARTEFACT_TYPE: {c["unique_code"] for c in data[CONNECTIONS_KEY]},
    }
    data[LINKS_KEY] = [
        link for link in data.get(LINKS_KEY, [])
        if all(end["ref"] in surviving.get(end["type"], {end["ref"]}) for end in (link["source"], link["target"]))
    ]


def _type_row(vocabulary: ArchitectureVocabulary, db: Session, project: Project, name: str | None, warnings: BundleImportWarnings):
    """The vocabulary row named `name`: one the project can use, else any organisation or project row of that
    name (a default the project hides), else a new project row so the record keeps its type."""
    if not name:
        return None
    wanted = name.casefold()
    rows = [
        *vocabulary.resolve_effective(db, project.id, project.organization_id).rows,
        *vocabulary.project_rows(db, project.id), *vocabulary.org_rows(db, project.organization_id),
    ]
    found = next((r for r in rows if r.name.casefold() == wanted), None)
    if found is None:
        warnings.add(f"{vocabulary.label} {name!r} was not found here and was created in the project.")
        found = vocabulary.create(db, project_id=project.id, organization_id=project.organization_id, name=name)
    return found


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's own types and hides the organisation defaults
    it had hidden, then its elements (parents after their children are created), connections and links, numbered
    afresh. A name the project already lists is skipped; a reference that cannot be matched is reported."""
    _import_symbols(
        db, data.get(PROJECT_SYMBOLS_KEY, []), file_bytes_by_ref, project_id=project.id, organization_id=project.organization_id,
        actor_id=current_user.id,
        taken={r.name.lower() for r in SYMBOLS.resolve_effective(db, project.id, project.organization_id).rows}, warnings=warnings,
    )
    for name in SYMBOLS.hide_by_names(db, project.id, project.organization_id, data.get(HIDDEN_SYMBOLS_KEY, [])):
        warnings.add(f"Symbol {name!r} was hidden in the source project but the organisation has no such symbol.")
    type_symbol_for = _symbol_lookup(db, project.organization_id, project.id, warnings, "Element type")
    element_symbol_for = _symbol_lookup(db, project.organization_id, project.id, warnings, "Element")
    for vocabulary, _org_key, project_key, hidden_key in _VOCABULARIES:
        entries = data.get(project_key, [])
        if entries:
            taken = {r.name.lower() for r in vocabulary.resolve_effective(db, project.id, project.organization_id).rows}
            _add_rows(db, vocabulary, entries, taken=taken, owner={"project_id": project.id}, symbol_for=type_symbol_for)
        for name in vocabulary.hide_by_names(db, project.id, project.organization_id, data.get(hidden_key, [])):
            warnings.add(f"{vocabulary.label} {name!r} was hidden in the source project but the organisation has no such type.")

    created: dict[str, ArchitectureElement] = {}
    elements: dict[str, UUID] = {}
    connections: dict[str, UUID] = {}
    ports: dict[tuple[str, str], UUID] = {}
    seen: set[str] = set()
    for entry in data.get(ELEMENTS_KEY, []):
        code = entry.get("unique_code", "")
        element_type = _type_row(ELEMENT_TYPES, db, project, entry.get("type_name"), warnings)
        if code in seen or element_type is None:
            warnings.add(f"Element {code or '?'} skipped — {'it appears more than once' if code in seen else 'it has no type'}.")
            continue
        seen.add(code)
        creator = users.resolve(entry.get("created_by_email"), required=True, context=f"Element {code} creator")
        archived = bool(entry.get("is_archived"))
        element = ArchitectureElement(
            project_id=project.id, unique_code=generate_unique_code(db, project, ELEMENT_ARTEFACT_TYPE, ELEMENT_CODE_PREFIX),
            name=entry["name"], description=entry.get("description", ""), element_type_id=element_type.id, parent_id=None,
            symbol_id=element_symbol_for(entry.get("symbol")),
            status=entry.get("status", "draft"), version=1, creator_id=creator, is_archived=archived,
            archived_at=_instant(entry.get("archived_at")),
            archived_by=(users.resolve(entry.get("archived_by_email"), required=False, context=f"Element {code} archiver") or creator)
            if archived else None,
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=project.organization_id, project_id=project.id, users=users,
                warnings=warnings, context=f"Element {code} owner", required=False,
            ),
        )
        created_at = _instant(entry.get("created_at"))
        if created_at is not None:
            element.created_at = created_at
        db.add(element)
        db.flush()
        elements[code] = element.id
        created[code] = element
        for order, port in enumerate(entry.get("ports", [])):
            connection_type = _type_row(CONNECTION_TYPES, db, project, port.get("connection_type_name"), warnings)
            row = ArchitecturePort(
                element_id=element.id, name=port["name"], direction=port.get("direction", PortDirection.BOTH.value),
                connection_type_id=connection_type.id if connection_type else None, sort_order=port.get("sort_order", order),
            )
            db.add(row)
            db.flush()
            ports[(code, port["name"])] = row.id
        restore_record_tags(
            db, organization_id=project.organization_id, record_project_id=project.id, actor_id=creator,
            artefact_type=ELEMENT_ARTEFACT_TYPE, artefact_id=element.id, names=entry.get("tags"),
        )
        restore_record_placements(
            db, project_id=project.id, actor_id=creator, artefact_type=ELEMENT_ARTEFACT_TYPE, artefact_id=element.id,
            entries=entry.get("placements"),
        )
    for entry in data.get(ELEMENTS_KEY, []):
        parent_code = entry.get("parent_code")
        if not parent_code or entry.get("unique_code") not in elements:
            continue
        if parent_code not in elements:
            warnings.add(f"Element {entry['unique_code']}: parent {parent_code} is not in the bundle — left at the top level.")
            continue
        created[entry["unique_code"]].parent_id = elements[parent_code]
    db.flush()

    for entry in data.get(CONNECTIONS_KEY, []):
        code = entry.get("unique_code", "")
        connection_type = _type_row(CONNECTION_TYPES, db, project, entry.get("type_name"), warnings)
        source = elements.get(entry.get("source_code") or "") or _resolve_foreign(db, project, current_user, entry.get("source_ref"))
        target = elements.get(entry.get("target_code") or "") or _resolve_foreign(db, project, current_user, entry.get("target_ref"))
        if connection_type is None or source is None or target is None or source == target:
            warnings.add(
                f"Connection {code or '?'} skipped — its type, or one of its elements (in the bundle or shared with this "
                "project), is not available."
            )
            continue
        creator = users.resolve(entry.get("created_by_email"), required=True, context=f"Connection {code} creator")
        archived = bool(entry.get("is_archived"))
        connection = ArchitectureConnection(
            project_id=project.id,
            unique_code=generate_unique_code(db, project, CONNECTION_ARTEFACT_TYPE, CONNECTION_CODE_PREFIX),
            name=entry.get("name", ""), connection_type_id=connection_type.id, source_element_id=source,
            source_port_id=ports.get((entry.get("source_code") or "", entry.get("source_port") or "")),
            target_element_id=target, target_port_id=ports.get((entry.get("target_code") or "", entry.get("target_port") or "")),
            protocol=entry.get("protocol", ""), description=entry.get("description", ""),
            status=entry.get("status", "draft"), version=1, creator_id=creator, is_archived=archived,
            archived_at=_instant(entry.get("archived_at")),
            archived_by=(users.resolve(entry.get("archived_by_email"), required=False, context=f"Connection {code} archiver") or creator)
            if archived else None,
        )
        created_at = _instant(entry.get("created_at"))
        if created_at is not None:
            connection.created_at = created_at
        db.add(connection)
        db.flush()
        connections[code] = connection.id
        restore_record_tags(
            db, organization_id=project.organization_id, record_project_id=project.id, actor_id=creator,
            artefact_type=CONNECTION_ARTEFACT_TYPE, artefact_id=connection.id, names=entry.get("tags"),
        )
        restore_record_placements(
            db, project_id=project.id, actor_id=creator, artefact_type=CONNECTION_ARTEFACT_TYPE,
            artefact_id=connection.id, entries=entry.get("placements"),
        )
    _import_collections(
        db, data.get(COLLECTIONS_KEY, []), owner={"project_id": project.id},
        owner_filter=ArchitectureCollection.project_id == project.id, elements=elements, creator_id=current_user.id,
        warnings=warnings,
    )
    import_artefact_links(
        db, project, data.get(LINKS_KEY, []), {ELEMENT_ARTEFACT_TYPE: elements, CONNECTION_ARTEFACT_TYPE: connections},
        current_user, users, warnings, context="System Architecture",
    )
    db.flush()
