"""
Module: services.report_exchange

Report layouts and packs as a single `.zip` file a person can keep, send or attach, and bring into another project,
organisation or installation.

Responsibilities:
- `build_export`: the selected layouts and packs (and the layouts the packs name) as a file.
- `read_file`: opens an uploaded file defensively and returns its parts; nothing is stored.
- `plan_import` / `apply_import`: what importing the file into one tier would create, rename, skip or refuse, and doing
  it in the caller's transaction (the caller commits) with one audit event.

File layout: `manifest.json` (kind, format version, counts), `reports.json` (`layouts`, `packs`, `images`) and
`files/<n>_<name>` (one per picture). The layout and pack entries are the project bundle's own
(`report_layout_bundle.layout_entry`, `report_pack_bundle.pack_entry`), so a field added to a layout reaches the file
with no change here.

Design decisions:
- **One serialiser.** Import goes through the bundle importers (`import_layout_entry`, `import_pack_entry`), which
  validate every tree again and use the normal create path. Nothing here reads or writes a layout's content itself.
- **The file is untrusted input.** Size, entry count, entry names (only the three known shapes; a name is never used
  as a path), a per-entry and total uncompressed cap read with a cap (a header that lies cannot inflate more), a
  compression-ratio limit, item and version counts, and every picture re-sniffed and (SVG) re-sanitised exactly as an
  upload to the library is. An EPS or PDF is never converted from a file: an exported picture is already a raster or SVG.
- **No people in the file.** The author emails the bundle carries are dropped: a file travels beyond the organisation.
  The importer is the author of what it creates; version times in the file are information only.
- **Current version by default.** `include_history` carries every published version (never a draft); the importer renumbers
  them 1..n. Without it the current version becomes version 1, noted "Imported from file".
- **Never a silent replace.** A name the target tier owns is renamed "<name> (copy)" or skipped (the caller's choice);
  one that matches an inherited report is allowed and warned about, as any project report is.
- **Packs bring their layouts.** Exporting a pack also exports the layouts it names that its source scope can reach
  (unless asked not to), with the saved sets as that scope sees them. Import creates layouts first and re-points a
  pack's entries at a renamed layout.
- **Pictures.** Each is stored in the target tier's library (a project's for a project import, the organisation's for an
  organisation import) as the target's own, so a file never references another organisation's library. An organisation
  picture that already belongs to the importing organisation is reused by reference. A layout whose picture cannot be
  stored is dropped with a reason, like any invalid version.
- **Not carried:** ids, owners, pack membership of a layout the pack does not name, placements, favourites, drafts, and
  who may run a report; they belong to the target. A layout holds no Restricted-classified value.
- The audit event holds counts and keys only, never layout text or names.

Dependencies: `services.report_layout_bundle`, `services.report_pack_bundle`, `services.report_layout_scope`,
`services.report_pack_scope`, `services.report_images`, `services.bundle_common`.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack
from app.models.user import User
from app.modules.registry import get_all_reports, report_enabled_for_project
from app.services import (
    report_layout_bundle,
    report_layout_designer,
    report_layout_scope,
    report_layouts,
    report_pack_bundle,
    report_pack_sets,
    report_packs,
)
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings, new_bundle_file, write_json_entry
from app.services.files import read_file, upload_file, uploads_allowed
from app.services.report_copy import free_name, layout_warnings
from app.services.report_file_names import clean_filename
from app.services.report_images import SVG_TYPE, image_nodes, max_image_bytes, sniff_image
from app.services.report_org_values import organization_colour_names
from app.services.report_raster import ImageRejectedError
from app.services.report_svg import sanitize_svg

FILE_KIND = "reqtrack-report-file"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
REPORTS = "reports.json"

#: Limits on an uploaded file (see the module docstring).
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 600
MAX_RATIO = 200
MAX_ITEMS = 100
MAX_IMAGES = 200
MAX_VERSIONS = 200
IMPORT_NOTE = "Imported from file"

_PICTURE_NAME = re.compile(r"^files/[0-9]{1,4}_[^/\\\x00-\x1f]{1,200}$")

OnConflict = Literal["rename", "skip"]
Kind = Literal["layout", "pack"]
Action = Literal["create", "rename", "skip", "left_out"]


class ReportFileError(ValueError):
    """The uploaded file is not a report file this installation can read; `too_large` marks a size-limit refusal."""

    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.too_large = too_large


@dataclass
class ExportResult:
    """A built file and what could not be included.

    Attributes:
        file: The finished zip (spooled; the caller sends and closes it).
        layouts / packs / pictures: How many of each it holds.
        left_out: Layout names a pack names that the source scope cannot reach, so they are not in the file.
    """

    file: IO[bytes]
    layouts: int
    packs: int
    pictures: int
    left_out: list[str] = field(default_factory=list)


@dataclass
class ReportFile:
    """The parts of an uploaded file after the safety checks."""

    manifest: dict[str, Any]
    layouts: list[dict[str, Any]]
    packs: list[dict[str, Any]]
    images: list[dict[str, Any]]
    pictures: dict[str, bytes]


@dataclass
class ImportItem:
    """One layout or pack in the file and what the import does with it.

    Attributes:
        kind: `layout` or `pack`.
        name: The name in the file.
        new_name: The name it gets (differs from `name` on a rename).
        action: `create`, `rename`, `skip` (name taken and the caller chose skip) or `left_out` (nothing in it is valid).
        versions: How many versions it brings.
        warnings: What does not carry cleanly or why it is left out.
        new_id: The created layout or pack, set once applied.
    """

    kind: Kind
    name: str
    new_name: str
    action: Action
    versions: int
    warnings: list[str] = field(default_factory=list)
    new_id: uuid.UUID | None = None


@dataclass
class ImportPlan:
    """The outcome of a plan (or, once applied, of the import)."""

    items: list[ImportItem] = field(default_factory=list)
    pictures: int = 0
    warnings: list[str] = field(default_factory=list)

    def count(self, kind: Kind, *actions: Action) -> int:
        """How many items of `kind` ended in one of `actions`."""
        return sum(1 for i in self.items if i.kind == kind and i.action in actions)


# --- export ---------------------------------------------------------------------------------------------------------


def _anonymous(entry: dict[str, Any], *, latest: int | None) -> dict[str, Any]:
    """The bundle entry without author emails; with only version `latest` (noted as imported from a file) when given."""
    versions = entry["versions"]
    if latest is not None:
        versions = [v for v in versions if v["version"] == latest]
        for v in versions:
            v["comment"] = f"{IMPORT_NOTE}: {entry['name']}, version {v['version']}"[: report_layouts.MAX_COMMENT_CHARS]
    for v in versions:
        v.pop("created_by_email", None)
    return {**entry, "versions": versions}


def pack_layout_names(pack: ReportPack, db: Session) -> list[str]:
    """The layout names the pack's current version lists, in order, without repeats."""
    version = report_packs.current_version(db, pack)
    names = [str(e.get("name", "")) for e in version.definition.get("entries", []) if e.get("kind") == "layout"]
    return list(dict.fromkeys(n for n in names if n))


