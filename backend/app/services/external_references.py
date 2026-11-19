"""
Module: services.external_references

External references on any record of any registered artefact type: the organisation's list of outside systems
(Jira, ServiceNow, ...), and the pointers from a record to an item in one of them (`models.external_reference`).

Responsibilities:
- `EXTERNAL_SYSTEMS`: the two-tier system vocabulary (organisation list; a project overrides, adds and hides entries),
  `seed_org_defaults`, and `resolve_system` (a payload's system id to the row a reference stores).
- Validation: `check_web_url` (a link is http or https only), `check_url_template` (one `{key}`), `link_for` (a
  reference's effective link: its own URL, else the system's template with the key URL-encoded in).
- A record's references: `references_for_records` (many records, a fixed number of statements), `add_reference`,
  `update_reference`, `remove_reference`, `get_reference`, `forget_record_references` and
  `convert_record_to_project` (an organisation-owned record that becomes a project's).
- `audit_reference`: the audit event a change writes against the record.
- Bundle halves: `export_record_references` / `import_record_references` (by system name, never id) and
  `copy_project_systems` (a template).

Design decisions:
- Keyed by the registered artefact type string like tags and placements, so a new type needs no code here; the
  record has no foreign key, so its owner calls `forget_record_references` when it deletes the record for good.
- A reference is metadata, not record content: it is not versioned with the record and is not blocked by an approval
  lock. The authority is the one for tags (`services.tags.can_tag`).
- Nested projects (**Decided by: User**): a child project with no system configuration of its own shows its nearest
  ancestor's effective list, else the organisation's (`TypeVocabulary(inherit_from_ancestors=True)`).
- A reference needs a key or a URL (or both). At most `MAX_REFERENCES` per record, so a list stays bounded.
- A URL or template that is not http(s) is rejected at every entry point (API, bundle, import), and `link_for` checks
  its result again, so a `javascript:` or `data:` link can never reach a rendered page or an export.

External dependencies: `models.external_reference`, `services.type_vocabulary`, `services.audit`, `modules.registry`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.external_reference import (
    ExternalReference,
    ExternalReferenceRole,
    ExternalSystemDefinition,
    ProjectExternalSystem,
)
from app.models.project import Project
from app.modules.registry import (
    artefact_type_module,
    get_all_registered_artefact_types,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
)
from app.services.audit import log_event
from app.services.type_vocabulary import TypeVocabulary

#: Most references one record may carry.
MAX_REFERENCES = 50
#: The longest a key, a URL, a template and a note may be (the columns' widths).
MAX_KEY_LENGTH = 100
MAX_URL_LENGTH = 500
MAX_NOTE_LENGTH = 500
#: The key of the sub-component a module may declare so an administrator can switch references off for its types
#: (stored references are kept; the endpoints answer 404 while it is off).
EXTERNAL_REFERENCES_SUBCOMPONENT_KEY = "external_references"
#: The one placeholder a URL template holds.
KEY_PLACEHOLDER = "{key}"
DEFAULT_EXTERNAL_SYSTEMS: tuple[str, ...] = ("Jira", "ServiceNow", "Zendesk", "Azure DevOps", "GitHub", "Other")
#: The entry a legacy single delivery link was filed under, and the one the Other fallback uses.
OTHER_NAME = "Other"


# --- validation ---------------------------------------------------------------------------------


def check_web_url(value: str | None) -> str | None:
    """Accepts only an absolute `http` or `https` URL (or nothing). A reference is rendered as a link, and a
    `javascript:` or `data:` URL stored there would run in the viewer's browser or in an export.

    Raises:
        ValueError: If a non-empty value is not an http(s) URL with a host.
    """
    if not value:
        return value
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("A link must be an http or https URL.")
    return value.strip()


def check_url_template(value: str | None) -> str | None:
    """Accepts a URL template: an http(s) URL holding `{key}` exactly once and no other braces (or nothing).

    Raises:
        ValueError: If the template is not an http(s) URL, lacks `{key}`, repeats it, or holds another brace.
    """
    if not value or not value.strip():
        return None
    template = value.strip()
    if template.count(KEY_PLACEHOLDER) != 1:
        raise ValueError("A link template must contain {key} exactly once.")
    if "{" in template.replace(KEY_PLACEHOLDER, "") or "}" in template.replace(KEY_PLACEHOLDER, ""):
        raise ValueError("A link template may contain only the {key} placeholder.")
    check_web_url(template.replace(KEY_PLACEHOLDER, "key"))
    return template


def _clean_extra(column: str, value: Any) -> Any:
    """`TypeVocabulary.clean_extra`: validates a bundle's `url_template`."""
    return check_url_template(value) if column == "url_template" else value


