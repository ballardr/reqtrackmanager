"""
Module: routers.system.report_fonts

Server administration of the extra report fonts: list the families found in the mounted font directory, set each one's
name for Word and OpenDocument, its generic fallback and whether authors are offered it, and rescan. Also the picker list
for authors.

Responsibilities:
- `GET /system/report-fonts`, `PUT /system/report-fonts/{key}`, `POST /system/report-fonts/rescan` (server administrator).
- `GET /system/report-fonts/choices` (any signed-in user): the families an author may pick.

Design decisions:
- Responses carry file names, never directory paths or file contents; the directory is set by the deployment, not by a request.
- A change and a rescan are each one audit event with the family key and counts (`report_font.*`), never file contents.
- The licence is the administrator's responsibility; the page says so and reports each face's embedding permission.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import report_font_catalogue as catalogue
from app.services.audit import log_event
from app.services.rbac import require_server_admin
from app.services.report_font_directory import FS_TYPE_LABELS, MAX_FONT_BYTES

router = APIRouter(tags=["system-report-fonts"])

# A name safe to write into CSS, XML attributes and a Word font table without escaping surprises.
_NAME = re.compile(r"^[\w][\w ._()+\-]{0,98}$")


class ReportFontFace(BaseModel):
    """One real font file of a family."""

    style: str
    permission: str


class ReportFontOut(BaseModel):
    """A font family for the administrator."""

    key: str
    label: str
    bundled: bool
    enabled: bool
    missing: bool
    word_name: str
    generic: str
    faces: list[ReportFontFace]


class ReportFontSkipped(BaseModel):
    """A file in the directory that was not used."""

    file_name: str
    reason: str


class ReportFontsOut(BaseModel):
    """The font page."""

    directory_configured: bool
    max_file_mb: int
    families: list[ReportFontOut]
    skipped: list[ReportFontSkipped]


class ReportFontUpdate(BaseModel):
    """An administrator's settings for one extra family."""

    word_name: str | None = Field(default=None, max_length=100)
    generic: Literal["sans-serif", "serif", "monospace"]
    enabled: bool

    @field_validator("word_name")
    @classmethod
    def _safe_name(cls, value: str | None) -> str | None:
        """Refuses a name with quotes, angle brackets, semicolons or control characters."""
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _NAME.match(value):
            raise ValueError("Use letters, digits, spaces and . _ ( ) + - only")
        return value


class ReportFontChoice(BaseModel):
    """A family an author may pick."""

    key: str
    label: str
    bundled: bool
    generic: str


def _out(info: catalogue.FontInfo) -> ReportFontOut:
    """The response shape of one family."""
    return ReportFontOut(
        key=info.key, label=info.label, bundled=info.bundled, enabled=info.enabled, missing=info.missing,
        word_name=info.word_name, generic=info.generic,
        faces=[
            ReportFontFace(style=s, permission=FS_TYPE_LABELS.get(info.fs_types.get(s, 0), "Restricted") if not info.bundled else "Installable")
            for s in info.faces_found
        ],
    )


def _page(db: Session) -> ReportFontsOut:
    """The font page for the current scan."""
    scan = catalogue.current_scan()
    return ReportFontsOut(
        directory_configured=scan.configured, max_file_mb=MAX_FONT_BYTES // (1024 * 1024),
        families=[_out(i) for i in catalogue.describe_fonts(db)],
        skipped=[ReportFontSkipped(file_name=s.file_name, reason=s.reason) for s in scan.skipped],
    )


@router.get("/report-fonts", response_model=ReportFontsOut)
def list_report_fonts(_: User = Depends(require_server_admin), db: Session = Depends(get_db)):
    """Every family, hidden and missing included, and the files that were skipped (server administrator)."""
    return _page(db)


@router.get("/report-fonts/choices", response_model=list[ReportFontChoice])
def report_font_choices(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The families an author's picker offers: the bundled four, then the enabled extras (any signed-in user)."""
    return [
        ReportFontChoice(key=i.key, label=i.label, bundled=i.bundled, generic=i.generic)
        for i in catalogue.author_choices(db)
    ]


@router.post("/report-fonts/rescan", response_model=ReportFontsOut)
def rescan_report_fonts(current_user: User = Depends(require_server_admin), db: Session = Depends(get_db)):
    """Scans the font directory again now (server administrator). Other workers follow within a minute."""
    scan = catalogue.rescan()
    log_event(
        db, entity_type="report_font", entity_id="directory", action="report_font.rescanned", actor_id=current_user.id,
        detail={"families": len(scan.families), "skipped": len(scan.skipped)},
    )
    db.commit()
    return _page(db)


@router.put("/report-fonts/{font_key}", response_model=ReportFontsOut)
def update_report_font(
    font_key: str,
    payload: ReportFontUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sets an extra family's name for Word and OpenDocument, generic fallback and whether authors are offered it."""
    try:
        catalogue.update_font(
            db, font_key, word_name=payload.word_name, generic=payload.generic, enabled=payload.enabled,
            actor_id=current_user.id,
        )
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such font family") from None
    log_event(
        db, entity_type="report_font", entity_id=font_key, action="report_font.updated", actor_id=current_user.id,
        detail={"enabled": payload.enabled, "generic": payload.generic, "word_name_set": payload.word_name is not None},
    )
    db.commit()
    return _page(db)