def build_export(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, layouts: list[ReportLayout], packs: list[ReportPack],
    include_history: bool, include_pack_layouts: bool, exported_by: User,
) -> ExportResult:
    """Builds the report file for `layouts` and `packs` that the caller's scope can reach.

    Args:
        db: Active session (read only).
        organization_id: The source organisation.
        project: The source project, or `None` for the organisation's own reports.
        layouts / packs: The selected rows (the route has already checked the scope).
        include_history: Every published version instead of the current one.
        include_pack_layouts: Also export the layouts the packs name that the scope can reach.
        exported_by: Recorded in the audit event by the caller; not written into the file.

    Returns:
        The file and its counts. The caller owns `file`.
    """
    reachable = (
        {s.layout.name.casefold(): s.layout for s in report_layout_scope.resolve_project_layouts(db, project) if not s.hidden}
        if project is not None
        else {lay.name.casefold(): lay for lay in report_layout_scope.list_org_layouts(db, organization_id)}
    )
    chosen: dict[uuid.UUID, ReportLayout] = {lay.id: lay for lay in layouts}
    left_out: list[str] = []
    if include_pack_layouts:
        for pack in packs:
            for name in pack_layout_names(pack, db):
                found = reachable.get(name.casefold())
                if found is None:
                    left_out.append(name)
                else:
                    chosen.setdefault(found.id, found)
    layout_entries = [
        _anonymous(
            report_layout_bundle.layout_entry(db, lay),
            latest=None if include_history else lay.current_version,
        )
        for lay in chosen.values()
    ]
    pack_entries = []
    for pack in packs:
        sets = [(e.row.name, e.effective) for e in report_pack_sets.effective_sets(db, pack, project)]
        pack_entries.append(_anonymous(
            report_pack_bundle.pack_entry(db, pack, sets=sets),
            latest=None if include_history else pack.current_version,
        ))
    assets: dict[uuid.UUID, FileAsset] = {}
    images = report_layout_bundle.image_entries(db, layout_entries, organization_id, project.id if project else None, assets)
    for index, image in enumerate(images):
        image["file_ref"] = f"files/{index}_{clean_filename(str(image['filename']), limit=100)}"
    manifest = {
        "kind": FILE_KIND, "format_version": FORMAT_VERSION, "exported_at": datetime.now(UTC).isoformat(),
        "history": include_history, "layouts": len(layout_entries), "packs": len(pack_entries), "pictures": len(images),
        "left_out": sorted(set(left_out)),
    }
    bundle = new_bundle_file()
    try:
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
            write_json_entry(zf, REPORTS, {"layouts": layout_entries, "packs": pack_entries, "images": images})
            for image in images:
                zf.writestr(image["file_ref"], read_file(assets[uuid.UUID(image["id"])]))
    except BaseException:
        bundle.close()
        raise
    return ExportResult(
        file=bundle, layouts=len(layout_entries), packs=len(pack_entries), pictures=len(images), left_out=sorted(set(left_out)),
    )