def link_for(url: str | None, template: str | None, key: str) -> str | None:
    """The link a reference opens: its own URL, else the system's template with `key` URL-encoded in, else none.
    The result is checked again, so a stored value that predates a rule can never be returned as a link."""
    candidate = url or (template.replace(KEY_PLACEHOLDER, quote(key, safe="")) if template and key else None)
    if not candidate:
        return None
    try:
        return check_web_url(candidate)
    except ValueError:
        return None


# --- the system vocabulary ---------------------------------------------------------------------


def _org_system_in_use(db: Session, type_id: uuid.UUID) -> bool:
    return db.scalar(select(ExternalReference.id).where(ExternalReference.org_system_id == type_id).limit(1)) is not None


def _project_system_in_use(db: Session, type_id: uuid.UUID) -> bool:
    return db.scalar(select(ExternalReference.id).where(ExternalReference.project_system_id == type_id).limit(1)) is not None


EXTERNAL_SYSTEMS = TypeVocabulary(
    kind="external_system",
    label="External system",
    org_model=ExternalSystemDefinition,
    project_model=ProjectExternalSystem,
    default_names=DEFAULT_EXTERNAL_SYSTEMS,
    org_type_in_use=_org_system_in_use,
    project_type_in_use=_project_system_in_use,
    inherit_from_ancestors=True,
    extra_columns=("url_template",),
    clean_extra=_clean_extra,
)


def seed_org_defaults(db: Session, organization_id: uuid.UUID) -> None:
    """Gives a new organisation the default systems (`run_on_org_created_hooks`; the caller commits)."""
    EXTERNAL_SYSTEMS.seed_defaults(db, organization_id)


