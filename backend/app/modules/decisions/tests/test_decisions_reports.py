"""Tests for the Decision Management reports D1–D4 (docs/plans/platform-
enhancements-2026-10-plan.md Phase 8), through the real HTTP endpoints.

Covers, per report: content, filters and the sections gap tables are built
from. Cross-cutting: access (non-member and disabled module are 404), scope
(child projects only when asked and only if readable, other organisations
never), PDF/CSV output including formula neutralising and an over-long
free-text cell, the catalogue entries, and that no organisation-wide variant
exists. Every test builds its own organisation, so none depends on another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import update

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

MODULE_KEY = "decisions"
SLUGS = ("decision-register", "approval-ageing", "decision-log", "rationale-coverage")


def _base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _today() -> date:
    """The reports' reference date (UTC), not the host's local date."""
    return datetime.now(UTC).date()


def _setup(client, admin_token, name):
    """Org (with admin) with Decision Management on, and a project the admin manages."""
    org, token = create_org_admin_in(client, admin_token, name)
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _type_ids(client, token, project_id) -> dict[str, str]:
    resp = client.get(f"{_base(project_id)}/decision-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {t["name"]: t["id"] for t in resp.json()}


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def _decision(client, token, project_id, title, type_name="Architecture", **extra) -> dict:
    payload = {
        "title": title, "decision_statement": f"We will {title.lower()}.",
        "decision_type_id": _type_ids(client, token, project_id)[type_name], **extra,
    }
    resp = client.post(_base(project_id), json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _post(client, token, project_id, decision_id, action, expect=200, **body) -> dict:
    # Transitions with no payload (propose, submit-for-review) take no body; every other action requires one.
    payload = None if action in ("propose", "submit-for-review") else body
    resp = client.post(f"{_base(project_id)}/{decision_id}/{action}", json=payload, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _to_review(client, token, project_id, decision_id) -> None:
    _post(client, token, project_id, decision_id, "propose")
    _post(client, token, project_id, decision_id, "submit-for-review")


def _approved(client, token, project_id, title, **extra) -> dict:
    decision = _decision(client, token, project_id, title, **extra)
    _to_review(client, token, project_id, decision["id"])
    return _post(client, token, project_id, decision["id"], "approve")


def _report(client, token, project_id, slug, expect=200, **params):
    resp = client.get(f"{_base(project_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def _col(section, column: str) -> list[str]:
    index = section["columns"].index(column)
    return [row[index] for row in section["rows"]]


def _metric(report, label: str):
    return next(m["value"] for m in report["metrics"] if m["label"] == label)


def _backdate_status_entry(decision_id: str, days: int) -> None:
    """Moves the audit events that put a Decision into its awaiting status `days` into the past."""
    db = SessionLocal()
    try:
        stamp = datetime.now(UTC) - timedelta(days=days)
        db.execute(update(AuditEvent).where(
            AuditEvent.entity_type == "decision", AuditEvent.entity_id == decision_id,
            AuditEvent.action.in_(["proposed", "submitted_for_review"]),
        ).values(created_at=stamp))
        db.commit()
    finally:
        db.close()


def test_d1_register_lists_decisions_with_labels_people_and_supersession(client, admin_token):
    _, project, token = _setup(client, admin_token, "D1 Co")
    old = _approved(client, token, project["id"], "Use REST", decision_date="2026-01-10")
    new = _decision(client, token, project["id"], "Use GraphQL", type_name="Design", decision_maker_id=_me(client, token))
    _post(client, token, project["id"], new["id"], "supersessions", 201, old_decision_id=old["id"])
    _to_review(client, token, project["id"], new["id"])
    _post(client, token, project["id"], new["id"], "approve")

    report = _report(client, token, project["id"], "decision-register")
    rows = {r[0]: r for r in _section(report, "register")["rows"]}
    columns = _section(report, "register")["columns"]
    old_row, new_row = rows[old["unique_code"]], rows[new["unique_code"]]

    assert old_row[columns.index("Status")] == "Superseded"  # the label, never `superseded`
    assert old_row[columns.index("Decision date")] == "2026-01-10"
    assert old_row[columns.index("Superseded by")] == new["unique_code"]
    assert new_row[columns.index("Supersedes")] == old["unique_code"]
    assert new_row[columns.index("Type")] == "Design"
    assert new_row[columns.index("Decision maker")] != ""
    assert new_row[columns.index("Owner")] != ""
    assert dict(_section(report, "by_status")["rows"])["Superseded"] == "1"
    assert dict(_section(report, "by_type")["rows"]) == {"Architecture": "1", "Design": "1"}
    assert _metric(report, "Decisions") == 2 and _metric(report, "Superseded") == 1
    assert report["eligible_projects"] == 1


def test_d1_filters_by_status_type_dates_and_archive(client, admin_token):
    _, project, token = _setup(client, admin_token, "D1 Filter Co")
    jan = _approved(client, token, project["id"], "January call", decision_date="2026-01-15")
    _decision(client, token, project["id"], "March call", type_name="Strategy", decision_date="2026-03-15")
    archived = _decision(client, token, project["id"], "Dropped idea")
    assert client.post(f"{_base(project['id'])}/{archived['id']}/archive", headers=auth_headers(token)).status_code == 200

    def titles(**params):
        return _col(_section(_report(client, token, project["id"], "decision-register", **params), "register"), "Title")

    assert sorted(titles()) == ["January call", "March call"]  # archived hidden by default
    assert sorted(titles(include_archived=True)) == ["Dropped idea", "January call", "March call"]
    assert titles(status="approved") == ["January call"]
    assert titles(decision_type="strategy") == ["March call"]  # case-insensitive name
    assert titles(date_from="2026-02-01") == ["March call"]
    assert titles(date_to="2026-02-01") == ["January call"]
    assert titles(status="approved", decision_type="Strategy") == []
    assert jan["unique_code"]
    _report(client, token, project["id"], "decision-register", expect=400, status="nonsense")


def test_d2_ageing_orders_by_wait_and_flags_overdue_and_missing_decision_maker(client, admin_token):
    _, project, token = _setup(client, admin_token, "D2 Co")
    me = _me(client, token)
    stale = _decision(client, token, project["id"], "Stale call", decision_maker_id=me)
    fresh = _decision(client, token, project["id"], "Fresh call")
    proposed = _decision(client, token, project["id"], "Just proposed", decision_maker_id=me)
    _decision(client, token, project["id"], "Still a draft")
    _to_review(client, token, project["id"], stale["id"])
    _to_review(client, token, project["id"], fresh["id"])
    _post(client, token, project["id"], proposed["id"], "propose")
    _backdate_status_entry(stale["id"], 30)
    _backdate_status_entry(fresh["id"], 3)

    report = _report(client, token, project["id"], "approval-ageing")
    awaiting = _section(report, "awaiting")
    assert _col(awaiting, "Title") == ["Stale call", "Fresh call", "Just proposed"]  # longest wait first; draft excluded
    assert _col(awaiting, "Days waiting") == ["30", "3", "0"]
    assert _col(awaiting, "Status") == ["Under review", "Under review", "Proposed"]
    assert _col(_section(report, "overdue"), "Title") == ["Stale call"]
    assert _col(_section(report, "unassigned"), "Title") == ["Fresh call"]
    assert _metric(report, "Longest wait (days)") == 30

    wider = _report(client, token, project["id"], "approval-ageing", overdue_days=60)
    assert _section(wider, "overdue")["rows"] == []
    tighter = _report(client, token, project["id"], "approval-ageing", overdue_days=2)
    assert _col(_section(tighter, "overdue"), "Title") == ["Stale call", "Fresh call"]
    _report(client, token, project["id"], "approval-ageing", expect=422, overdue_days=0)


def test_d2_leaves_out_decisions_that_have_a_verdict(client, admin_token):
    _, project, token = _setup(client, admin_token, "D2 Done Co")
    _approved(client, token, project["id"], "Settled")
    rejected = _decision(client, token, project["id"], "Declined")
    _post(client, token, project["id"], rejected["id"], "propose")
    _post(client, token, project["id"], rejected["id"], "reject", comment="No")

    report = _report(client, token, project["id"], "approval-ageing")
    assert _section(report, "awaiting")["rows"] == []
    assert _metric(report, "Awaiting a verdict") == 0


def test_d3_log_covers_the_period_and_only_decisions_that_were_made(client, admin_token):
    _, project, token = _setup(client, admin_token, "D3 Co")
    recent = (_today() - timedelta(days=10)).isoformat()
    _approved(
        client, token, project["id"], "Recent call", decision_date=recent, context="Traffic doubled",
        chosen_option="Scale out", rationale="Cheapest path",
    )
    _approved(client, token, project["id"], "Old call", decision_date=(_today() - timedelta(days=400)).isoformat())
    _decision(client, token, project["id"], "Not yet made", decision_date=recent)
    declined = _decision(client, token, project["id"], "Declined call", decision_date=recent)
    _post(client, token, project["id"], declined["id"], "propose")
    _post(client, token, project["id"], declined["id"], "reject", comment="No")

    default = _report(client, token, project["id"], "decision-log")
    log = _section(default, "log")
    assert _col(log, "Title") == ["Recent call"]  # default window is the last 90 days; draft and rejected excluded
    assert _col(log, "Context") == ["Traffic doubled"]
    assert _col(log, "Chosen option") == ["Scale out"]
    assert _col(log, "Rationale") == ["Cheapest path"]
    assert _col(log, "Status") == ["Approved"]
    assert _metric(default, "Decisions made") == 1

    wide = _report(client, token, project["id"], "decision-log", date_from="2020-01-01")
    assert _col(_section(wide, "log"), "Title") == ["Old call", "Recent call"]  # oldest first
    narrow = _report(client, token, project["id"], "decision-log", date_from="2020-01-01", date_to="2025-01-01")
    assert _section(narrow, "log")["rows"] == []


def test_d3_counts_decisions_without_a_rationale_as_a_gap(client, admin_token):
    _, project, token = _setup(client, admin_token, "D3 Gap Co")
    today = _today().isoformat()
    _approved(client, token, project["id"], "Reasoned", decision_date=today, rationale="Because")
    _approved(client, token, project["id"], "Unreasoned", decision_date=today)
    report = _report(client, token, project["id"], "decision-log")
    assert _metric(report, "Without a rationale") == 1


def test_d4_lists_decisions_without_links_and_requirements_without_decisions(client, admin_token):
    _, project, token = _setup(client, admin_token, "D4 Co")
    component_id, category_id = create_component_and_category(client, token, project["id"])

    def requirement(name) -> dict:
        resp = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    justified = _decision(client, token, project["id"], "Justified")
    bare = _decision(client, token, project["id"], "Bare")
    chained = _decision(client, token, project["id"], "Only linked to a decision")
    covered, uncovered = requirement("Covered requirement"), requirement("Uncovered requirement")
    _post(client, token, project["id"], justified["id"], "requirement-links", 201, requirement_id=covered["id"], kind="implements")
    _post(client, token, project["id"], chained["id"], "decision-links", 201, target_decision_id=bare["id"], kind="depends_on")
    history = _approved(client, token, project["id"], "Old approach")
    replacement = _decision(client, token, project["id"], "New approach")
    _post(client, token, project["id"], replacement["id"], "supersessions", 201, old_decision_id=history["id"])
    _to_review(client, token, project["id"], replacement["id"])
    _post(client, token, project["id"], replacement["id"], "approve")

    report = _report(client, token, project["id"], "rationale-coverage")
    no_links = _col(_section(report, "decisions_without_links"), "Title")
    # A decision-to-decision link is not rationale; superseded history is not expected to have any.
    assert sorted(no_links) == ["Bare", "New approach", "Only linked to a decision"]
    assert _col(_section(report, "requirements_without_decisions"), "Name") == ["Uncovered requirement"]
    assert _metric(report, "Live Decisions") == 4 and _metric(report, "Decisions with no linked artefact") == 3
    assert _metric(report, "Requirements") == 2 and _metric(report, "Requirements with no linked Decision") == 1
    assert uncovered["id"]


def test_d4_requirement_linked_only_to_an_archived_requirement_is_not_listed(client, admin_token):
    _, project, token = _setup(client, admin_token, "D4 Archive Co")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Gone", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{resp.json()['id']}", headers=auth_headers(token),
    ).status_code == 204
    report = _report(client, token, project["id"], "rationale-coverage")
    assert _section(report, "requirements_without_decisions")["rows"] == []


def test_reports_are_404_for_non_members_and_when_the_module_is_off(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Gate Co")
    create_org_user(client, admin, org["id"], "gate_outsider@example.com")
    outsider = login(client, "gate_outsider@example.com", "Password123!")
    for slug in SLUGS:
        _report(client, outsider, project["id"], slug, expect=404)

    off_org, off_token = create_org_admin_in(client, admin_token, "Gate Off Co")
    off_project = create_project(client, off_token, off_org["id"], "Off Project")
    for slug in SLUGS:
        _report(client, off_token, off_project["id"], slug, expect=404)


def test_a_member_of_another_organisation_cannot_run_the_reports(client, admin_token):
    _, project, _ = _setup(client, admin_token, "Iso A Co")
    _, _, other_token = _setup(client, admin_token, "Iso B Co")
    for slug in SLUGS:
        _report(client, other_token, project["id"], slug, expect=404)


def test_include_children_only_adds_readable_child_projects_with_the_module_on(client, admin_token):
    org, _, admin = _setup(client, admin_token, "Children Co")
    parent = create_project(client, admin, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, admin, org["id"], "Child", parent_project_id=parent["id"])
    _decision(client, admin, parent["id"], "Parent call")
    _decision(client, admin, child["id"], "Child call")

    own = _report(client, admin, parent["id"], "decision-register")
    assert _col(_section(own, "register"), "Title") == ["Parent call"]
    widened = _report(client, admin, parent["id"], "decision-register", include_children=True)
    assert sorted(_col(_section(widened, "register"), "Title")) == ["Child call", "Parent call"]
    assert widened["eligible_projects"] == 2

    user_id = create_org_user(client, admin, org["id"], "parent_only@example.com")
    assert client.post(
        f"/api/v1/projects/{parent['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin),
    ).status_code == 204
    parent_only = login(client, "parent_only@example.com", "Password123!")
    limited = _report(client, parent_only, parent["id"], "decision-register", include_children=True)
    assert _col(_section(limited, "register"), "Title") == ["Parent call"]

    # Switching the module off for the child alone removes it from a widened parent report.
    resp = client.put(
        f"/api/v1/projects/{child['id']}/modules/{MODULE_KEY}/enablement", json={"enabled": False},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    off = _report(client, admin, parent["id"], "decision-register", include_children=True)
    assert _col(_section(off, "register"), "Title") == ["Parent call"]
    assert off["eligible_projects"] == 1


def test_csv_neutralises_formulas_and_pdf_survives_markup_and_very_long_text(client, admin_token):
    _, project, token = _setup(client, admin_token, "Render Co")
    today = _today().isoformat()
    _approved(client, token, project["id"], '=HYPERLINK("http://evil.example","x")', decision_date=today)
    _approved(
        client, token, project["id"], "<img src='file:///etc/passwd'/> & <b>bold</b>", decision_date=today,
        context="word " * 5000, rationale="x" * 20000,
    )

    for slug in SLUGS:
        csv = _report(client, token, project["id"], slug, format="csv")
        assert csv.headers["content-type"].startswith("text/csv")
        pdf = _report(client, token, project["id"], slug, format="pdf")
        assert pdf.content[:5] == b"%PDF-"

    register_csv = _report(client, token, project["id"], "decision-register", format="csv").text
    assert "'=HYPERLINK" in register_csv and ",=HYPERLINK" not in register_csv

    log = _section(_report(client, token, project["id"], "decision-log"), "log")
    assert all(len(cell) <= 400 for row in log["rows"] for cell in (row[7], row[8], row[9]))


def test_catalogue_lists_all_four_reports_for_a_project_and_none_organisation_wide(client, admin_token):
    org, project, token = _setup(client, admin_token, "Catalogue Co")
    project_entries = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()
    mine = {e["slug"]: e for e in project_entries if e["module_key"] == MODULE_KEY}
    assert set(mine) == set(SLUGS)
    # The catalogue path is what the UI runs, so it must resolve to the real report route.
    for slug, entry in mine.items():
        assert entry["path"] == f"{_base(project['id'])}/reports/{slug}"
        assert client.get(entry["path"], headers=auth_headers(token)).status_code == 200
    assert {p["name"] for p in mine["approval-ageing"]["params"]} == {"overdue_days"}
    assert {p["name"] for p in mine["decision-register"]["params"]} == {
        "status", "decision_type", "date_from", "date_to", "include_archived",
    }

    org_entries = client.get(f"/api/v1/orgs/{org['id']}/report-catalogue", headers=auth_headers(token)).json()
    assert not [e for e in org_entries if e["module_key"] == MODULE_KEY]
    resp = client.get(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/reports/decision-register", headers=auth_headers(token))
    assert resp.status_code == 404