# --- reading an uploaded file ----------------------------------------------------------------------------------------


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """The entry's bytes, refusing more than `limit` however large its header claims."""
    with zf.open(info) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ReportFileError("The file holds an entry larger than a report file allows.", too_large=True)
    return data


def read_file_bytes(data: bytes) -> ReportFile:
    """Opens an uploaded report file and returns its parts after every safety check.

    Args:
        data: The uploaded bytes.

    Returns:
        The parts; nothing is stored.

    Raises:
        ReportFileError: Not a report file, a newer format, an unexpected entry, or over a limit.
    """
    if len(data) > MAX_FILE_BYTES:
        raise ReportFileError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.", too_large=True)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ReportFileError("This is not a report file (it must be the .zip a report export produced).") from None
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ReportFileError("The file holds too many entries.", too_large=True)
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        raise ReportFileError("The file repeats an entry name.")
    total = 0
    for info in infos:
        if info.is_dir():
            continue
        if info.filename not in (MANIFEST, REPORTS) and not _PICTURE_NAME.match(info.filename):
            raise ReportFileError("The file holds an entry a report file does not have.")
        total += info.file_size
        if info.compress_size and info.file_size > 1024 * 1024 and info.file_size / info.compress_size > MAX_RATIO:
            raise ReportFileError("The file compresses suspiciously well and was refused.", too_large=True)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ReportFileError("The file's contents are larger than a report file allows.", too_large=True)
    by_name = {i.filename: i for i in infos if not i.is_dir()}
    if MANIFEST not in by_name or REPORTS not in by_name:
        raise ReportFileError("This is not a report file (manifest or reports missing).")
    try:
        manifest = json.loads(_read_capped(zf, by_name[MANIFEST], MAX_JSON_BYTES))
        body = json.loads(_read_capped(zf, by_name[REPORTS], MAX_JSON_BYTES))
    except (json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile):
        raise ReportFileError("This is not a report file (its contents cannot be read).") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != FILE_KIND or not isinstance(body, dict):
        raise ReportFileError("This is not a report file.")
    version = manifest.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ReportFileError("This is not a report file (no format version).")
    if version > FORMAT_VERSION:
        raise ReportFileError("This file was made by a newer version of the application and cannot be imported here.")
    parts: dict[str, list[dict[str, Any]]] = {}
    for key, limit in (("layouts", MAX_ITEMS), ("packs", MAX_ITEMS), ("images", MAX_IMAGES)):
        value = body.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
            raise ReportFileError(f"The file's {key} are not in the expected shape.")
        if len(value) > limit:
            raise ReportFileError(f"The file holds more than {limit} {key}.", too_large=True)
        parts[key] = value
    for entry in [*parts["layouts"], *parts["packs"]]:
        versions = entry.get("versions", [])
        if not isinstance(versions, list) or len(versions) > MAX_VERSIONS:
            raise ReportFileError("A layout or pack in the file has more versions than a report file allows.", too_large=True)
    picture_limit = max_image_bytes()
    pictures: dict[str, bytes] = {}
    for image in parts["images"]:
        ref = str(image.get("file_ref", ""))
        found = by_name.get(ref)
        if found is None or not _PICTURE_NAME.match(ref):
            continue
        pictures[ref] = _read_capped(zf, found, picture_limit)
    return ReportFile(manifest, parts["layouts"], parts["packs"], parts["images"], pictures)