def resolve_system(
    db: Session, organization_id: uuid.UUID, project: Project | None, system_id: uuid.UUID,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolves a payload's system id to the `(org_system_id, project_system_id)` pair a reference stores.

    Args:
        db: Active session (a passthrough project row may be added; the caller commits).
        organization_id: The record's organisation.
        project: The record's project, or `None` for an organisation-owned record.
        system_id: An `EffectiveType.id` of the record's tier (the project's list, or the organisation's).

    Raises:
        ValueError: If the id is not an enabled system of that tier.
    """
    if project is None:
        org_type = db.get(ExternalSystemDefinition, system_id)
        if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
            raise ValueError("This is not a valid external system for this organisation.")
        return org_type.id, None
    return None, EXTERNAL_SYSTEMS.usable_row_id(db, project.id, organization_id, system_id)


def other_system_id(db: Session, organization_id: uuid.UUID) -> uuid.UUID | None:
    """The organisation's active "Other" system, or `None` when it has removed or disabled it."""
    return db.scalar(select(ExternalSystemDefinition.id).where(
        ExternalSystemDefinition.organization_id == organization_id, ExternalSystemDefinition.name == OTHER_NAME,
        ExternalSystemDefinition.is_active.is_(True),
    ))


# --- output -------------------------------------------------------------------------------------


class ExternalReferenceOut(BaseModel):
    """A reference with its system's name and effective link. `system_id` is accepted back by the system picker of
    the record's tier; `link` is `url` or, without one, the system's template with the key in it."""

    id: uuid.UUID
    artefact_type: str
    artefact_id: uuid.UUID
    system_id: uuid.UUID
    system_name: str
    key: str
    url: str | None = None
    link: str | None = None
    note: str = ""
    role: ExternalReferenceRole | None = None
    created_by: uuid.UUID
    created_at: datetime


def references_for_records(
    db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, list[ExternalReferenceOut]]:
    """The references of many records of one type, oldest first, in a fixed number of statements (the rows, then the
    systems they name). A record with none is present with an empty list."""
    out: dict[uuid.UUID, list[ExternalReferenceOut]] = {i: [] for i in artefact_ids}
    if not out:
        return out
    rows = list(db.scalars(
        select(ExternalReference).where(ExternalReference.artefact_type == artefact_type, ExternalReference.artefact_id.in_(list(out)))
        .order_by(ExternalReference.created_at, ExternalReference.id)
    ))
    names, templates = _system_details(db, rows)
    for row in rows:
        out[row.artefact_id].append(reference_out(row, names, templates))
    return out


def _system_details(
    db: Session, rows: Sequence[ExternalReference],
) -> tuple[dict[tuple[uuid.UUID | None, uuid.UUID | None], str | None], dict[tuple[uuid.UUID | None, uuid.UUID | None], str | None]]:
    """`(names, templates)` keyed by `(org_system_id, project_system_id)` for the systems `rows` name: the effective
    display name, and the effective URL template (a project row's own, else its organisation entry's)."""
    pairs = {(r.org_system_id, r.project_system_id) for r in rows}
    names = EXTERNAL_SYSTEMS.display_names(db, pairs)
    project_ids = {p for _o, p in pairs if p is not None}
    project_rows = {
        r.id: r for r in db.scalars(select(ProjectExternalSystem).where(ProjectExternalSystem.id.in_(project_ids)))
    } if project_ids else {}
    org_ids = {o for o, p in pairs if p is None and o is not None}
    org_ids |= {r.org_type_id for r in project_rows.values() if r.org_type_id is not None}
    org_rows = {
        r.id: r for r in db.scalars(select(ExternalSystemDefinition).where(ExternalSystemDefinition.id.in_(org_ids)))
    } if org_ids else {}
    templates: dict[tuple[uuid.UUID | None, uuid.UUID | None], str | None] = {}
    for org_id, project_id in pairs:
        if project_id is not None:
            row = project_rows.get(project_id)
            org_row = org_rows.get(row.org_type_id) if row is not None and row.org_type_id else None
            templates[(org_id, project_id)] = (
                (row.url_template if row is not None and row.url_template is not None else None)
                or (org_row.url_template if org_row is not None else None)
            )
        else:
            org_row = org_rows.get(org_id) if org_id is not None else None
            templates[(org_id, project_id)] = org_row.url_template if org_row is not None else None
    return names, templates


def reference_out(
    row: ExternalReference, names: dict[tuple[uuid.UUID | None, uuid.UUID | None], str | None],
    templates: dict[tuple[uuid.UUID | None, uuid.UUID | None], str | None],
) -> ExternalReferenceOut:
    """The API shape of one reference; `system_id` is the id the system picker of the record's tier uses."""
    pair = (row.org_system_id, row.project_system_id)
    system_id = row.project_system_id or row.org_system_id
    assert system_id is not None  # the CHECK constraint guarantees one
    return ExternalReferenceOut(
        id=row.id, artefact_type=row.artefact_type, artefact_id=row.artefact_id, system_id=system_id,
        system_name=names.get(pair) or "", key=row.key, url=row.url, link=link_for(row.url, templates.get(pair), row.key),
        note=row.note, role=row.role, created_by=row.created_by, created_at=row.created_at,
    )


# --- changes ------------------------------------------------------------------------------------


def _check_type(artefact_type: str) -> None:
    """Raises `ValueError` for a type no module registers."""
    if artefact_type not in get_all_registered_artefact_types():
        raise ValueError(f"{artefact_type!r} is not a registered record type.")


def references_enabled(db: Session, artefact_type: str, *, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> bool:
    """Whether references are switched on for records of `artefact_type` here. A type is always on unless its module
    declares a sub-component keyed `EXTERNAL_REFERENCES_SUBCOMPONENT_KEY`, whose effective state (a project's own
    switch, else the organisation default; for an organisation-owned record the organisation's) then decides."""
    definition = artefact_type_module(artefact_type)
    if definition is None or not any(sub.key == EXTERNAL_REFERENCES_SUBCOMPONENT_KEY for sub in definition.sub_components):
        return True
    if project_id is not None:
        return is_module_subcomponent_enabled(db, project_id, definition.key, EXTERNAL_REFERENCES_SUBCOMPONENT_KEY)
    return is_org_module_subcomponent_enabled(db, organization_id, definition.key, EXTERNAL_REFERENCES_SUBCOMPONENT_KEY)


def count_references(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> int:
    """How many references the record carries."""
    return db.scalar(select(func.count()).select_from(ExternalReference).where(
        ExternalReference.artefact_type == artefact_type, ExternalReference.artefact_id == artefact_id,
    )) or 0


def add_reference(
    db: Session, *, artefact_type: str, artefact_id: uuid.UUID, organization_id: uuid.UUID, project: Project | None,
    system_id: uuid.UUID, key: str, url: str | None = None, note: str = "", role: ExternalReferenceRole | None = None,
    actor_id: uuid.UUID,
) -> ExternalReference:
    """Adds a reference to a record (flushed, not committed, no audit; the caller authorised the record).

    Raises:
        ValueError: If the type is unregistered, the record already has `MAX_REFERENCES`, neither a key nor a link is
            given, the link is not http(s), or the system is not an enabled one of the record's tier.
    """
    _check_type(artefact_type)
    key = key.strip()
    url = check_web_url(url) or None
    if not key and not url:
        raise ValueError("A reference needs a key or a link.")
    if len(key) > MAX_KEY_LENGTH or len(url or "") > MAX_URL_LENGTH or len(note) > MAX_NOTE_LENGTH:
        raise ValueError("A reference key, link or note is too long.")
    if count_references(db, artefact_type, artefact_id) >= MAX_REFERENCES:
        raise ValueError(f"A record can have at most {MAX_REFERENCES} references.")
    org_system_id, project_system_id = resolve_system(db, organization_id, project, system_id)
    row = ExternalReference(
        artefact_type=artefact_type, artefact_id=artefact_id, organization_id=organization_id,
        project_id=project.id if project is not None else None, org_system_id=org_system_id,
        project_system_id=project_system_id, key=key, url=url, note=note.strip(), role=role, created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def get_reference(
    db: Session, artefact_type: str, artefact_id: uuid.UUID, reference_id: uuid.UUID,
) -> ExternalReference | None:
    """A reference of the record, or `None` (also for another record's reference id)."""
    row = db.get(ExternalReference, reference_id)
    if row is None or row.artefact_type != artefact_type or row.artefact_id != artefact_id:
        return None
    return row


def update_reference(
    db: Session, row: ExternalReference, project: Project | None, changes: dict[str, Any],
) -> ExternalReference:
    """Applies the keys present in `changes` (`system_id`, `key`, `url`, `note`, `role`) to a reference (flushed, not
    committed). `url` or `role` of `None` clears it.

    Raises:
        ValueError: If the result has neither a key nor a link, the link is not http(s), or `system_id` is not usable.
    """
    if changes.get("system_id") is not None:
        row.org_system_id, row.project_system_id = resolve_system(db, row.organization_id, project, changes["system_id"])
    if changes.get("key") is not None:
        row.key = changes["key"].strip()
    if "url" in changes:
        row.url = check_web_url(changes["url"]) or None
    if changes.get("note") is not None:
        row.note = changes["note"].strip()
    if "role" in changes:
        row.role = changes["role"]
    if not row.key and not row.url:
        raise ValueError("A reference needs a key or a link.")
    if len(row.key) > MAX_KEY_LENGTH or len(row.url or "") > MAX_URL_LENGTH or len(row.note) > MAX_NOTE_LENGTH:
        raise ValueError("A reference key, link or note is too long.")
    db.flush()
    return row


def remove_reference(db: Session, row: ExternalReference) -> None:
    """Deletes a reference (flushed, not committed)."""
    db.delete(row)
    db.flush()


def forget_record_references(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> None:
    """Drops every reference of a record that is being deleted for good (there is no foreign key, so the record's
    owner calls this)."""
    db.execute(delete(ExternalReference).where(
        ExternalReference.artefact_type == artefact_type, ExternalReference.artefact_id == artefact_id,
    ))


def audit_reference(
    db: Session, row: ExternalReference, action: str, actor_id: uuid.UUID | None, *, entity_type: str | None = None,
) -> None:
    """Writes `reference_added`, `reference_updated` or `reference_removed` against the record. The detail names the
    reference, its role and whether it carries a link, never the key or the link (an identifier in a customer's
    system is not for the audit trail)."""
    log_event(
        db, entity_type=entity_type or row.artefact_type, entity_id=row.artefact_id, action=action, actor_id=actor_id,
        organization_id=row.organization_id, project_id=row.project_id,
        detail={"reference_id": str(row.id), "role": row.role.value if row.role else None, "has_url": bool(row.url)},
    )


def _local_system(db: Session, project: Project, name: str) -> ProjectExternalSystem:
    """The project's own system called `name`, created if it has none."""
    existing = db.scalar(select(ProjectExternalSystem).where(
        ProjectExternalSystem.project_id == project.id, ProjectExternalSystem.org_type_id.is_(None),
        ProjectExternalSystem.name_override == name,
    ))
    return existing if existing is not None else EXTERNAL_SYSTEMS.create_project_local(db, project.id, name)


def convert_record_to_project(db: Session, artefact_type: str, artefact_id: uuid.UUID, project: Project) -> int:
    """Re-points an organisation-owned record's references at `project`'s systems (the caller has already re-owned the
    record). A system the project hides, or has disabled, is kept as a project-local system of the same name so the
    reference still reads the same.

    Returns:
        How many references were converted.
    """
    rows = list(db.scalars(select(ExternalReference).where(
        ExternalReference.artefact_type == artefact_type, ExternalReference.artefact_id == artefact_id,
        ExternalReference.org_system_id.is_not(None),
    )))
    for row in rows:
        org_system = db.get(ExternalSystemDefinition, row.org_system_id)
        assert org_system is not None  # the FK guarantees it
        try:
            _org_id, project_id = resolve_system(db, project.organization_id, project, org_system.id)
        except ValueError:
            project_id = _local_system(db, project, org_system.name).id
        row.org_system_id = None
        row.project_system_id = project_id
        row.project_id = project.id
    db.flush()
    return len(rows)


# --- bundles and templates --------------------------------------------------------------------


def export_record_references(
    db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """`{record id: [bundle entry]}` for the records' references, by system name (never id, so a bundle moves between
    organisations): `{"system", "key", "url", "note", "role"}`."""
    return {
        record_id: [
            {"system": r.system_name, "key": r.key, "url": r.url, "note": r.note, "role": r.role.value if r.role else None}
            for r in refs
        ]
        for record_id, refs in references_for_records(db, artefact_type, artefact_ids).items()
    }


def import_record_references(
    db: Session, *, artefact_type: str, artefact_id: uuid.UUID, organization_id: uuid.UUID, project: Project | None,
    entries: Sequence[dict[str, Any]] | None, systems, actor_id: uuid.UUID,
) -> int:
    """Recreates a record's references from bundle entries (flushed, not committed). `systems` is a
    `services.vocabulary_bundle.NameResolver` for `EXTERNAL_SYSTEMS` at the record's tier, which turns a name into the
    row to store. An entry with no key and no link, an unusable link, or a name nothing can place is skipped.

    Returns:
        How many references were created.
    """
    created = 0
    for entry in list(entries or [])[:MAX_REFERENCES]:
        system_id = systems.row_id(entry.get("system"))
        if system_id is None or not (entry.get("key") or entry.get("url")):
            continue
        try:
            role = ExternalReferenceRole(entry["role"]) if entry.get("role") else None
            row = ExternalReference(
                artefact_type=artefact_type, artefact_id=artefact_id, organization_id=organization_id,
                project_id=project.id if project is not None else None,
                org_system_id=system_id if project is None else None,
                project_system_id=system_id if project is not None else None, key=(entry.get("key") or "").strip()[:MAX_KEY_LENGTH],
                url=check_web_url(entry.get("url")) or None, note=(entry.get("note") or "").strip()[:MAX_NOTE_LENGTH], role=role,
                created_by=actor_id,
            )
        except ValueError:
            continue
        db.add(row)
        created += 1
    db.flush()
    return created


def prime_record_references(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> None:
    """Reads the references of many records of one type in a fixed number of statements, for `record_references` to
    answer from. Like `services.tags.prime_record_tag_names` it only has an effect inside a `memoize_module_state()`
    block (an export); elsewhere it does nothing."""
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    if memo is None:
        return
    ids = list(artefact_ids)
    for record_id, entries in export_record_references(db, artefact_type, ids).items():
        memo[("record_references", artefact_type, record_id)] = entries


def record_references(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[dict[str, Any]]:
    """A record's references as bundle entries (from `prime_record_references` when the export primed them)."""
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    if memo is not None and ("record_references", artefact_type, artefact_id) in memo:
        return [dict(e) for e in memo[("record_references", artefact_type, artefact_id)]]
    return export_record_references(db, artefact_type, [artefact_id])[artefact_id]


def share_system_resolver(db: Session, resolver: Any) -> None:
    """Makes an import's `NameResolver` for `EXTERNAL_SYSTEMS` the one `restore_record_references` uses for its owner
    (a project's bundle import calls this once the project's own systems exist), so every module's records resolve
    names against the same rows and the import's warnings collect in one place."""
    db.info.setdefault("reference_systems", {})[(resolver.organization_id, resolver.project.id if resolver.project is not None else None)] = resolver


def restore_record_references(
    db: Session, *, organization_id: uuid.UUID, record_project_id: uuid.UUID | None, actor_id: uuid.UUID | None,
    artefact_type: str, artefact_id: uuid.UUID, entries: Sequence[dict[str, Any]] | None, warnings: Any = None,
) -> None:
    """Applies a bundle row's references to its newly created record, by system name.

    A name the target has no system for becomes a system of the target project's own, with a warning when `warnings`
    (a `BundleImportWarnings`) is given, so a reference is never dropped. The resolver is kept for the import (on the
    session), so a bundle of thousands of records reads the system lists once.

    Args:
        db: Active session; rows are added, not committed.
        organization_id: The organisation being imported into.
        record_project_id: The record's owning project, or `None` for a record the organisation owns.
        actor_id: The importing user (falls back to the record's creator being unknown: such an entry is skipped).
        artefact_type / artefact_id: The new record.
        entries: The row's `record_references` output (nothing to do when empty or absent).
        warnings: Where a system the target lacks is reported.
    """
    if not entries or actor_id is None:
        return
    from app.services.bundle_common import BundleImportWarnings
    from app.services.vocabulary_bundle import NameResolver

    cache = db.info.setdefault("reference_systems", {})
    key = (organization_id, record_project_id)
    resolver = cache.get(key)
    if resolver is None:
        project = db.get(Project, record_project_id) if record_project_id is not None else None
        resolver = cache[key] = NameResolver(
            db, EXTERNAL_SYSTEMS, organization_id, project, warnings or BundleImportWarnings(), "external system",
        )
    elif warnings is not None:
        resolver.warnings = warnings
    import_record_references(
        db, artefact_type=artefact_type, artefact_id=artefact_id, organization_id=organization_id,
        project=resolver.project, entries=entries, systems=resolver, actor_id=actor_id,
    )


def copy_project_systems(db: Session, source: Project, target: Project) -> None:
    """Copies `source`'s own system configuration (overrides, project-local systems, hidden defaults) to `target`, a
    project made from a template (not committed). The template's references to them are records and are not copied here."""
    from app.services.bundle_common import BundleImportWarnings
    from app.services.vocabulary_bundle import NameResolver, export_project_list

    exported = export_project_list(db, source, EXTERNAL_SYSTEMS)
    resolver = NameResolver(db, EXTERNAL_SYSTEMS, target.organization_id, target, BundleImportWarnings(), "external system")
    resolver.import_project_rows(exported["rows"])
    resolver.hide(exported["hidden"])
