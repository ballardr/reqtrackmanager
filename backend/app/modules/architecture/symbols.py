"""
Module: modules.architecture.symbols

What a symbol is made of and who may read it: the built-in drawings, the checks an uploaded file passes, the safe SVG
a stored symbol yields, and which symbols a viewer may read.

Responsibilities:
- `BUILTIN_SVG`: the built-in set, drawn here (no file, no licence question), keyed as `service.DEFAULT_SYMBOLS`.
- `prepare_symbol_upload`: turn an upload into the sanitised SVG that is stored.
- `symbol_svg`: the sanitised SVG of any symbol row, for the endpoint that serves it and the renderers.
- `visible_symbol_ids`: the symbols among some ids a viewer may read.

Design decisions:
- **One importer.** An upload goes through the report-image machinery (`services.report_images.prepare_upload` for an
  EPS or PDF when the converter is configured, `sniff_image`, `services.report_svg.sanitize_svg`), so a script, an
  external reference, an entity or an oversized file is refused in one place. Only a vector drawing is accepted (a
  raster image does not scale on a diagram), and the stored copy is the sanitised one, never the upload. The sanitiser
  runs again whenever a symbol is read, as each renderer's does.
- **A smaller size limit than a report picture.** A symbol is an icon drawn at a few dozen pixels; `MAX_SYMBOL_BYTES`
  keeps a diagram of many symbols light and a megabyte photograph-in-an-SVG out.
- **Built-ins are code.** They are rows with a key and no file, so they cost no storage, cannot be altered through
  the library and travel in a bundle by key.
- **Reading follows the record that uses a symbol.** An organisation symbol is readable by the organisation's
  members. A project's symbol is readable by whoever can open that project, from that project or an inheriting
  child, and by anyone who can read an element (or the type of an element) drawn with it, so an element shared from
  another project still shows its symbol. A symbol that none of these reaches is indistinguishable from a missing one.

Dependencies: `service` (the library and the module's keys), `visibility`, and core services (`report_images`,
`report_svg`, `files`, `link_nesting`, `project_hierarchy`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.modules.architecture.models import ArchitectureElement, ArchitectureElementType, ArchitectureSymbol
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.modules.registry import is_module_enabled_for_project
from app.services import report_images
from app.services.files import read_file
from app.services.link_nesting import can_open_project
from app.services.project_hierarchy import get_project_chain_ids
from app.services.report_raster import ImageRejectedError
from app.services.report_svg import UnsafeSvgError, sanitize_svg

#: Largest symbol file accepted, in bytes (after an EPS or PDF is converted).
MAX_SYMBOL_BYTES = 512 * 1024

#: The longest a symbol name may be (the column is 100 characters).
MAX_NAME = 100

_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round">'
)

#: Each built-in drawing, by key, on a 64 x 64 grid in the current text colour so a diagram's theme colours it.
BUILTIN_SVG: dict[str, str] = {
    "device": (
        f'{_OPEN}<rect x="12" y="6" width="40" height="52" rx="5"/><path d="M24 16h16"/><circle cx="32" cy="48" r="3"/></svg>'
    ),
    "server": (
        f'{_OPEN}<rect x="8" y="8" width="48" height="14" rx="2"/><rect x="8" y="25" width="48" height="14" rx="2"/>'
        '<rect x="8" y="42" width="48" height="14" rx="2"/><path d="M16 15h.01M16 32h.01M16 49h.01"/></svg>'
    ),
    "database": (
        f'{_OPEN}<ellipse cx="32" cy="14" rx="20" ry="8"/><path d="M12 14v36a20 8 0 0 0 40 0V14"/>'
        '<path d="M12 32a20 8 0 0 0 40 0"/></svg>'
    ),
    "queue": (
        f'{_OPEN}<rect x="5" y="22" width="14" height="20" rx="2"/><rect x="25" y="22" width="14" height="20" rx="2"/>'
        '<rect x="45" y="22" width="14" height="20" rx="2"/><path d="M19 32h6M39 32h6"/></svg>'
    ),
    "firewall": (
        f'{_OPEN}<rect x="8" y="12" width="48" height="40" rx="2"/><path d="M8 25h48M8 38h48M32 12v13M20 25v13M44 25v13M32 38v14"/></svg>'
    ),
    "cloud": f'{_OPEN}<path d="M18 46a12 12 0 0 1-1-24 16 16 0 0 1 31 3 11 11 0 0 1 0 21z"/></svg>',
    "sensor": (
        f'{_OPEN}<circle cx="32" cy="32" r="5"/><path d="M22 22a14 14 0 0 0 0 20M42 22a14 14 0 0 1 0 20'
        'M15 15a24 24 0 0 0 0 34M49 15a24 24 0 0 1 0 34"/></svg>'
    ),
    "board": (
        f'{_OPEN}<rect x="8" y="12" width="48" height="40" rx="3"/><rect x="24" y="24" width="16" height="16"/>'
        '<path d="M28 24v-8M36 24v-8M28 40v8M36 40v8M24 28h-8M24 36h-8M40 28h8M40 36h8"/></svg>'
    ),
    "connector": (
        f'{_OPEN}<path d="M22 8v14M42 8v14"/><path d="M16 22h32v10a16 16 0 0 1-32 0z"/><path d="M32 48v10"/></svg>'
    ),
    "user": f'{_OPEN}<circle cx="32" cy="20" r="10"/><path d="M12 56a20 18 0 0 1 40 0z"/></svg>',
}

_EXTENSIONS = re.compile(r"(\.(svg|eps|pdf))+$", re.IGNORECASE)


def default_name(filename: str) -> str:
    """A symbol name from an uploaded file name: the name without its extension(s), at most `MAX_NAME` characters
    (`"server.eps.svg"` gives `"server"`), or `"Symbol"` for a name with nothing left."""
    stem = _EXTENSIONS.sub("", filename.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    return (stem or "Symbol")[:MAX_NAME]


def clean_symbol_svg(data: bytes) -> bytes:
    """The sanitised SVG bytes for the bytes of a symbol file (an upload, or one embedded in a bundle).

    Raises:
        ImageRejectedError: Empty, larger than `MAX_SYMBOL_BYTES`, not an SVG, or unsafe.
    """
    if len(data) > MAX_SYMBOL_BYTES:
        raise ImageRejectedError(f"The symbol is too large (limit {MAX_SYMBOL_BYTES // 1024} KB).")
    if report_images.sniff_image(data) != report_images.SVG_TYPE:
        raise ImageRejectedError("A symbol must be an SVG drawing (an EPS or PDF is converted when the converter is available).")
    try:
        return sanitize_svg(data.decode("utf-8")).encode("utf-8")
    except (UnicodeDecodeError, UnsafeSvgError) as exc:
        raise ImageRejectedError("The SVG is not safe to use.") from exc


def prepare_symbol_upload(filename: str, data: bytes, uploaded_by: uuid.UUID | None = None) -> tuple[str, bytes]:
    """The file name and sanitised SVG bytes to store for an upload.

    Converts an EPS or PDF first when the converter is configured, so call it off the event loop
    (`run_in_threadpool`).

    Args:
        filename: The uploaded name (a converted file keeps it, with `.svg` appended).
        data: The uploaded bytes.
        uploaded_by: The uploader, for the conversion rate limit.

    Returns:
        `(filename, sanitised SVG bytes)`.

    Raises:
        ImageRejectedError: As `clean_symbol_svg`, or too many conversions started by this person.
    """
    filename, data = report_images.prepare_upload(filename, data, uploaded_by)
    return filename or "symbol.svg", clean_symbol_svg(data)


def symbol_svg(db: Session, symbol: ArchitectureSymbol) -> str:
    """The sanitised SVG markup of a symbol: the built-in drawing, or the stored file read back and sanitised again.

    Raises:
        LookupError: The stored file is missing or no longer a safe SVG.
    """
    if symbol.builtin_key is not None:
        drawing = BUILTIN_SVG.get(symbol.builtin_key)
        if drawing is None:
            raise LookupError("This built-in symbol has no drawing.")
        return drawing
    asset = db.get(FileAsset, symbol.file_asset_id) if symbol.file_asset_id else None
    if asset is None:
        raise LookupError("The symbol's file is missing.")
    try:
        return sanitize_svg(read_file(asset).decode("utf-8"))
    except (UnicodeDecodeError, UnsafeSvgError, OSError) as exc:
        raise LookupError("The symbol's file cannot be read.") from exc


def visible_symbol_ids(db: Session, viewer: Viewer, symbol_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The ids among `symbol_ids` the viewer may read; an unknown id, or one that is hidden, is absent.

    An organisation symbol is readable by anyone in its organisation. A project symbol is readable from the project that
    owns it or from a project that inherits its library, by a person who can open the owning project, and by whoever can
    read an element drawn with it (directly or through its type).
    """
    wanted = set(symbol_ids)
    if not wanted:
        return set()
    rows = db.execute(
        select(ArchitectureSymbol.id, ArchitectureSymbol.project_id, ArchitectureSymbol.organization_id, Project.organization_id)
        .outerjoin(Project, Project.id == ArchitectureSymbol.project_id).where(ArchitectureSymbol.id.in_(wanted))
    ).all()
    found: set[uuid.UUID] = set()
    project_symbols: dict[uuid.UUID, uuid.UUID] = {}
    for symbol_id, project_id, symbol_org, project_org in rows:
        if (symbol_org or project_org) != viewer.organization_id:
            continue
        if project_id is None:
            found.add(symbol_id)
        else:
            project_symbols[symbol_id] = project_id
    if not project_symbols:
        return found

    chain = set(get_project_chain_ids(db, viewer.project_id)) if viewer.project_id is not None else set()
    open_projects: dict[uuid.UUID, bool] = {}
    for symbol_id, project_id in project_symbols.items():
        if project_id in chain:
            found.add(symbol_id)
        elif viewer.user is not None:
            if project_id not in open_projects:
                open_projects[project_id] = can_open_project(db, viewer.user.id, project_id) and (
                    is_module_enabled_for_project(db, project_id, ARCHITECTURE_MODULE_KEY)
                )
            if open_projects[project_id]:
                found.add(symbol_id)

    pending = set(project_symbols) - found
    if pending:
        typed = select(ArchitectureElementType.id).where(ArchitectureElementType.symbol_id.in_(pending))
        users = db.execute(
            select(ArchitectureElement.id, ArchitectureElement.symbol_id, ArchitectureElementType.symbol_id)
            .join(ArchitectureElementType, ArchitectureElementType.id == ArchitectureElement.element_type_id)
            .where(or_(ArchitectureElement.symbol_id.in_(pending), ArchitectureElement.element_type_id.in_(typed)))
        ).all()
        readable = visible_element_ids(db, viewer, [element_id for element_id, _own, _typed in users])
        for element_id, own, from_type in users:
            drawn = own or from_type
            if element_id in readable and drawn in pending:
                found.add(drawn)
    return found
