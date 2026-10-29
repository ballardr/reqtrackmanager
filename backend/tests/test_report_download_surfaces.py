"""
Pins that every report download surface offers every file format the renderers produce.

A new renderer registered in `services.report_render` must reach the requirement report, both compliance reports, the
record-list report and the report framework's module reports, and the frontend's format controls, or the surface
gives a stated reason in `EXEMPT` below. The frontend checks read source text and are skipped when the repository
root is not visible (the backend container mounts only backend/).
"""

import re
import typing
from pathlib import Path

import pytest

from app.modules.compliance.report_files import ComplianceReportFormat
from app.schemas.report import ReportRequest
from app.services import report_render
from app.services.report_framework import ReportFormat

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

#: Every file format the renderers produce.
RENDERED = set(report_render._RENDERERS)

#: `surface -> {format: reason}`: formats a surface deliberately does not offer.
EXEMPT: dict[str, dict[str, str]] = {
    "record-list menu": {
        "html": "a list is downloaded to be filed or edited; HTML is a screen view, offered by Download report",
        "xlsx": "ODS and CSV already cover a spreadsheet; Excel is offered by Download report and the report setup",
    },
}


def _literal_values(annotation) -> set[str]:
    return set(typing.get_args(annotation))


def test_requirement_report_offers_every_rendered_format():
    assert _literal_values(ReportRequest.model_fields["format"].annotation) == RENDERED


def test_compliance_reports_offer_every_rendered_format():
    assert _literal_values(ComplianceReportFormat) == RENDERED


def test_report_framework_and_record_list_offer_every_rendered_format():
    assert _literal_values(ReportFormat) - {"json"} == RENDERED


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend sources not available")
def test_frontend_format_map_names_every_rendered_format():
    source = (FRONTEND / "api" / "reportFormats.ts").read_text()
    body = source[source.index("export const REPORT_FORMAT"):]
    assert set(re.findall(r"^\s{2}(\w+): \{ label:", body, re.M)) == RENDERED


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend sources not available")
def test_record_list_menu_offers_every_rendered_format_or_says_why():
    source = (FRONTEND / "api" / "recordTables.ts").read_text()
    kinds = re.search(r"RECORD_LIST_EXPORT_KINDS[^=]*=\s*\[([^\]]*)\]", source)
    assert kinds, "api/recordTables.ts must declare RECORD_LIST_EXPORT_KINDS"
    offered = set(re.findall(r'"(\w+)"', kinds.group(1)))
    assert offered | set(EXEMPT["record-list menu"]) == RENDERED
    assert not offered & set(EXEMPT["record-list menu"])


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend sources not available")
def test_requirement_report_panel_offers_every_rendered_format():
    source = (FRONTEND / "components" / "RequirementReportPanel.tsx").read_text()
    assert "REQUIREMENT_REPORT_FORMATS" in source
    declared = re.search(r"REQUIREMENT_REPORT_FORMATS[^=]*=\s*\[([^\]]*)\]", source)
    assert declared and set(re.findall(r'"(\w+)"', declared.group(1))) == RENDERED


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend sources not available")
def test_compliance_exports_offer_every_rendered_format():
    source = (FRONTEND / "modules" / "compliance" / "api.ts").read_text()
    assert "ComplianceReportKind" in source
    declared = re.search(r"COMPLIANCE_REPORT_KINDS[^=]*=\s*\[([^\]]*)\]", source)
    assert declared and set(re.findall(r'"(\w+)"', declared.group(1))) == RENDERED