# --- import ---------------------------------------------------------------------------------------------------------


def _layout_versions(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for v in entry.get("versions", []) if isinstance(v, dict) and isinstance(v.get("tree"), dict)]


def _pack_versions(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for v in entry.get("versions", []) if isinstance(v, dict) and isinstance(v.get("definition"), dict)]


def _taken(db: Session, model: type[ReportLayout] | type[ReportPack], organization_id: uuid.UUID, project: Project | None) -> set[str]:
    where = model.project_id == project.id if project is not None else (
        model.organization_id == organization_id) & model.project_id.is_(None)
    return {n.casefold() for n in db.scalars(select(model.name).where(where))}


def _tree_problems(db: Session, trees: list[dict[str, Any]], organization: Organization | None) -> list[str]:
    """The first tree problem of each version that is not valid here (pictures are checked when they are stored)."""
    colours = organization_colour_names(organization) if organization is not None else None
    found: list[str] = []
    for tree in trees:
        analysis = report_layout_designer.check_tree(tree, colours)
        if not analysis.ok:
            found.append(f"{analysis.errors[0].path}: {analysis.errors[0].message}" if analysis.errors else "not valid")
    return found


def _pack_warnings(
    db: Session, entry: dict[str, Any], project: Project | None, file_layouts: set[str], target_layouts: set[str],
) -> list[str]:
    """Pack entries that will not resolve: layouts in neither the file nor the target, reports of modules that are off."""
    missing: set[str] = set()
    off: set[str] = set()
    unknown: set[str] = set()
    reports = {(mk, d.key): d for mk, d in get_all_reports()}
    for version in _pack_versions(entry)[-1:]:
        for e in version["definition"].get("entries", []):
            if not isinstance(e, dict):
                continue
            if e.get("kind") == "layout":
                name = str(e.get("name", "")).casefold()
                if name and name not in file_layouts and name not in target_layouts:
                    missing.add(str(e.get("name")))
            elif e.get("kind") == "report":
                definition = reports.get((str(e.get("module_key")), str(e.get("report"))))
                if definition is None:
                    unknown.add(f"{e.get('module_key')}.{e.get('report')}")
                elif project is not None and not report_enabled_for_project(db, project.id, str(e["module_key"]), definition):
                    off.add(str(e["module_key"]))
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"Entries use layouts that are not in the file or here: {', '.join(sorted(missing))}. They run only once a layout of that name exists."
        )
    if unknown:
        warnings.append(f"Entries use reports this installation does not have: {', '.join(sorted(unknown))}.")
    if off:
        warnings.append(f"Entries use reports of modules that are off in this project: {', '.join(sorted(off))}.")
    return warnings


