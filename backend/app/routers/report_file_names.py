"""
Module: routers.report_file_names

The live example beside a "File name" field: what a template would name a downloaded report.

Responsibilities:
- `POST /api/v1/report-file-names/example`: the example name for a template (or the problems with it).

Design decisions:
- Stateless and data-free: it is a pure function of the text sent and fixed sample values (`services.report_file_names`),
  so any signed-in person may call it and nothing is read, stored, audited or logged. The template is not logged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models.user import User
from app.schemas.report_file_name import FileNameExampleOut, FileNameExampleRequest
from app.services import report_file_names

router = APIRouter(prefix="/api/v1/report-file-names", tags=["report-file-names"])


@router.post("/example", response_model=FileNameExampleOut)
def file_name_example(body: FileNameExampleRequest, current_user: User = Depends(get_current_user)) -> FileNameExampleOut:
    """Fills a template with sample values: the file name it would give, or what is wrong with it (200 either way)."""
    name, problems = report_file_names.example(
        body.template, kind=body.kind, variables=body.variables, extension=body.extension,
    )
    return FileNameExampleOut(
        example=name, problems=problems, placeholders=report_file_names.allowed_placeholders(body.kind, body.variables),
    )
