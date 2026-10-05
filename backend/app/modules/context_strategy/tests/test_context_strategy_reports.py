"""Tests for the Context & Strategy reports R1–R9 (docs/plans/module-01-
context-and-strategy-plan.md Phase 12), through the real HTTP endpoints.

Covers, per report: content, gap detection and the sections the summary pack
re-lists. Cross-cutting: model and roll-up switching (R1), intentional-item
segregation (R1/R9), the Blocker flag surviving an average, the
organisation-reports role gate, exclusion of projects the caller cannot read,
include-child-projects scoping, cross-organisation isolation, a disabled
module being a 404, and PDF/CSV output (including CSV formula neutralising).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import update

from app.database import SessionLocal
from app.modules.context_strategy.enums import GuidingPrincipleStatus, StrategyStatus
from app.modules.context_strategy.models import GuidingPrincipleVersion, StrategyVersion
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

CS = "context_strategy"
SH = "stakeholders"


def _today() -> date:
    """The reports' own reference date (UTC), not the host's local date, which differs for part of each day."""
    return datetime.now(UTC).date()


def _cs(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{CS}"


def _org(org_id) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{CS}"


def _enable(client, token, org_id, module) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name):
    """Org (with admin), project (admin is its manager), Context & Strategy and Stakeholders on."""
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"], CS)
    _enable(client, token, org["id"], SH)
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _report(client, token, project_id, slug, expect=200, **params):
    resp = client.get(f"{_cs(project_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _org_report(client, token, org_id, slug, expect=200, **params):
    resp = client.get(f"{_org(org_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def _titles(section, column: str) -> list[str]:
    index = section["columns"].index(column)
    return [row[index] for row in section["rows"]]


def _levels(client, token, project_id) -> dict[str, dict[str, str]]:
    resp = client.get(f"/api/v1/projects/{project_id}/scoring-schemes/pain_point", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in resp.json()["axes"]}


def _persona(client, token, project_id, name, weight=None) -> str:
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/{SH}/personas",
        json={"name": name, "description": name, "weight": weight}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    act = client.post(f"/api/v1/projects/{project_id}/modules/{SH}/personas/{pid}/activate", headers=auth_headers(token))
    assert act.status_code == 200, act.text
    return pid


def _pain_point(client, token, project_id, title="Slow reports", **extra) -> dict:
    types = client.get(_cs(project_id) + "/pain-point-types", headers=auth_headers(token)).json()
    resp = client.post(
        _cs(project_id) + "/pain-points",
        json={"pain_point_type_id": types[0]["id"], "title": title, **extra}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _score(client, token, project_id, pp_id, levels, rows) -> None:
    """rows: [(persona_id|None, severity, frequency, confidence)]."""
    scores = [
        {
            "target_id": target,
            "severity_level_id": levels["severity"][sev] if sev else None,
            "frequency_level_id": levels["frequency"][freq] if freq else None,
            "confidence_level_id": levels["confidence"][conf] if conf else None,
        }
        for target, sev, freq, conf in rows
    ]
    resp = client.put(f"{_cs(project_id)}/pain-points/{pp_id}/scores", json={"scores": scores}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _scored_pain_point(client, token, project_id, levels, title, sev, freq, conf, **extra) -> dict:
    pp = _pain_point(client, token, project_id, title, **extra)
    _score(client, token, project_id, pp["id"], levels, [(None, sev, freq, conf)])
    return pp


def _transition(client, token, project_id, kind, item_id, *actions) -> None:
    for action in actions:
        resp = client.post(f"{_cs(project_id)}/{kind}/{item_id}/{action}", json={}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text


def _link(client, token, project_id, kind, item_id, link_kind, target_id) -> None:
    resp = client.post(
        f"{_cs(project_id)}/{kind}/{item_id}/relationships", json={"kind": link_kind, "target_id": target_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def _strategy(client, token, project_id, title="Lead the market") -> dict:
    resp = client.post(_cs(project_id) + "/strategies", json={"title": title, "objective": "Win"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _requirement(client, token, project_id, name="Access control") -> dict:
    component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    if project_id:
        resp = client.post(
            f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
            headers=auth_headers(org_admin_token),
        )
        assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _grant_org_role(client, org_admin_token, org_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles", json={"module_key": CS, "role_key": role_key},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text


# --- R1: Pain Point prioritisation ------------------------------------------------


def test_r1_group_data_carries_axis_levels_and_bands_for_the_matrix_view(client, admin_token):
    """The on-screen matrix needs each group's levels and rating bands (not just item rows)."""
    _, project, token = _setup(client, admin_token, "R1 Bands Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "Major constant", "Major", "Constant", "High")

    group = _report(client, token, pid, "pain-point-prioritisation")["data"]["groups"][0]

    assert [lvl["weight"] for lvl in group["severity_levels"]] == sorted(lvl["weight"] for lvl in group["severity_levels"])
    assert group["frequency_levels"]
    assert group["bands"], "the model's effective rating bands are included"
    assert set(group["bands"][0]) == {"label", "min_score", "tone"}


def test_r1_ranks_and_segregates_blockers_unscored_and_intentional(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Rank Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "Major constant", "Major", "Constant", "High")  # 16/20
    _scored_pain_point(client, token, pid, levels, "Blocker rare", "Blocker", "Rare", "High")  # 5/20
    _pain_point(client, token, pid, "Never scored")
    _scored_pain_point(client, token, pid, levels, "Deliberate limit", "Blocker", "Constant", "High", is_intentional=True)

    report = _report(client, token, pid, "pain-point-prioritisation")

    assert [g["model_key"] for g in report["data"]["groups"]] == ["sxfxc"]  # system default model
    assert _titles(_section(report, "ranking"), "Pain point") == ["Major constant", "Blocker rare"]
    assert _titles(_section(report, "ranking"), "Rank") == ["1", "2"]
    assert _titles(_section(report, "unscored"), "Pain point") == ["Never scored"]
    assert _titles(_section(report, "intentional"), "Pain point") == ["Deliberate limit"]
    # Only the unintentional Blocker is a fixable Blocker; it is listed though it ranks second.
    assert _titles(_section(report, "blockers"), "Pain point") == ["Blocker rare"]
    metrics = {m["label"]: m["value"] for m in report["metrics"]}
    assert metrics["Open Pain Points (excluding intentional)"] == 3 and metrics["Blockers"] == 1
    # The matrix places both scored fixable items by their worst persona.
    matrix = _section(report, "matrix")
    assert sum(int(cell.split()[0]) for row in matrix["rows"] for cell in row[2:] if cell) == 2


def test_r1_model_switch_reorders_and_unknown_model_is_400(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Model Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "Unsure but severe", "Major", "Frequent", "Low")  # sxf .6, sxfxc .3
    _scored_pain_point(client, token, pid, levels, "Certain and moderate", "Moderate", "Frequent", "High")  # .45, .45

    by_default = _report(client, token, pid, "pain-point-prioritisation")
    assert _titles(_section(by_default, "ranking"), "Pain point")[0] == "Certain and moderate"
    by_sxf = _report(client, token, pid, "pain-point-prioritisation", model_key="sxf")
    assert _titles(_section(by_sxf, "ranking"), "Pain point")[0] == "Unsure but severe"
    assert {g["model_key"] for g in by_sxf["data"]["groups"]} == {"sxf"}

    _report(client, token, pid, "pain-point-prioritisation", expect=400, model_key="nope")
    _report(client, token, pid, "pain-point-prioritisation", expect=400, rollup="nope")


def test_r1_rollup_methods_and_blocker_survives_average(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Rollup Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    heavy = _persona(client, token, pid, "Operator", weight=3)
    light = _persona(client, token, pid, "Visitor", weight=1)
    pp = _pain_point(client, token, pid, "Per persona")
    _score(client, token, pid, pp["id"], levels, [(heavy, "Blocker", "Constant", "High"), (light, "Minor", "Rare", "High")])

    def item(**params):
        report = _report(client, token, pid, "pain-point-prioritisation", model_key="sxf", **params)
        return report["data"]["groups"][0]["items"][0]

    assert item()["score"] == pytest.approx((3 * 1.0 + 1 * 0.1) / 4)  # weighted average (default)
    assert item(rollup="worst_case")["score"] == pytest.approx(1.0)
    assert item(rollup="average")["score"] == pytest.approx(0.55)
    # Whatever the roll-up, the Blocker persona is named.
    assert item(rollup="average")["is_blocker"] is True
    assert item()["blocker_personas"] == ["Operator"]
    breakdown = _report(client, token, pid, "pain-point-prioritisation")["sections"][-1]
    assert sorted(_titles(breakdown, "Persona")) == ["Operator", "Visitor"]


def test_r1_unscored_persona_excluded_not_zero(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Unscored Persona Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    scored = _persona(client, token, pid, "Scored")
    for name in ("Other A", "Other B"):
        _persona(client, token, pid, name)
    pp = _pain_point(client, token, pid)
    _score(client, token, pid, pp["id"], levels, [(scored, "Major", "Constant", "High")])
    item = _report(client, token, pid, "pain-point-prioritisation", model_key="sxf")["data"]["groups"][0]["items"][0]
    assert item["score"] == pytest.approx(0.8)  # one scored persona of three shows that persona's value


def test_r1_input_gap_shows_as_unscored_under_that_model(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Gap Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "No confidence", "Major", "Constant", None)
    sxf = _report(client, token, pid, "pain-point-prioritisation", model_key="sxf")
    sxfxc = _report(client, token, pid, "pain-point-prioritisation", model_key="sxfxc")
    assert _titles(_section(sxf, "ranking"), "Pain point") == ["No confidence"]
    assert _titles(_section(sxfxc, "unscored"), "Pain point") == ["No confidence"]


def test_r1_excludes_archived_and_finished_pain_points(client, admin_token):
    _, project, token = _setup(client, admin_token, "R1 Open Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    keep = _scored_pain_point(client, token, pid, levels, "Open", "Major", "Constant", "High")
    gone = _scored_pain_point(client, token, pid, levels, "Rejected", "Major", "Constant", "High")
    _transition(client, token, pid, "pain-points", gone["id"], "triage")
    reject = client.post(f"{_cs(pid)}/pain-points/{gone['id']}/reject", json={"comment": "No"}, headers=auth_headers(token))
    assert reject.status_code == 200, reject.text
    report = _report(client, token, pid, "pain-point-prioritisation")
    assert _titles(_section(report, "ranking"), "Pain point") == [keep["title"]]


# --- R2: Strategy cascade -----------------------------------------------------------


def test_r2_cascade_and_gaps(client, admin_token):
    org, project, token = _setup(client, admin_token, "R2 Cascade Co")
    pid = project["id"]
    org_strategy = client.post(
        _org(org["id"]) + "/strategies", json={"title": "Org growth", "objective": "Grow"}, headers=auth_headers(token),
    ).json()
    child = _strategy(client, token, pid, "Project growth")
    orphan = _strategy(client, token, pid, "Orphan strategy")
    _link(client, token, pid, "strategies", child["id"], "contributes_to_strategy", org_strategy["id"])
    requirement = _requirement(client, token, pid)
    _link(client, token, pid, "strategies", child["id"], "drives_requirement", requirement["id"])
    future_state = client.post(_cs(pid) + "/future-states", json={"title": "Aligned FS"}, headers=auth_headers(token)).json()
    _link(client, token, pid, "strategies", child["id"], "defines_future_state", future_state["id"])
    lonely = client.post(_cs(pid) + "/future-states", json={"title": "Lonely FS"}, headers=auth_headers(token)).json()
    _transition(client, token, pid, "strategies", orphan["id"], "propose", "submit-for-review", "approve", "activate")

    report = _report(client, token, pid, "strategy-cascade")

    rows = _section(report, "cascade")["rows"]
    labels = [(r[0], r[1].lstrip("— ")) for r in rows]
    assert labels[0] == ("Organisation Strategy", "Org growth")
    assert ("Project Strategy", "Project growth") in labels and ("Future State", "Aligned FS") in labels
    assert any(level == "Requirement" and "Access control" in title for level, title in labels)
    assert _titles(_section(report, "no_parent"), "Title") == ["Orphan strategy"]
    assert _titles(_section(report, "no_requirement"), "Title") == ["Orphan strategy"]  # Active, nothing implements it
    assert _titles(_section(report, "no_strategy"), "Title") == [lonely["title"]]


# --- R3: Pain Point coverage --------------------------------------------------------------


def test_r3_coverage_matrix_uncovered_and_ageing(client, admin_token):
    _, project, token = _setup(client, admin_token, "R3 Coverage Co")
    pid = project["id"]
    old = (_today() - timedelta(days=30)).isoformat()
    covered = _pain_point(client, token, pid, "Covered", date_identified=old)
    uncovered = _pain_point(client, token, pid, "Uncovered", date_identified=old)
    for pp in (covered, uncovered):
        _transition(client, token, pid, "pain-points", pp["id"], "triage", "accept")
    requirement = _requirement(client, token, pid)
    _link(client, token, pid, "pain-points", covered["id"], "motivates_requirement", requirement["id"])

    report = _report(client, token, pid, "pain-point-coverage")

    matrix = _section(report, "matrix")
    assert matrix["rows"][0][matrix["columns"].index("Accepted")] == "2" and matrix["rows"][0][-1] == "2"
    assert _titles(_section(report, "uncovered"), "Pain point") == ["Uncovered"]
    assert _titles(_section(report, "uncovered"), "Age (days)") == ["30"]
    linked = _section(report, "requirements")
    assert _titles(linked, "Pain point") == ["Covered"] and linked["rows"][0][3] == "Draft"
    assert {r[0]: r[4] for r in _section(report, "ageing")["rows"]} == {"Covered": "30", "Uncovered": "30"}


# --- R4: Open Question register -------------------------------------------------------------


def test_r4_overdue_unowned_and_resolved_excluded(client, admin_token):
    org, project, token = _setup(client, admin_token, "R4 Register Co")
    pid = project["id"]
    past = (_today() - timedelta(days=3)).isoformat()
    created = client.post(
        _cs(pid) + "/open-questions", json={"question": "Late?", "priority": "high", "due_date": past}, headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    owned = client.post(_cs(pid) + "/open-questions", json={"question": "Owned?", "priority": "low"}, headers=auth_headers(token)).json()
    done = client.post(_cs(pid) + "/open-questions", json={"question": "Done?"}, headers=auth_headers(token)).json()
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    upd = client.put(
        f"{_cs(pid)}/open-questions/{owned['id']}", json={"question": "Owned?", "priority": "low", "owner_id": me},
        headers=auth_headers(token),
    )
    assert upd.status_code == 200, upd.text
    _transition(client, token, pid, "open-questions", done["id"], "investigate", "mark-ready-for-decision")
    resolve = client.post(f"{_cs(pid)}/open-questions/{done['id']}/withdraw", json={"comment": "moot"}, headers=auth_headers(token))
    assert resolve.status_code == 200, resolve.text

    report = _report(client, token, pid, "open-question-register")

    assert _titles(_section(report, "open"), "Question") == ["Late?", "Owned?"]  # high priority first; withdrawn omitted
    assert _titles(_section(report, "overdue"), "Question") == ["Late?"]
    assert _titles(_section(report, "unowned"), "Question") == ["Late?"]
    by_owner = dict(_section(report, "by_owner")["rows"])
    assert by_owner["Unowned"] == "1" and sum(int(v) for v in by_owner.values()) == 2
    assert [i["is_overdue"] for i in report["data"]["items"]] == [True, False]


# --- R5: Future State roadmap -----------------------------------------------------------------


def test_r5_roadmap_order_overdue_and_missing_measures(client, admin_token):
    _, project, token = _setup(client, admin_token, "R5 Roadmap Co")
    pid = project["id"]
    past = (_today() - timedelta(days=10)).isoformat()
    soon = (_today() + timedelta(days=10)).isoformat()
    later = (_today() + timedelta(days=100)).isoformat()
    for title, target, measures in (
        ("Later", later, "Measured"), ("Missed", past, ""), ("Soon", soon, "Measured"), ("Undated", None, "Measured"),
    ):
        resp = client.post(
            _cs(pid) + "/future-states", json={"title": title, "target_date": target, "success_measures": measures},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text

    report = _report(client, token, pid, "future-state-roadmap")

    assert _titles(_section(report, "roadmap"), "Future State") == ["Missed", "Soon", "Later", "Undated"]
    assert _titles(_section(report, "overdue"), "Future State") == ["Missed"]
    assert _titles(_section(report, "no_measures"), "Future State") == ["Missed"]
    assert _section(report, "roadmap")["rows"][0][4] == "-10"


# --- R6: Guiding Principle usage ---------------------------------------------------------------


def test_r6_applied_vs_never_applied(client, admin_token):
    _, project, token = _setup(client, admin_token, "R6 Principles Co")
    pid = project["id"]
    used = client.post(_cs(pid) + "/guiding-principles", json={"name": "Used", "principle_statement": "s"}, headers=auth_headers(token)).json()
    unused = client.post(_cs(pid) + "/guiding-principles", json={"name": "Unused", "principle_statement": "s"}, headers=auth_headers(token)).json()
    draft = client.post(_cs(pid) + "/guiding-principles", json={"name": "Draft one", "principle_statement": "s"}, headers=auth_headers(token)).json()
    requirement = _requirement(client, token, pid)
    _link(client, token, pid, "guiding-principles", used["id"], "informs_requirement", requirement["id"])
    db = SessionLocal()
    try:
        for gp in (used, unused):
            db.execute(update(GuidingPrincipleVersion).where(
                GuidingPrincipleVersion.guiding_principle_id == gp["id"], GuidingPrincipleVersion.valid_to.is_(None),
            ).values(status=GuidingPrincipleStatus.ACTIVE))
        db.commit()
    finally:
        db.close()

    report = _report(client, token, pid, "guiding-principle-usage")

    register = _section(report, "register")
    assert _titles(register, "Principle") == ["Used", "Unused"]  # draft one is not Active
    assert _titles(register, "Linked Requirements") == ["1", "0"]
    assert _titles(_section(report, "unused"), "Principle") == ["Unused"]
    assert draft["name"] not in _titles(register, "Principle")


# --- R7: Change history ------------------------------------------------------------------------


def test_r7_history_status_moves_and_stale_active_items(client, admin_token):
    _, project, token = _setup(client, admin_token, "R7 History Co")
    pid = project["id"]
    strategy = _strategy(client, token, pid, "Aging strategy")
    _transition(client, token, pid, "strategies", strategy["id"], "propose", "submit-for-review", "approve", "activate")

    report = _report(client, token, pid, "strategy-change-history")
    history = _section(report, "history")
    assert "Proposed → Under review" in _titles(history, "Status change")
    assert _titles(_section(report, "stale"), "Title") == []  # just revised

    db = SessionLocal()
    try:
        db.execute(update(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy["id"], StrategyVersion.valid_to.is_(None),
        ).values(created_at=datetime.now(UTC) - timedelta(days=400)))
        db.commit()
        assert db.query(StrategyVersion).filter(StrategyVersion.strategy_id == strategy["id"]).count() >= 4
    finally:
        db.close()
    stale = _report(client, token, pid, "strategy-change-history")
    assert _titles(_section(stale, "stale"), "Title") == ["Aging strategy"]
    # `since` trims the history but not the stale check.
    recent = _report(client, token, pid, "strategy-change-history", since=_today().isoformat())
    assert len(_section(recent, "history")["rows"]) < len(_section(stale, "history")["rows"])
    assert _section(recent, "stale")["rows"]
    assert StrategyStatus.ACTIVE.value == "active"


# --- R8: Summary pack ---------------------------------------------------------------------------


def test_r8_project_summary_includes_gaps_and_org_summary_is_org_level_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "R8 Summary Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "Blocking", "Blocker", "Constant", "High")
    client.post(_cs(pid) + "/open-questions", json={"question": "Unowned?"}, headers=auth_headers(token))

    report = _report(client, token, pid, "summary")
    keys = [s["key"] for s in report["sections"]]
    assert keys[0] == "headline" and "r1_blockers" in keys and "r4_unowned" in keys and "r2_no_parent" in keys
    assert {"r1", "r2", "r3", "r4", "r5", "r6", "r7", "r9"} == set(report["data"]["included"])

    org_report = _org_report(client, token, org["id"], "summary")
    org_keys = {s["key"] for s in org_report["sections"]}
    assert "r1_blockers" in org_keys and not any(k.startswith(("r2_", "r5_", "r6_", "r7_")) for k in org_keys)
    assert set(org_report["data"]["included"]) == {"r1", "r3", "r4", "r9"}


def test_summary_omits_reports_whose_subcomponent_is_off(client, admin_token):
    org, project, token = _setup(client, admin_token, "R8 Subcomponent Co")
    pid = project["id"]
    resp = client.put(
        f"/api/v1/projects/{pid}/modules/{CS}/subcomponents/open_question", json={"enabled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert "r4" not in _report(client, token, pid, "summary")["data"]["included"]
    _report(client, token, pid, "open-question-register", expect=404)


# --- R9: Upgrade drivers -------------------------------------------------------------------------


def test_r9_intentional_only_with_churn_risk_and_tier_note(client, admin_token):
    _, project, token = _setup(client, admin_token, "R9 Drivers Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "Fixable", "Blocker", "Constant", "High")
    _scored_pain_point(client, token, pid, levels, "Pro-only export", "Minor", "Rare", "High", is_intentional=True)
    _scored_pain_point(client, token, pid, levels, "Hard paywall", "Major", "Constant", "High", is_intentional=True)

    report = _report(client, token, pid, "upgrade-drivers")

    drivers = _section(report, "drivers")
    assert _titles(drivers, "Pain point") == ["Hard paywall", "Pro-only export"]
    assert dict(zip(_titles(drivers, "Pain point"), _titles(drivers, "Assessment"), strict=True)) == {
        "Hard paywall": "Churn risk", "Pro-only export": "Upsell lever",
    }
    assert _titles(_section(report, "churn"), "Pain point") == ["Hard paywall"]
    assert any("Product Tiers" in n for n in report["notes"])
    assert set(_titles(drivers, "Introduced in tier")) == {""}


# --- Access, scoping and output ---------------------------------------------------------------------


def test_org_reports_need_the_role_and_org_admins_hold_it(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Org Gate Co")
    levels = _levels(client, admin, project["id"])
    _scored_pain_point(client, admin, project["id"], levels, "Visible", "Major", "Constant", "High")
    member_id, member = _member(client, admin, org["id"], project["id"], "gate_member@example.com")

    _org_report(client, member, org["id"], "pain-point-prioritisation", expect=403)
    for project_only in ("strategy-cascade", "future-state-roadmap", "guiding-principle-usage", "strategy-change-history"):
        _org_report(client, admin, org["id"], project_only, expect=404)
    report = _org_report(client, admin, org["id"], "pain-point-prioritisation")
    assert _titles(_section(report, "ranking"), "Pain point") == ["Visible"]

    _grant_org_role(client, admin, org["id"], member_id, "org_reports_viewer")
    granted = _org_report(client, member, org["id"], "pain-point-prioritisation")
    assert _titles(_section(granted, "ranking"), "Pain point") == ["Visible"]  # member is on the project


def test_org_report_silently_excludes_projects_the_caller_cannot_read(client, admin_token):
    org, first, admin = _setup(client, admin_token, "Org Scope Co")
    second = create_project(client, admin, org["id"], "Second Project")
    levels = _levels(client, admin, first["id"])
    _scored_pain_point(client, admin, first["id"], levels, "In first", "Major", "Constant", "High")
    _scored_pain_point(client, admin, second["id"], levels, "In second", "Major", "Constant", "High")
    viewer_id, viewer = _member(client, admin, org["id"], first["id"], "scope_viewer@example.com")
    _grant_org_role(client, admin, org["id"], viewer_id, "org_reports_viewer")

    everything = _org_report(client, admin, org["id"], "pain-point-prioritisation")
    assert sorted(_titles(_section(everything, "ranking"), "Pain point")) == ["In first", "In second"]
    restricted = _org_report(client, viewer, org["id"], "pain-point-prioritisation")
    assert _titles(_section(restricted, "ranking"), "Pain point") == ["In first"]
    assert "In second" not in str(restricted)


def test_org_reports_are_isolated_between_organisations(client, admin_token):
    org_a, project_a, admin_a = _setup(client, admin_token, "Iso A Co")
    org_b, project_b, admin_b = _setup(client, admin_token, "Iso B Co")
    levels = _levels(client, admin_a, project_a["id"])
    _scored_pain_point(client, admin_a, project_a["id"], levels, "Secret A", "Major", "Constant", "High")

    other = _org_report(client, admin_b, org_b["id"], "pain-point-prioritisation")
    assert "Secret A" not in str(other)
    assert other["data"]["groups"] == []
    # The other organisation's admin can't reach this organisation's reports at all.
    assert client.get(f"{_org(org_a['id'])}/reports/pain-point-prioritisation", headers=auth_headers(admin_b)).status_code in (403, 404)
    assert client.get(f"{_cs(project_a['id'])}/reports/pain-point-prioritisation", headers=auth_headers(admin_b)).status_code in (403, 404)
    assert project_b["id"] != project_a["id"]


def test_include_children_only_adds_readable_child_projects(client, admin_token):
    org, _, admin = _setup(client, admin_token, "Children Co")
    parent = create_project(client, admin, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, admin, org["id"], "Child", parent_project_id=parent["id"])
    levels = _levels(client, admin, parent["id"])
    _scored_pain_point(client, admin, parent["id"], levels, "Parent item", "Major", "Constant", "High")
    _scored_pain_point(client, admin, child["id"], levels, "Child item", "Major", "Constant", "High")

    default = _report(client, admin, parent["id"], "pain-point-prioritisation")
    assert _titles(_section(default, "ranking"), "Pain point") == ["Parent item"]
    widened = _report(client, admin, parent["id"], "pain-point-prioritisation", include_children=True)
    assert sorted(_titles(_section(widened, "ranking"), "Pain point")) == ["Child item", "Parent item"]

    _, parent_only = _member(client, admin, org["id"], parent["id"], "parent_only@example.com")
    limited = _report(client, parent_only, parent["id"], "pain-point-prioritisation", include_children=True)
    assert _titles(_section(limited, "ranking"), "Pain point") == ["Parent item"]


def test_project_report_needs_membership_and_enabled_module(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Gate Co")
    _, outsider = _member(client, admin, org["id"], None, "gate_outsider@example.com")
    _report(client, outsider, project["id"], "pain-point-prioritisation", expect=404)

    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{CS}", json={"enabled": False}, headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    _report(client, admin, project["id"], "pain-point-prioritisation", expect=404)
    _org_report(client, admin, org["id"], "pain-point-prioritisation", expect=404)


def test_pdf_and_csv_outputs_and_csv_formula_neutralised(client, admin_token):
    _, project, token = _setup(client, admin_token, "Formats Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    _scored_pain_point(client, token, pid, levels, "=HYPERLINK(\"http://x\")", "Major", "Constant", "High")
    _scored_pain_point(client, token, pid, levels, "<b>Markup</b> & more", "Minor", "Rare", "High")

    csv_resp = _report(client, token, pid, "pain-point-prioritisation", format="csv")
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in csv_resp.headers["content-disposition"]
    lines = csv_resp.text.splitlines()
    assert lines[0].startswith("Model,Rank,Pain point")
    assert any("'=HYPERLINK" in line for line in lines) and not any(",=HYPERLINK" in line for line in lines)

    for slug in ("pain-point-prioritisation", "summary", "strategy-cascade", "upgrade-drivers"):
        pdf = _report(client, token, pid, slug, format="pdf")
        assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


@pytest.mark.parametrize("slug", [
    "pain-point-prioritisation", "strategy-cascade", "pain-point-coverage", "open-question-register",
    "future-state-roadmap", "guiding-principle-usage", "strategy-change-history", "summary", "upgrade-drivers",
])
def test_every_report_renders_on_an_empty_project_in_every_format(client, admin_token, slug):
    _, project, token = _setup(client, admin_token, f"Empty {slug[:12]} Co")
    body = _report(client, token, project["id"], slug)
    assert body["sections"] and body["generated_at"]
    assert _report(client, token, project["id"], slug, format="csv").status_code == 200
    assert _report(client, token, project["id"], slug, format="pdf").content.startswith(b"%PDF")


def test_download_filename_survives_a_non_ascii_project_name(client, admin_token):
    """An em dash in the project name used to crash the response header with a 500."""
    org, token = create_org_admin_in(client, admin_token, "Unicode Name Co")
    _enable(client, token, org["id"], CS)
    project = create_project(client, token, org["id"], "Café — Prøject")
    for fmt in ("csv", "pdf"):
        resp = _report(client, token, project["id"], "summary", format=fmt)
        assert resp.status_code == 200
        assert f".{fmt}" in resp.headers["content-disposition"]
