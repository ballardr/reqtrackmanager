"""
Module: services.report_images

The pictures a report layout may embed: the library at each tier, the visibility rule, and the safe way to turn a
stored file into the bytes a renderer draws.

Responsibilities:
- Accept an upload only when its *content* is a raster image (PNG, JPEG, GIF, WebP) or a sanitisable SVG, never its
  declared type or file name.
- List the library a layout may use, upload to it and delete from it, naming the layouts that use an image.
- Decide whether a layout may use a file (`usable_by_layout`) and report the layouts that break that rule at save
  (`image_problems`), so the check is made again at run time by `load_image` and a hand-typed id cannot cross it.
- Turn a stored raster into drawable bytes with the metadata removed (`normalise_raster`), within byte and pixel caps.

Design decisions:
- **Visibility.** An organisation layout may use organisation images only (it runs for, and is inherited by, every
  project, so a project's picture in it would reach members who cannot open that project). A project layout may use
  its own project's images and any organisation image. A project's library is `FileAsset.project_id`; the
  organisation's is the shared resources (`is_org_resource`), so one library serves attachments in Markdown and
  the Image block. There is no ancestor fallback: a child reaches the organisation library for anything shared.
- **A layout stores a file id, never bytes** (tree size, version diffs, bundles); a deleted image is skipped with a
  run warning.
- **Metadata is stripped on every embed.** A photograph's GPS position and camera owner are personal data a report
  must not pass on, so a raster is re-encoded (after applying its EXIF orientation); an animated GIF keeps its first
  frame. The pixel count is read from the header before the image is decoded (decompression bombs).
- **No remote URLs, ever.** Only files in the store are read.

Dependencies: Pillow, `services.files`, `services.report_svg`, `services.report_layout_tree` (the tree vocabulary).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from PIL import Image as PilImage
from PIL import ImageOps
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.file import FileAsset
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.services.files import delete_file, read_file, upload_file
from app.services.report_layout_tree import TreeError
from app.services.report_svg import UnsafeSvgError, sanitize_svg

#: Raster formats embedded, by Pillow format name, and the content type each is stored and drawn as.
RASTER_TYPES: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
SVG_TYPE = "image/svg+xml"
#: Most pictures one report run embeds (times the background multiplier). The size limits are deployment settings
#: (`Settings.report_image_max_bytes`, `report_image_max_pixels`, `report_image_max_total_bytes`).
MAX_REPORT_IMAGES = 200
#: JPEG quality of a re-encoded photograph.
JPEG_QUALITY = 90


def max_image_bytes() -> int:
    """The largest picture the library accepts: the report-image setting, never above the general upload limit."""
    settings = get_settings()
    return min(settings.report_image_max_bytes, settings.max_upload_bytes)


def max_image_pixels() -> int:
    """The most pixels one raster picture may have (`REPORT_IMAGE_MAX_PIXELS`)."""
    return get_settings().report_image_max_pixels


def max_total_image_bytes() -> int:
    """The most bytes of pictures one report run may embed, before the background multiplier."""
    return get_settings().report_image_max_total_bytes


def _megabytes(value: int) -> str:
    return f"{value / (1024 * 1024):g} MB"


class ImageRejectedError(ValueError):
    """The bytes are not an image this library accepts (the message is shown to the author)."""


@dataclass(frozen=True)
class NormalisedImage:
    """A raster ready to draw: re-encoded without metadata.

    Attributes:
        data: PNG or JPEG bytes.
        content_type: `image/png` or `image/jpeg`.
        width_px / height_px: The pixel size after the EXIF orientation was applied.
    """

    data: bytes
    content_type: str
    width_px: int
    height_px: int


@dataclass(frozen=True)
class ResolvedImage:
    """What a run draws for one library image: raster bytes (`data`), or sanitised SVG markup (`svg`)."""

    data: bytes = b""
    svg: str | None = None
    width_px: int = 0
    height_px: int = 0

    @property
    def size(self) -> int:
        """Bytes this image adds to the report."""
        return len(self.data) + len(self.svg or "")


@dataclass(frozen=True)
class LibraryImage:
    """One picture in a library as the designer lists it.

    Attributes:
        asset: The stored file.
        tier: `organisation` or `project`.
        used_by: Names of the layouts whose current version embeds it.
    """

    asset: FileAsset
    tier: str
    used_by: list[str]


def sniff_image(data: bytes) -> str:
    """The content type of `data`, decided from its bytes, or an error naming what is wrong.

    Args:
        data: The uploaded bytes.

    Returns:
        One of `RASTER_TYPES`' values, or `image/svg+xml`.

    Raises:
        ImageRejectedError: Empty, too large, not a PNG, JPEG, GIF, WebP or SVG, or a raster with too many pixels.
    """
    if not data:
        raise ImageRejectedError("The file is empty.")
    if len(data) > max_image_bytes():
        raise ImageRejectedError(f"The image is too large (limit {_megabytes(max_image_bytes())}).")
    try:
        with PilImage.open(io.BytesIO(data), formats=list(RASTER_TYPES)) as img:
            width, height = img.size
            if width * height > max_image_pixels():
                raise ImageRejectedError(f"The image has too many pixels (limit {max_image_pixels() / 1_000_000:g} million).")
            return RASTER_TYPES[img.format or ""]
    except ImageRejectedError:
        raise
    except Exception:  # noqa: BLE001 - Pillow raises several types for a file that is not an image
        pass
    try:
        sanitize_svg(data.decode("utf-8"))
    except (UnicodeDecodeError, UnsafeSvgError):
        raise ImageRejectedError("Only PNG, JPEG, GIF, WebP and plain SVG images can be used in a report.") from None
    return SVG_TYPE


def normalise_raster(data: bytes) -> NormalisedImage:
    """Re-encodes a raster without its metadata (EXIF, GPS, comments), applying its orientation first.

    Args:
        data: A PNG, JPEG, GIF or WebP file.

    Returns:
        PNG bytes (JPEG bytes for a JPEG source).

    Raises:
        ImageRejectedError: Not a decodable image, or more pixels than `max_image_pixels()`.
    """
    try:
        with PilImage.open(io.BytesIO(data), formats=list(RASTER_TYPES)) as img:
            if img.size[0] * img.size[1] > max_image_pixels():
                raise ImageRejectedError("The image has too many pixels.")
            source_format = img.format
            img.load()
            oriented = ImageOps.exif_transpose(img)
            out = io.BytesIO()
            if source_format == "JPEG":
                oriented.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
                content_type = "image/jpeg"
            else:
                has_alpha = oriented.mode in ("RGBA", "LA", "P") or "transparency" in oriented.info
                oriented.convert("RGBA" if has_alpha else "RGB").save(out, "PNG", optimize=True)
                content_type = "image/png"
            return NormalisedImage(out.getvalue(), content_type, oriented.size[0], oriented.size[1])
    except ImageRejectedError:
        raise
    except Exception as exc:  # noqa: BLE001 - a corrupt or unsupported file is a rejected image, never a crash
        raise ImageRejectedError("The image could not be read.") from exc


def usable_by_layout(asset: FileAsset | None, organization_id: uuid.UUID, layout_project_id: uuid.UUID | None) -> bool:
    """Whether a layout owned by `layout_project_id` (`None`: the organisation) may embed `asset`.

    Args:
        asset: The file, or `None`.
        organization_id: The layout's organisation.
        layout_project_id: The layout's own project, or `None` for an organisation layout.

    Returns:
        True for an image in the organisation's library, or in the layout's own project's library.
    """
    if asset is None or asset.organization_id != organization_id:
        return False
    if asset.content_type != SVG_TYPE and asset.content_type not in RASTER_TYPES.values():
        return False
    if asset.is_org_resource:
        return True
    return layout_project_id is not None and asset.project_id == layout_project_id


def load_image(
    db: Session, organization_id: uuid.UUID, layout_project_id: uuid.UUID | None, file_id: uuid.UUID,
) -> tuple[ResolvedImage | None, str]:
    """Reads a library image for a run, after the visibility rule.

    Args:
        db: Active session (read only).
        organization_id: The layout's organisation.
        layout_project_id: The layout's own project, or `None` for an organisation layout.
        file_id: The image's file id.

    Returns:
        `(image, "")`, or `(None, reason)` with a short reason for the run's warning. Never raises for a bad image.
    """
    asset = db.get(FileAsset, file_id)
    if asset is None:
        return None, "was not found (it may have been deleted)"
    if not usable_by_layout(asset, organization_id, layout_project_id):
        return None, "is not in a library this layout may use"
    try:
        raw = read_file(asset)
    except Exception:  # noqa: BLE001 - a missing object in storage must not fail the report
        return None, "could not be read"
    if asset.content_type == SVG_TYPE:
        try:
            return ResolvedImage(svg=sanitize_svg(raw.decode("utf-8"))), ""
        except (UnicodeDecodeError, UnsafeSvgError):
            return None, "is not a safe SVG"
    try:
        normal = normalise_raster(raw)
    except ImageRejectedError as exc:
        return None, f"could not be used ({str(exc).rstrip('.').lower()})"
    return ResolvedImage(normal.data, None, normal.width_px, normal.height_px), ""


# --- the library ---------------------------------------------------------------------------------------


def _is_image(asset: FileAsset) -> bool:
    return asset.content_type == SVG_TYPE or asset.content_type in RASTER_TYPES.values()


def upload_library_image(
    db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID | None, uploaded_by: uuid.UUID, filename: str,
    data: bytes,
) -> FileAsset:
    """Adds an image to the organisation's library (`project_id` None) or a project's.

    Args:
        db: Active session (the file row is added, not committed).
        organization_id: The owning organisation.
        project_id: The project whose library receives it, or `None` for the organisation's.
        uploaded_by: The uploader.
        filename: Shown in the library.
        data: The file bytes; their content decides the type.

    Returns:
        The stored file.

    Raises:
        ImageRejectedError: Not an acceptable image.
        HTTPException: 413 from the upload cap (`services.files.upload_file`).
    """
    content_type = sniff_image(data)
    return upload_file(
        db, organization_id=organization_id, uploaded_by=uploaded_by, filename=filename or "image", content_type=content_type,
        data=data, is_org_resource=project_id is None, project_id=project_id,
    )


def list_library(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list[LibraryImage]:
    """The images a layout at this tier may use: the organisation's, and for a project its own too.

    Args:
        db: Active session (read only).
        organization_id: The organisation.
        project_id: The project, or `None` for the organisation's own layouts.

    Returns:
        Images newest first, each with the layouts that use it.
    """
    condition = (
        FileAsset.is_org_resource.is_(True) if project_id is None
        else or_(FileAsset.is_org_resource.is_(True), FileAsset.project_id == project_id)
    )
    assets = [
        a for a in db.scalars(
            select(FileAsset).where(FileAsset.organization_id == organization_id, condition).order_by(FileAsset.created_at.desc())
        ) if _is_image(a)
    ]
    users = used_by(db, organization_id, [a.id for a in assets])
    return [LibraryImage(a, "organisation" if a.is_org_resource else "project", users.get(a.id, [])) for a in assets]


def used_by(db: Session, organization_id: uuid.UUID, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """The names of the layouts whose current version embeds each file (a text search of the stored tree)."""
    if not file_ids:
        return {}
    rows = db.execute(
        select(ReportLayout.name, cast(ReportLayoutVersion.tree, Text))
        .join(ReportLayoutVersion, (ReportLayoutVersion.layout_id == ReportLayout.id)
              & (ReportLayoutVersion.version == ReportLayout.current_version))
        .where(ReportLayout.organization_id == organization_id)
    ).all()
    found: dict[uuid.UUID, list[str]] = {}
    for name, tree_text in rows:
        for file_id in file_ids:
            if str(file_id) in tree_text:
                found.setdefault(file_id, []).append(name)
    return found


def delete_library_image(db: Session, asset: FileAsset) -> None:
    """Deletes an image's bytes and row; layouts that used it skip it with a warning from then on."""
    delete_file(db, asset)


