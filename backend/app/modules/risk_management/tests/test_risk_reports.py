"""Tests for the Risk Management reports RK1-RK4, through the real HTTP endpoints.

Covers, per report: content, labels, filters and the gap tables. Cross-cutting:
access (non-member, other organisation and disabled module are 404), scope
(child projects only when asked, readable and with the module on, each rated by
its own matrix), PDF/CSV output including formula neutralising, the catalogue
entries and the generated MCP tools. Every test builds its own organisation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.modules.registry import build_mcp_tool_manifest
from app.modules.risk_management.models import RiskTreatmentAssessment
from app.modules.risk_management.tests._helpers import (
    MODULE_KEY,
    add_effective_treatment,
    add_member,
    assess,
    create_risk,
    levels,
    mitigate_with_requirement,
    project_base,
    setup,
    user_ref,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

SLUGS = ("risk-register", "risk-exposure", "treatment-coverage", "review-schedule")


def _report(client, token, project_id, slug, expect=200, **params):
    resp = client.get(f"{project_base(project_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def _col(section, column: str) -> list[str]:
    index = section["columns"].index(column)
    return [row[index] for row in section["rows"]]


def _metric(report, label: str):
    return next(m["value"] for m in report["metrics"] if m["label"] == label)


def _move(client, token, project_id, risk_id, *statuses):
    for status in statuses:
        resp = client.post(
            f"{project_base(project_id)}/risks/{risk_id}/transition", json={"status": status, "comment": ""},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text


def _put(client, token, project_id, risk_id, **body):
    resp = client.put(f"{project_base(project_id)}/risks/{risk_id}", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _scored(client, token, project, *, inherent: tuple[str, str] | None, residual: tuple[str, str] | None = None, **extra) -> dict:
    """A risk scored on Likelihood and Consequence by level name (inherent, and optionally residual)."""
    lv = levels(client, token, project["id"])
    body = dict(extra)
    for prefix, pair in (("inherent", inherent), ("residual", residual)):
        if pair:
            body[f"{prefix}_likelihood_level_id"] = lv["likelihood"][pair[0]]
            body[f"{prefix}_consequence_level_id"] = lv["consequence"][pair[1]]
    return create_risk(client, token, project["id"], **body)


def _days(n: int) -> str:
    """A date `n` days from today as the app sees it: reports are dated in UTC, not the host's timezone."""
    return (datetime.now(UTC).date() + timedelta(days=n)).isoformat()


# --- RK1 --------------------------------------------------------------------------