def plan_import(
    db: Session, parsed: ReportFile, *, organization_id: uuid.UUID, project: Project | None, on_conflict: OnConflict,
) -> ImportPlan:
    """What importing `parsed` into the tier would do. Writes nothing.

    Args:
        db: Active session (read only).
        parsed: The checked file.
        organization_id: The target organisation.
        project: The target project, or `None` for the organisation.
        on_conflict: `rename` or `skip` for a name the tier already owns.

    Returns:
        The plan; an item's `action` says what happens to it.
    """
    organization = db.get(Organization, organization_id)
    plan = ImportPlan()
    inherited = (
        {s.layout.name.casefold() for s in report_layout_scope.resolve_project_layouts(db, project) if s.origin != "project"}
        if project is not None else set()
    )
    taken = _taken(db, ReportLayout, organization_id, project)
    file_layouts = {str(e.get("name", "")).strip().casefold() for e in parsed.layouts}
    wanted_pictures: set[str] = set()
    for entry in parsed.layouts:
        name = str(entry.get("name", "")).strip()
        versions = _layout_versions(entry)
        item = ImportItem("layout", name, name, "create", len(versions))
        if not name or entry.get("family") not in report_layouts.LAYOUT_FAMILIES or not versions:
            item.action, item.warnings = "left_out", ["It has no name, family or version this installation can read."]
        elif name.casefold() in taken:
            if on_conflict == "skip":
                item.action, item.warnings = "skip", ["A layout with this name already exists here."]
            else:
                item.action, item.new_name = "rename", free_name(name, taken)
        if item.action in ("create", "rename"):
            problems = _tree_problems(db, [v["tree"] for v in versions], organization)
            if len(problems) == len(versions):
                item.action, item.warnings = "left_out", [f"No version is valid here: {problems[-1]}"]
            else:
                taken.add(item.new_name.casefold())
                if problems:
                    item.warnings.append(f"{len(problems)} version(s) are not valid here and are left out: {problems[-1]}")
                latest = versions[-1]["tree"]
                if project is not None:
                    item.warnings += layout_warnings(db, latest, project, item.new_name.casefold() in inherited, pictures=False)
                for version in versions:
                    wanted_pictures |= {str(n.get("file")) for _, n in image_nodes(version["tree"])}
        plan.items.append(item)
    by_old_id = {str(i.get("id")): i for i in parsed.images}
    plan.pictures = sum(1 for old in wanted_pictures if old in by_old_id)
    if plan.pictures:
        where = "this project's" if project is not None else "the organisation's"
        plan.warnings.append(f"{plan.pictures} picture(s) will be added to {where} library.")
    gone = [str(i.get("filename", "")) for old, i in by_old_id.items() if old in wanted_pictures and i.get("file_ref") not in parsed.pictures]
    if gone:
        plan.warnings.append(f"{len(gone)} picture(s) have no file in the report file; layouts using them will be left out.")
    target_layouts = (
        {s.layout.name.casefold() for s in report_layout_scope.resolve_project_layouts(db, project) if not s.hidden}
        if project is not None else {n for n in _taken(db, ReportLayout, organization_id, None)}
    )
    pack_taken = _taken(db, ReportPack, organization_id, project)
    for entry in parsed.packs:
        name = str(entry.get("name", "")).strip()
        versions = _pack_versions(entry)
        item = ImportItem("pack", name, name, "create", len(versions))
        if not name or not versions:
            item.action, item.warnings = "left_out", ["It has no name or version this installation can read."]
        elif name.casefold() in pack_taken:
            if on_conflict == "skip":
                item.action, item.warnings = "skip", ["A pack with this name already exists here."]
            else:
                item.action, item.new_name = "rename", free_name(name, pack_taken)
        if item.action in ("create", "rename"):
            pack_taken.add(item.new_name.casefold())
            item.warnings += _pack_warnings(db, entry, project, file_layouts, target_layouts)
        plan.items.append(item)
    if len(plan.items) == 0:
        plan.warnings.append("The file holds no layouts or packs.")
    return plan


def _store_pictures(
    db: Session, parsed: ReportFile, wanted: set[str], *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    actor: User, warnings: BundleImportWarnings,
) -> dict[str, str]:
    """Stores the wanted pictures in the tier's library and returns `{old file id: new file id}`.

    Each is re-sniffed from its bytes (the declared type is ignored) and an SVG is re-sanitised. One that fails is reported
    and left unmapped. An organisation picture the importing organisation already has maps to itself. While file
    uploads are disabled, or the organisation's storage limit would be exceeded, a picture cannot be stored: it is
    reported in the preview and left unmapped, so the person sees the loss before applying.
    """
    mapping: dict[str, str] = {}
    for entry in parsed.images:
        old = str(entry.get("id", ""))
        if old not in wanted:
            continue
        try:
            existing = db.get(FileAsset, uuid.UUID(old))
        except ValueError:
            continue
        if entry.get("tier") == "organisation" and existing is not None and existing.organization_id == organization_id and existing.is_org_resource:
            mapping[old] = old
            continue
        filename = str(entry.get("filename", "image"))
        data = parsed.pictures.get(str(entry.get("file_ref", "")))
        if data is None:
            warnings.add(f'Picture "{filename}" has no file in the report file.')
            continue
        if not uploads_allowed(db, organization_id, len(data)):
            warnings.add(f'Picture "{filename}" was not imported because file uploads are disabled or the storage limit is reached.')
            continue
        try:
            content_type = sniff_image(data)
            if content_type == SVG_TYPE:
                data = sanitize_svg(data.decode("utf-8")).encode("utf-8")
        except (ImageRejectedError, UnicodeDecodeError, ValueError) as exc:
            warnings.add(f'Picture "{filename}" was not imported: {exc}')
            continue
        asset = upload_file(
            db, organization_id=organization_id, uploaded_by=actor.id, filename=filename[:255] or "image",
            content_type=content_type, data=data, is_org_resource=project_id is None, project_id=project_id,
        )
        db.flush()
        mapping[old] = str(asset.id)
    return mapping


