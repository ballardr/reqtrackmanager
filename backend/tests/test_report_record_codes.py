"""Tests for how reports, exports and embedded references name a record: the shared server-side
code formatter (`services.codes.display_code`, `ReportContext.code` / `org_code`), the rule that
every registered report declares which record types it names, and the requirement report's
ID and Tags columns.

Per-module report behaviour (the code and Tags columns of each module's reports) is tested beside
each module's other report tests.
"""

from __future__ import annotations

import csv
import io
from types import SimpleNamespace

import pytest

from app.modules.registry import get_all_registered_artefact_types, get_all_reports
from app.services.codes import display_code
from app.services.report_framework import ReportContext
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


@pytest.mark.parametrize(
    ("owner", "own", "enforced", "org_owned", "expected"),
    [
        ("ACME", "ACME", False, False, "REQ-001"),  # inside the reported project: bare
        ("ACME", "ACME", True, False, "ACME-REQ-001"),  # ... unless the organisation enforces the project code
        ("CHILD", "ACME", False, False, "CHILD-REQ-001"),  # a record from another project is always qualified
        ("CHILD", None, False, False, "CHILD-REQ-001"),  # an output about no one project qualifies every record
        ("ORG", "ACME", False, True, "ORG-REQ-001"),  # an organisation-owned record is always qualified
        (None, "ACME", True, False, "REQ-001"),  # no owner code known: left bare rather than guessed
    ],
)
def test_display_code_follows_the_one_rule(owner, own, enforced, org_owned, expected):
    assert display_code("REQ-001", owner, own_project_code=own, enforced=enforced, organization_owned=org_owned) == expected


def test_display_code_leaves_an_empty_code_alone():
    assert display_code("", "ACME", organization_owned=True) == ""


def _context(*, enforced: bool, root: bool = True) -> tuple[ReportContext, SimpleNamespace, SimpleNamespace]:
    parent = SimpleNamespace(id="p", code="PAR", name="Parent")
    child = SimpleNamespace(id="c", code="KID", name="Child")
    organization = SimpleNamespace(code="ORG", enforce_code_everywhere=enforced, name="Org")
    context = ReportContext(
        module_key="m", organization=organization, projects=[parent, child], root_project=parent if root else None,
    )
    return context, parent, child


def test_report_context_codes_bare_in_the_root_project_and_qualified_for_a_child():
    context, parent, child = _context(enforced=False)
    assert context.code("DEC-001", parent.id) == "DEC-001"
    assert context.code("DEC-001", child.id) == "KID-DEC-001"
    assert context.org_code("PER-001") == "ORG-PER-001"


def test_report_context_qualifies_everything_when_enforced_or_organisation_wide():
    enforced, parent, child = _context(enforced=True)
    assert [enforced.code("DEC-001", p.id) for p in (parent, child)] == ["PAR-DEC-001", "KID-DEC-001"]
    organisation_wide, parent, _ = _context(enforced=False, root=False)
    assert organisation_wide.code("DEC-001", parent.id) == "PAR-DEC-001"


def test_report_context_qualifies_a_project_outside_the_scope_only_when_its_code_is_given():
    context, _, _ = _context(enforced=False)
    assert context.code("DEC-001", "elsewhere") == "DEC-001"
    assert context.code("DEC-001", "elsewhere", "OUT") == "OUT-DEC-001"


def test_every_registered_report_declares_the_record_types_it_names():
    """A report that lists records must say which, so a new one cannot skip the shared code and Tags helpers
    unnoticed; each declared type is a registered artefact type."""
    registered = get_all_registered_artefact_types()
    reports = get_all_reports()
    assert reports, "no reports are registered"
    for module_key, report in reports:
        assert report.record_types, f"{module_key} report '{report.slug}' declares no record_types"
        assert set(report.record_types) <= registered, (
            f"{module_key} report '{report.slug}' names unregistered types {set(report.record_types) - registered}"
        )


def _requirement_csv(client, token, project_id, **body) -> list[list[str]]:
    resp = client.post(f"/api/v1/projects/{project_id}/reports", json={"format": "csv", **body}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))


def test_requirement_report_lists_codes_by_the_report_rule_and_tags(client, admin_token):
    """The ID is bare in the project's own report unless the organisation enforces the project code (the viewer's
    preference is ignored), and Tags lists the requirement's tags."""
    org, token = create_org_admin_in(client, admin_token, "Req Report Codes Co")
    project = create_project(client, token, org["id"], "Req Report Codes Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Tagged requirement", "component_id": component_id, "category_id": category_id, "keywords": ["Safety"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    assert client.patch(
        "/api/v1/auth/me/preferences", json={"ui_preferences": {"show_project_code": True}}, headers=auth_headers(token),
    ).status_code == 200

    header, row = _requirement_csv(client, token, project["id"])
    assert header[-1] == "Tags" and (row[0], row[-1]) == ("SW-PERF-001", "Safety")

    policy = {"kind": "alphanumeric", "min_length": 2, "max_length": 6, "assignment": "auto", "enforce_code_everywhere": True}
    assert client.put(f"/api/v1/orgs/{org['id']}/code-policy", json=policy, headers=auth_headers(token)).status_code == 200
    assert _requirement_csv(client, token, project["id"])[1][0] == f"{project['code']}-SW-PERF-001"


def test_pdf_columns_are_sized_so_a_qualified_code_stays_on_one_line():
    """A dozen equal columns split `ACME-PER-001` across two lines; widths follow the content instead."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from app.services.report_model import Table
    from app.services.report_pdf import _CELL_FONT_SIZE, _content_widths

    columns = ["Code", "Persona", "Project", "Status", "Weight", "Linked stakeholders", "Engagements", "Anonymous participants",
               "Findings", "Last engagement", "Evidence", "Tags"]
    row = ["ACME-PER-001", "Shared technician", "Atlas Platform", "Active", "3", "Tara, Sam", "2", "1", "1", "2026-10-01",
           "Evidenced", "Fieldwork, Safety"]
    usable = 770.0
    widths = _content_widths(Table(columns, [row]), usable)
    assert len(widths) == len(columns) and abs(sum(widths) - usable) < 0.01
    assert widths[0] > stringWidth("ACME-PER-001", "Helvetica", _CELL_FONT_SIZE) + 12  # the code plus the cell padding
    # A table too wide for the page is scaled down together rather than overflowing.
    crowded = _content_widths(Table([f"Heading number {i}" for i in range(40)], [["x" * 20] * 40]), usable)
    assert abs(sum(crowded) - usable) < 0.01


def test_pdf_column_widths_ignore_a_pasted_unbroken_string():
    from app.services.report_model import Table
    from app.services.report_pdf import _content_widths

    widths = _content_widths(Table(["Code", "Note"], [["ACME-REQ-001", "x" * 5000]]), 770.0)
    assert abs(sum(widths) - 770.0) < 0.01 and widths[0] > 60  # the code still has room, the string does not take the page
