"""
Module: services.image_details

What a picture file says about itself, for a person choosing or inspecting it: its size and the EXIF a photograph is
recognised by.

Responsibilities:
- Read a raster picture's size (orientation applied) and, from its EXIF, when it was taken, the camera, the description
  and the recorded position, and an SVG's declared size (`image_details`).

Design decisions:
- The header is read and the picture is never decoded, so a large file costs little.
- **EXIF is untrusted text.** Strings lose control characters and are cut to 200 characters; coordinates are range-checked;
  an unreadable or absent EXIF gives an empty record, never an error.
- **"Taken" is not a point in time.** EXIF carries no time zone, so it is the camera's own wall clock as written and is
  never converted or compared.
- Reading is not publishing: the caller (`routers.files`) applies the file's own read access, and nothing read here is
  logged or audited.

Dependencies: Pillow.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image as PilImage
from svglib.svglib import svg2rlg

from app.services.report_svg import sanitize_svg

#: Raster formats read (Pillow format names).
_FORMATS = ["PNG", "JPEG", "GIF", "WEBP"]


@dataclass(frozen=True)
class ImageDetails:
    """What a photograph says about itself, for a person choosing it in the library (read-only, never printed).

    Attributes:
        width_px / height_px: The pixel size as displayed (the EXIF orientation applied); `None` for an SVG.
        taken: When it was taken as the camera recorded it, `YYYY-MM-DD HH:MM:SS` on the camera's own clock. EXIF holds
            no time zone, so this is shown as written, never converted.
        camera: Make and model.
        description: The EXIF image description, if the photographer or the camera wrote one.
        latitude / longitude: Where it was taken, in decimal degrees, when the file records a position.
    """

    width_px: int | None = None
    height_px: int | None = None
    taken: str | None = None
    camera: str | None = None
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825
_MAX_DETAIL_CHARS = 200


def _exif_text(value: Any) -> str | None:
    """EXIF text made safe to show: a string, control characters removed, cut to a sensible length."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    if not isinstance(value, str):
        return None
    cleaned = "".join(c for c in value if c.isprintable()).strip()
    return cleaned[:_MAX_DETAIL_CHARS] or None


def _degrees(parts: Any, reference: Any) -> float | None:
    """A GPS coordinate (degrees, minutes, seconds and an N/S/E/W reference) as signed decimal degrees."""
    try:
        degrees, minutes, seconds = (float(p) for p in parts)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    value = degrees + minutes / 60 + seconds / 3600
    if isinstance(reference, bytes):
        reference = reference.decode("ascii", "ignore")
    return round(-value if reference in ("S", "W") else value, 6)


def image_details(data: bytes) -> ImageDetails:
    """Reads a picture's size and the EXIF a person recognises a photograph by.

    Args:
        data: The stored file (any library picture).

    Returns:
        The details found; a picture with none, an SVG or an unreadable file gives an empty record. The header is read,
        the picture is never decoded.
    """
    try:
        with PilImage.open(io.BytesIO(data), formats=_FORMATS) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(0x0112)
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            make, model = _exif_text(exif.get(0x010F)), _exif_text(exif.get(0x0110))
            camera = model if model and (not make or model.lower().startswith(make.lower())) else " ".join(p for p in (make, model) if p) or None
            taken_raw = _exif_text(exif.get_ifd(_EXIF_IFD).get(0x9003) or exif.get(0x0132))
            taken = None
            if taken_raw and len(taken_raw) >= 19 and taken_raw[4] == ":" and taken_raw[7] == ":":
                taken = f"{taken_raw[:4]}-{taken_raw[5:7]}-{taken_raw[8:10]} {taken_raw[11:19]}"
            gps = exif.get_ifd(_GPS_IFD)
            latitude = _degrees(gps.get(2), gps.get(1)) if gps.get(2) else None
            longitude = _degrees(gps.get(4), gps.get(3)) if gps.get(4) else None
            if latitude is None or longitude is None or abs(latitude) > 90 or abs(longitude) > 180:
                latitude = longitude = None
            return ImageDetails(width, height, taken, camera, _exif_text(exif.get(0x010E)), latitude, longitude)
    except Exception:  # noqa: BLE001 - a picture with unreadable metadata simply has no details
        return _svg_details(data)


def _svg_details(data: bytes) -> ImageDetails:
    """An SVG's size in CSS pixels as it declares it (`width` and `height`, or its `viewBox`); empty for anything else."""
    try:
        source = data.decode("utf-8")
        if "<svg" not in source[:2000]:
            return ImageDetails()
        drawing = svg2rlg(io.StringIO(sanitize_svg(source)))
    except Exception:  # noqa: BLE001 - not an SVG, or one that cannot be read: no details
        return ImageDetails()
    if drawing is None or drawing.width <= 0 or drawing.height <= 0:
        return ImageDetails()
    return ImageDetails(round(drawing.width * 96 / 72), round(drawing.height * 96 / 72))


__all__ = ["ImageDetails", "image_details"]
