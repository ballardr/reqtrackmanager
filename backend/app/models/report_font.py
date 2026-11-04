"""
Module: models.report_font

The server administrator's settings for the extra report fonts found in the mounted font directory.

Responsibilities:
- `ServerReportFont`: how one extra font family is named to Word, OpenDocument and HTML, its generic fallback, and
  whether authors are offered it.

Design decisions:
- Explicit-override-only, like `ServerModuleDefault`: a family found in the directory with no row is offered with the
  defaults (its own name, `sans-serif`, enabled). The font files are not in the database; a row can outlive its files
  (the family then shows as missing to administrators and layouts using it fall back to the generic family).
- The key is the stable `x-<slug>` of the family's name, so a bundle moved between servers keeps its meaning.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ServerReportFont(UUIDPKMixin, TimestampMixin, Base):
    """Administrator settings for one extra report font family.

    Attributes:
        font_key: The family key (`x-<slug>`).
        word_name: The name written to Word, OpenDocument and HTML; `None` means the family's own name.
        generic: Generic fallback family: `sans-serif`, `serif` or `monospace`.
        enabled: Whether authors are offered the family; `False` hides it from pickers but layouts already using
            it keep working.
        updated_by: The administrator who last changed it.
    """

    __tablename__ = "server_report_fonts"
    __table_args__ = (UniqueConstraint("font_key"),)

    font_key: Mapped[str] = mapped_column(String(80))
    word_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generic: Mapped[str] = mapped_column(String(20), default="sans-serif", server_default="sans-serif")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