def apply_import(
    db: Session, parsed: ReportFile, *, organization_id: uuid.UUID, project: Project | None, actor: User,
    on_conflict: OnConflict, folder: str | None = None,
) -> ImportPlan:
    """Plans, then performs the import in the caller's transaction (flushed, not committed), with one audit event.

    Args:
        db: Active session.
        parsed: The checked file.
        organization_id: The target organisation.
        project: The target project, or `None` for the organisation.
        actor: The importer; the author of everything created.
        on_conflict: As `plan_import`.
        folder: A folder (already tidied) to file every created report in; `None` keeps each report's own folder.

    Returns:
        The plan with `new_id` set for each created item; an item the importers refused is marked `left_out`.
    """
    plan = plan_import(db, parsed, organization_id=organization_id, project=project, on_conflict=on_conflict)
    notes = BundleImportWarnings()
    project_id = project.id if project is not None else None
    creating = [i for i in plan.items if i.kind == "layout" and i.action in ("create", "rename")]
    names = {i.name: i for i in creating}
    wanted: set[str] = set()
    for entry in parsed.layouts:
        if str(entry.get("name", "")).strip() in names:
            for version in _layout_versions(entry):
                wanted |= {str(n.get("file")) for _, n in image_nodes(version["tree"])}
    images = _store_pictures(
        db, parsed, wanted, organization_id=organization_id, project_id=project_id, actor=actor, warnings=notes,
    )
    plan.warnings += notes.messages
    notes.messages = []
    renamed: dict[str, str] = {}
    for entry in parsed.layouts:
        name = str(entry.get("name", "")).strip()
        item = names.get(name)
        if item is None or item.new_id is not None:
            continue
        stamped = {**entry, "name": item.new_name}
        if folder is not None:
            stamped["folder"] = folder
        new_id = report_layout_bundle.import_layout_entry(
            db, stamped, organization_id=organization_id, project_id=project_id, actor=actor, warnings=notes, images=images,
        )
        item.warnings += notes.messages
        notes.messages = []
        if new_id is None:
            item.action = "left_out"
            continue
        item.new_id = new_id
        renamed[name.casefold()] = item.new_name
    pack_items = {i.name: i for i in plan.items if i.kind == "pack" and i.action in ("create", "rename")}
    for entry in parsed.packs:
        item = pack_items.get(str(entry.get("name", "")).strip())
        if item is None or item.new_id is not None:
            continue
        stamped = {**entry, "name": item.new_name}
        if folder is not None:
            stamped["folder"] = folder
        for version in stamped.get("versions", []):
            if not isinstance(version, dict) or not isinstance(version.get("definition"), dict):
                continue
            for e in version["definition"].get("entries", []):
                if isinstance(e, dict) and e.get("kind") == "layout" and str(e.get("name", "")).casefold() in renamed:
                    e["name"] = renamed[str(e["name"]).casefold()]
        pack = report_pack_bundle.import_pack_entry(
            db, stamped, organization_id=organization_id, project_id=project_id, actor=actor, warnings=notes,
        )
        item.warnings += notes.messages
        notes.messages = []
        if pack is None:
            item.action = "left_out"
            continue
        item.new_id = pack.id
    log_event(
        db, entity_type="project" if project is not None else "organization", entity_id=project_id or organization_id,
        action="report_file_imported", actor_id=actor.id, organization_id=organization_id, project_id=project_id,
        detail={
            "layouts": plan.count("layout", "create", "rename"), "packs": plan.count("pack", "create", "rename"),
            "skipped": sum(1 for i in plan.items if i.action in ("skip", "left_out")), "pictures": len(images),
            "on_conflict": on_conflict,
        },
    )
    return plan


__all__ = [
    "FILE_KIND", "FORMAT_VERSION", "MAX_FILE_BYTES", "MAX_ITEMS", "ExportResult", "ImportItem", "ImportPlan", "OnConflict",
    "ReportFile", "ReportFileError", "apply_import", "build_export", "pack_layout_names", "plan_import", "read_file_bytes",
]
