"""
Module: services.branding

Platform-wide UI branding defaults (accent colour, logo, header title) and
the small colour-math helper used to keep an admin-picked accent colour
from producing unreadable button/badge text.

`ServerSettings` is a lazily-created singleton row — `get_server_settings()`
is the only way anything in this app should read or create it, so "there
might be zero rows" only ever needs handling here. True singleton-ness is
now enforced at the DB level (`ServerSettings.singleton_guard`, migration
0020, 2026-08-31) after live evidence showed the earlier
purely-application-level "read then insert if absent" check really did let
two concurrent requests both create a row in practice — see that migration
and the model's own docstring for the full incident.
"""

from __future__ import annotations

import colorsys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.organization import ServerSettings

DEFAULT_ACCENT_COLOR_HEX = "#475569"


def get_server_settings(db: Session) -> ServerSettings:
    """Returns the single `ServerSettings` row, creating it with built-in
    defaults on first access.

    Two concurrent callers can both observe `settings is None` below before
    either commits — the `singleton_guard` UNIQUE constraint (migration
    0020) makes the second `INSERT` fail with an `IntegrityError` rather
    than silently succeeding as a duplicate row; that loser rolls back and
    re-reads, picking up the winner's row instead.
    """
    settings = db.scalar(select(ServerSettings))
    if settings is None:
        settings = ServerSettings(accent_color_hex=DEFAULT_ACCENT_COLOR_HEX)
        db.add(settings)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            settings = db.scalar(select(ServerSettings))
            if settings is None:
                # The row that made us lose the race should be visible to
                # a fresh read immediately after the other transaction
                # committed — a still-missing row here means something
                # other than the expected singleton race, so surface it
                # rather than looping/guessing.
                raise
        else:
            db.refresh(settings)
    return settings


def _luminance(hex_value: str) -> float:
    """WCAG relative luminance of `#RRGGBB` (or `RRGGBB`), 0 (black) to 1 (white)."""
    value = hex_value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two colours, 1 (identical) to 21 (black on white)."""
    lighter, darker = sorted((_luminance(hex_a), _luminance(hex_b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_text_hex(background_hex: str) -> str:
    """Picks black or white text, whichever gives better contrast against
    `background_hex` (per the WCAG relative-luminance formula), so an admin
    picking one accent colour never has to also pick a matching text colour
    or risk an unreadable combination."""
    # Contrast against white (luminance 1.0) vs. black (luminance 0.0).
    contrast_with_white = (1.0 + 0.05) / (_luminance(background_hex) + 0.05)
    contrast_with_black = (_luminance(background_hex) + 0.05) / (0.0 + 0.05)
    return "#ffffff" if contrast_with_white >= contrast_with_black else "#000000"


def readable_on_white(colour_hex: str, min_ratio: float = 4.5) -> str:
    """The accent colour as text on a white page: itself when it already contrasts enough, otherwise darkened
    (same hue and saturation, lightness lowered in steps), mirroring the frontend's `ensureContrast`, so a light
    brand colour does not make a faint title on paper.

    Args:
        colour_hex: The colour, `#RRGGBB` or `RRGGBB`.
        min_ratio: Least WCAG contrast against white (4.5 is AA for normal text).

    Returns:
        `#RRGGBB`, lower case.
    """
    value = colour_hex.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    for _ in range(34):  # 0.03 steps cover the whole lightness range
        candidate = "#" + "".join(f"{round(c * 255):02x}" for c in colorsys.hls_to_rgb(h, lightness, s))
        if contrast_ratio(candidate, "#ffffff") >= min_ratio:
            return candidate
        lightness = max(0.0, lightness - 0.03)
    return "#000000"
