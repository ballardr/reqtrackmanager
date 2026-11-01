"""
Module: services.report_raster

Re-encodes a raster picture (PNG, JPEG, GIF, WebP) without its metadata.

Responsibilities:
- `normalise_raster`: decode within the pixel limit, apply the EXIF orientation, drop every metadata chunk (EXIF,
  GPS, comments) by encoding afresh, and return PNG (JPEG stays JPEG).
- The shared raster vocabulary: `RASTER_TYPES`, `ImageRejectedError`, `NormalisedImage`, `max_image_pixels`.

Design decisions:
- Used for an uploaded library picture, a record attachment and a bitmap embedded inside an SVG, so all three get the
  same limits and the same metadata removal. It has no dependency on the SVG sanitiser (which uses it), so the two do
  not import each other.

Dependencies: Pillow, `app.config` (`report_image_max_pixels`).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image as PilImage
from PIL import ImageOps

from app.config import get_settings

RASTER_TYPES: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
#: JPEG quality of a re-encoded photograph.
JPEG_QUALITY = 90


def max_image_pixels() -> int:
    """The most pixels one raster picture may have (`REPORT_IMAGE_MAX_PIXELS`)."""
    return get_settings().report_image_max_pixels


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


__all__ = ["JPEG_QUALITY", "RASTER_TYPES", "ImageRejectedError", "NormalisedImage", "max_image_pixels", "normalise_raster"]
