"""
Module: services.branding

Platform-wide UI branding defaults (accent colour, logo, header title) and
the small colour-math helper used to keep an admin-picked accent colour
from producing unreadable button/badge text.

`ServerSettings` is a lazily-created singleton row — `get_server_settings()`
is the only way anything in this app should read or create it, so "there
might be zero rows" only ever needs handling here. True singleton-ness is
now enforced at the DB level (`ServerSettings.singleton_guard`, migration
0020, follow-up UX batch Phase D) after live evidence showed the earlier
purely-application-level "read then insert if absent" check really did let
two concurrent requests both create a row in practice — see that migration
and the model's own docstring for the full incident.
"""

from __future__ import annotations

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


def contrast_text_hex(background_hex: str) -> str:
    """Picks black or white text, whichever gives better contrast against
    `background_hex` (per the WCAG relative-luminance formula), so an admin
    picking one accent colour never has to also pick a matching text colour
    or risk an unreadable combination."""
    hex_value = background_hex.lstrip("#")
    r, g, b = (int(hex_value[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
    # Contrast against white (luminance 1.0) vs. black (luminance 0.0).
    contrast_with_white = (1.0 + 0.05) / (luminance + 0.05)
    contrast_with_black = (luminance + 0.05) / (0.0 + 0.05)
    return "#ffffff" if contrast_with_white >= contrast_with_black else "#000000"