def library_asset(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, file_id: uuid.UUID,
) -> FileAsset | None:
    """An image that is in this tier's *own* library (what a manager may delete), or `None`.

    A project's manager reaches its own project's images and never the organisation's; an organisation's
    manager reaches the organisation's.
    """
    asset = db.get(FileAsset, file_id)
    if asset is None or asset.organization_id != organization_id or not _is_image(asset):
        return None
    if project_id is None:
        return asset if asset.is_org_resource else None
    return asset if asset.project_id == project_id and not asset.is_org_resource else None


# --- the save-time check ----------------------------------------------------------------------------------


def image_nodes(tree: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every `image` block of a tree with its path (`nodes[0].children[1]`)."""

    def walk(nodes: Any, path: str) -> Iterator[tuple[str, dict[str, Any]]]:
        if not isinstance(nodes, list):
            return
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            here = f"{path}[{i}]"
            if node.get("type") == "image":
                yield here, node
            for key in ("children", "else_children"):
                yield from walk(node.get(key), f"{here}.{key}")

    yield from walk(tree.get("nodes"), "nodes")


def image_problems(
    db: Session, organization_id: uuid.UUID, layout_project_id: uuid.UUID | None, tree: dict[str, Any],
) -> list[TreeError]:
    """Problems with the images a tree names that only the database can see.

    Args:
        db: Active session (read only).
        organization_id: The layout's organisation.
        layout_project_id: The layout's own project, or `None` for an organisation layout.
        tree: A structurally valid tree.

    Returns:
        One error per image block whose file is not in a library the layout may use, naming the file.
    """
    problems: list[TreeError] = []
    for path, node in image_nodes(tree):
        raw = node.get("file")
        try:
            file_id = uuid.UUID(raw) if isinstance(raw, str) else None
        except ValueError:
            file_id = None
        if file_id is None:
            continue  # the structural validator reports a malformed id
        asset = db.get(FileAsset, file_id)
        if asset is None:
            problems.append(TreeError(f"{path}.file", "This image no longer exists in the library. Pick another."))
        elif not usable_by_layout(asset, organization_id, layout_project_id):
            where = "the organisation's library" if layout_project_id is None else "this project's or the organisation's library"
            problems.append(TreeError(
                f"{path}.file",
                f'"{asset.filename}" is not in {where}. An organisation layout can only use organisation images.',
            ))
    return problems


__all__ = [
    "JPEG_QUALITY", "MAX_REPORT_IMAGES", "max_image_bytes", "max_image_pixels", "max_total_image_bytes",
    "RASTER_TYPES", "SVG_TYPE", "ImageRejectedError", "LibraryImage", "NormalisedImage", "ResolvedImage",
    "delete_library_image", "image_nodes", "image_problems", "library_asset", "list_library", "load_image",
    "normalise_raster", "sniff_image", "upload_library_image", "usable_by_layout", "used_by",
]