def test_rk1_register_lists_risks_with_labels_ratings_and_owner(client, admin_token):
    _, project, token = setup(client, admin_token, "RK1 Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    types = {t["name"]: t["id"] for t in client.get(project_base(project["id"]) + "/risk-types", headers=auth_headers(token)).json()}
    treated = _scored(
        client, token, project, inherent=("Possible", "Catastrophic"), residual=("Unlikely", "Major"), title="Controller fails",
        risk_type_id=types["Safety"], owner=user_ref(me), treatment_strategy="mitigate", review_date=_days(10),
    )
    _move(client, token, project["id"], treated["id"], "assessed")
    unscored = create_risk(client, token, project["id"], title="Vague worry")

    report = _report(client, token, project["id"], "risk-register")
    register = _section(report, "register")
    rows = {r[0]: r for r in register["rows"]}
    cols = register["columns"]
    row = rows[treated["unique_code"]]
    assert row[cols.index("Status")] == "Assessed"  # the label, never `assessed`
    assert row[cols.index("Type")] == "Safety" and row[cols.index("Strategy")] == "Mitigate"
    assert row[cols.index("Inherent")] == "High" and row[cols.index("Residual")] == "Medium"
    assert row[cols.index("Owner")] != "" and row[cols.index("Next review")] == _days(10)
    bare = rows[unscored["unique_code"]]
    assert bare[cols.index("Inherent")] == "Not rated" and bare[cols.index("Status")] == "Identified"
    assert dict(_section(report, "by_status")["rows"])["Assessed"] == "1"
    assert dict(_section(report, "by_inherent")["rows"]) == {"High": "1", "Not rated": "1"}
    assert _metric(report, "Risks") == 2 and _metric(report, "Open") == 2
    assert report["eligible_projects"] == 1


def test_rk1_filters_by_status_type_and_archive(client, admin_token):
    _, project, token = setup(client, admin_token, "RK1 Filter Co")
    types = {t["name"]: t["id"] for t in client.get(project_base(project["id"]) + "/risk-types", headers=auth_headers(token)).json()}
    safety = _scored(client, token, project, inherent=("Likely", "Major"), title="Safety one", risk_type_id=types["Safety"])
    _move(client, token, project["id"], safety["id"], "assessed")
    create_risk(client, token, project["id"], title="Cost one", risk_type_id=types["Cost"])
    dropped = create_risk(client, token, project["id"], title="Dropped")
    assert client.post(
        f"{project_base(project['id'])}/risks/{dropped['id']}/archive", headers=auth_headers(token),
    ).status_code == 200

    def titles(**params):
        return sorted(_col(_section(_report(client, token, project["id"], "risk-register", **params), "register"), "Title"))

    assert titles() == ["Cost one", "Safety one"]  # archived hidden by default
    assert titles(include_archived=True) == ["Cost one", "Dropped", "Safety one"]
    assert titles(status="assessed") == ["Safety one"]
    assert titles(risk_type="cost") == ["Cost one"]  # case-insensitive name
    assert titles(status="assessed", risk_type="Cost") == []
    _report(client, token, project["id"], "risk-register", expect=400, status="nonsense")


# --- RK2 --------------------------------------------------------------------------


def test_rk2_exposure_compares_inherent_and_residual_and_leaves_out_history(client, admin_token):
    _, project, token = setup(client, admin_token, "RK2 Co")
    worst = _scored(client, token, project, inherent=("Almost certain", "Catastrophic"), residual=("Likely", "Major"), title="Worst")
    mild = _scored(client, token, project, inherent=("Possible", "Minor"), residual=("Possible", "Minor"), title="Mild")
    untreated = _scored(client, token, project, inherent=("Likely", "Major"), title="No residual yet")
    unrated = create_risk(client, token, project["id"], title="Unrated")
    closed = _scored(client, token, project, inherent=("Almost certain", "Catastrophic"), title="Settled")
    for risk in (worst, mild, untreated, closed):
        _move(client, token, project["id"], risk["id"], "assessed")
    _move(client, token, project["id"], closed["id"], "avoided", "closed")

    report = _report(client, token, project["id"], "risk-exposure")
    by_rating = {r[0]: r[1:] for r in _section(report, "by_rating")["rows"]}
    assert by_rating["Critical"] == ["1", "0"]  # worst: Critical inherent, High residual
    assert by_rating["High"] == ["1", "1"]  # inherent: the untreated one; residual: worst, once treated
    assert by_rating["Medium"] == ["1", "1"]  # mild is the same before and after
    assert by_rating["Not rated"] == ["1", "2"]  # no inherent for one; no residual for it and the unrated one
    assert _col(_section(report, "top_residual"), "Title")[0] == "Worst"  # highest residual first
    assert "Settled" not in _col(_section(report, "top_residual"), "Title")
    assert _col(_section(report, "not_rated"), "Title") == ["Unrated"]
    assert _metric(report, "Exposed Risks") == 4  # the avoided and closed one is not exposure
    assert _metric(report, "Treated (residual below inherent)") == 1
    assert _metric(report, "Not rated") == 1
    assert unrated["unique_code"] in {r[0] for r in _section(report, "not_rated")["rows"]}
    assert mild["unique_code"]


# --- RK3 --------------------------------------------------------------------------


def test_rk3_coverage_lists_untreated_and_stale_risks_and_counts_verdicts(client, admin_token):
    org, project, token = setup(client, admin_token, "RK3 Co")
    bare = _scored(client, token, project, inherent=("Likely", "Major"), title="Nothing linked")
    proposed_only = _scored(client, token, project, inherent=("Likely", "Major"), title="Only proposed")
    covered = _scored(client, token, project, inherent=("Likely", "Major"), title="Covered")
    stale = _scored(client, token, project, inherent=("Likely", "Major"), title="Stale verdict")
    _scored(client, token, project, inherent=("Rare", "Minor"), title="Not yet assessed")  # Identified: not expected to be treated
    for risk in (bare, proposed_only, covered, stale):
        _move(client, token, project["id"], risk["id"], "assessed")
    mitigate_with_requirement(client, token, org, project, proposed_only["id"])
    add_effective_treatment(client, token, org, project, covered["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, stale["id"])
    assert assess(client, token, project["id"], stale["id"], link_id, status="needs_reassessment", rationale="").status_code == 200

    report = _report(client, token, project["id"], "treatment-coverage")
    untreated = _section(report, "untreated")
    assert sorted(_col(untreated, "Title")) == ["Nothing linked", "Only proposed", "Stale verdict"]
    assert "Covered" not in _col(untreated, "Title") and "Not yet assessed" not in _col(untreated, "Title")
    rows = {r[1]: r for r in untreated["rows"]}
    cols = untreated["columns"]
    assert rows["Only proposed"][cols.index("Treatment links")] == "1" and rows["Only proposed"][cols.index("Proposed")] == "1"
    assert rows["Nothing linked"][cols.index("Treatment links")] == "0"
    assert _col(_section(report, "needs_reassessment"), "Title") == ["Stale verdict"]
    verdicts = dict(_section(report, "verdicts")["rows"])
    assert verdicts == {"Proposed": "1", "Effective": "1", "Ineffective": "0", "Needs reassessment": "1"}
    assert _metric(report, "Risks expected to be treated") == 4
    assert _metric(report, "With an effective treatment") == 1
    assert _metric(report, "No effective treatment") == 3 and _metric(report, "Needing reassessment") == 1


def test_rk3_a_link_with_no_verdict_row_counts_as_proposed(client, admin_token):
    org, project, token = setup(client, admin_token, "RK3 Proposed Co")
    risk = _scored(client, token, project, inherent=("Likely", "Major"), title="Linked only")
    _move(client, token, project["id"], risk["id"], "assessed")
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    db = SessionLocal()
    try:
        assert db.query(RiskTreatmentAssessment).filter_by(link_id=link_id).count() == 0
    finally:
        db.close()
    report = _report(client, token, project["id"], "treatment-coverage")
    assert dict(_section(report, "verdicts")["rows"])["Proposed"] == "1"


# --- RK4 --------------------------------------------------------------------------


def test_rk4_schedule_separates_overdue_due_soon_and_unscheduled(client, admin_token):
    _, project, token = setup(client, admin_token, "RK4 Co")
    overdue = _scored(client, token, project, inherent=("Likely", "Major"), title="Overdue", review_date=_days(30))
    soon = _scored(client, token, project, inherent=("Likely", "Major"), title="Soon", review_date=_days(5))
    later = _scored(client, token, project, inherent=("Likely", "Major"), title="Later", review_date=_days(90))
    unscheduled = _scored(client, token, project, inherent=("Likely", "Major"), title="Nobody looks")
    fresh = create_risk(client, token, project["id"], title="Just identified")
    done = _scored(client, token, project, inherent=("Likely", "Major"), title="Closed", review_date=_days(30))
    for risk in (overdue, soon, later, unscheduled, done):
        _move(client, token, project["id"], risk["id"], "assessed")
    _put(client, token, project["id"], overdue["id"], review_date=_days(-4))
    _put(client, token, project["id"], done["id"], review_date=_days(-4))
    _move(client, token, project["id"], done["id"], "rejected", "closed")

    report = _report(client, token, project["id"], "review-schedule")
    assert _col(_section(report, "overdue"), "Title") == ["Overdue"]
    assert _col(_section(report, "overdue"), "Days") == ["4 overdue"]
    assert _col(_section(report, "due_soon"), "Title") == ["Soon"]
    assert _col(_section(report, "unscheduled"), "Title") == ["Nobody looks"]  # Identified is exempt; Closed is history
    assert fresh["unique_code"] not in {r[0] for r in _section(report, "unscheduled")["rows"]}
    assert _metric(report, "Overdue") == 1 and _metric(report, "Due soon") == 1 and _metric(report, "No review scheduled") == 1

    wide = _report(client, token, project["id"], "review-schedule", due_within_days=120)
    assert _col(_section(wide, "due_soon"), "Title") == ["Soon", "Later"]
    _report(client, token, project["id"], "review-schedule", expect=422, due_within_days=0)
    assert later["unique_code"]


def test_rk4_shows_when_a_risk_was_last_reviewed(client, admin_token):
    _, project, token = setup(client, admin_token, "RK4 Last Co")
    risk = _scored(client, token, project, inherent=("Likely", "Major"), title="Reviewed once", review_date=_days(-2))
    _move(client, token, project["id"], risk["id"], "assessed")
    resp = client.post(
        f"{project_base(project['id'])}/risks/{risk['id']}/reviews",
        json={"outcome": "confirmed", "notes": "Fine.", "next_review_date": _days(1)}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    report = _report(client, token, project["id"], "review-schedule", due_within_days=5)
    assert _col(_section(report, "due_soon"), "Last reviewed") == [datetime.now(UTC).date().isoformat()]  # the app stamps UTC dates


# --- Cross-cutting ----------------------------------------------------------------


def test_reports_are_hidden_from_non_members_other_organisations_and_a_disabled_module(client, admin_token):
    org, project, token = setup(client, admin_token, "Gate Co")
    _, _, other_token = setup(client, admin_token, "Gate Other Co")
    org2, outsider = create_org_admin_in(client, admin_token, "Gate Outsider Co")
    off_project = create_project(client, outsider, org2["id"], "Off Project")
    member_id, member_token = add_member(client, token, org["id"], project["id"], "gate-member@risk-rep.example.com")
    assert member_id
    for slug in SLUGS:
        _report(client, member_token, project["id"], slug)  # any project member may read
        _report(client, other_token, project["id"], slug, expect=404)
        _report(client, outsider, off_project["id"], slug, expect=404)  # module not enabled for that org


def test_include_children_adds_readable_children_each_rated_by_its_own_matrix(client, admin_token):
    org, parent, admin = setup(client, admin_token, "RK Children Co")
    parent = create_project(client, admin, org["id"], "RK Parent", can_be_parent=True)
    child = create_project(client, admin, org["id"], "RK Child", parent_project_id=parent["id"])
    _scored(client, admin, parent, inherent=("Likely", "Major"), title="Parent risk")
    _scored(client, admin, child, inherent=("Likely", "Major"), title="Child risk")

    own = _report(client, admin, parent["id"], "risk-register")
    assert _col(_section(own, "register"), "Title") == ["Parent risk"]
    widened = _report(client, admin, parent["id"], "risk-register", include_children=True)
    assert sorted(_col(_section(widened, "register"), "Title")) == ["Child risk", "Parent risk"]
    assert widened["eligible_projects"] == 2

    resp = client.put(
        f"/api/v1/projects/{child['id']}/modules/{MODULE_KEY}/enablement", json={"enabled": False}, headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    off = _report(client, admin, parent["id"], "risk-register", include_children=True)
    assert _col(_section(off, "register"), "Title") == ["Parent risk"]


def test_a_childs_own_cell_rating_is_used_for_its_risks(client, admin_token):
    org, parent, admin = setup(client, admin_token, "RK Own Matrix Co")
    parent = create_project(client, admin, org["id"], "RK Matrix Parent", can_be_parent=True)
    child = create_project(client, admin, org["id"], "RK Matrix Child", parent_project_id=parent["id"])
    lv = levels(client, admin, child["id"])
    # Pin Rare x Catastrophic to Critical for the child only (a cell the thresholds would call Medium).
    resp = client.put(
        f"/api/v1/projects/{child['id']}/scoring-schemes/risk/models/lxc/cell-ratings",
        json={"cells": [{
            "first_level_id": lv["likelihood"]["Rare"], "second_level_id": lv["consequence"]["Catastrophic"], "band_label": "Critical",
        }]}, headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    _scored(client, admin, parent, inherent=("Rare", "Catastrophic"), title="Parent corner")
    _scored(client, admin, child, inherent=("Rare", "Catastrophic"), title="Child corner")

    report = _report(client, admin, parent["id"], "risk-register", include_children=True)
    register = _section(report, "register")
    by_title = dict(zip(_col(register, "Title"), _col(register, "Inherent"), strict=True))
    assert by_title == {"Parent corner": "Medium", "Child corner": "Critical"}


def test_csv_neutralises_formulas_and_pdf_survives_markup_and_long_text(client, admin_token):
    _, project, token = setup(client, admin_token, "RK Render Co")
    _scored(client, token, project, inherent=("Likely", "Major"), title='=HYPERLINK("http://evil.example","x")', review_date=_days(-1))
    _scored(client, token, project, inherent=("Likely", "Major"), title="<img src='file:///etc/passwd'/> & <b>bold</b>", statement="word " * 5000)
    for slug in SLUGS:
        csv = _report(client, token, project["id"], slug, format="csv")
        assert csv.headers["content-type"].startswith("text/csv")
        pdf = _report(client, token, project["id"], slug, format="pdf")
        assert pdf.content[:5] == b"%PDF-"
    register_csv = _report(client, token, project["id"], "risk-register", format="csv").text
    assert "'=HYPERLINK" in register_csv and ",=HYPERLINK" not in register_csv


def test_catalogue_lists_the_four_project_reports_and_none_organisation_wide(client, admin_token):
    org, project, token = setup(client, admin_token, "RK Catalogue Co")
    entries = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()
    mine = {e["slug"]: e for e in entries if e["module_key"] == MODULE_KEY}
    assert set(mine) == set(SLUGS)
    for slug, entry in mine.items():
        assert entry["path"] == f"{project_base(project['id'])}/reports/{slug}"
        assert client.get(entry["path"], headers=auth_headers(token)).status_code == 200
    assert {p["name"] for p in mine["risk-register"]["params"]} == {"status", "risk_type", "include_archived"}
    assert {p["name"] for p in mine["review-schedule"]["params"]} == {"due_within_days"}
    org_entries = client.get(f"/api/v1/orgs/{org['id']}/report-catalogue", headers=auth_headers(token)).json()
    assert not [e for e in org_entries if e["module_key"] == MODULE_KEY]


def test_each_report_is_declared_as_a_read_only_mcp_tool():
    tools = {t.name: t for t in build_mcp_tool_manifest() if t.name.startswith("risk_management_")}
    for slug in SLUGS:
        tool = tools[f"risk_management_get_{slug.replace('-', '_')}_report"]
        assert tool.method == "GET" and not tool.mutates
    assert {p["name"] for p in tools["risk_management_get_review_schedule_report"].params} >= {"project_id", "due_within_days"}
