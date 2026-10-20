"""Tests for the Stakeholders & Personas reports S1-S5, through the real HTTP endpoints.

Covers, per report: content, labels, filters and the gap tables. Cross-cutting:
access (non-member, other organisation and disabled module are 404), sub-component
gating, scope (child projects only when asked), hidden and Retired records never
counted, PDF/CSV output, the catalogue entries and the generated MCP tools. Every
test builds its own organisation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.registry import build_mcp_tool_manifest
from app.modules.stakeholders.tests.test_engagement_api import (
    _add_to_group,
    _create_need,
    _create_open_question,
    _engagements,
    _group,
)
from app.modules.stakeholders.tests.test_engagement_api import (
    _create as _create_engagement,
)
from app.modules.stakeholders.tests.test_persona_api import (
    MODULE_KEY,
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_relationship_api import _create_pain_point, _rels
from app.modules.stakeholders.tests.test_stakeholder_api import (
    _create_org_stakeholder,
    _create_project_stakeholder,
    _levels,
)
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

SLUGS = (
    "power-interest-grid", "persona-validation", "need-coverage", "engagement-staleness", "engagement-yield",
)


def _report(client, token, project_id, slug, expect=200, **params):
    resp = client.get(f"{_project_base(project_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def _col(section, column: str) -> list[str]:
    index = section["columns"].index(column)
    return [row[index] for row in section["rows"]]


def _metric(report, label: str):
    return next(m["value"] for m in report["metrics"] if m["label"] == label)


def _days_ago(n: int) -> str:
    """A date `n` days ago as the app sees it: reports are dated in UTC, not the host's timezone."""
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def _subcomponent(client, token, org_id, key: str, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}/subcomponents/{key}", json={"enabled": enabled}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _scored(client, token, org_id, project_id, influence: str | None, interest: str | None, **extra) -> dict:
    """A project Stakeholder rated by level name (Low/Medium/High); unset when `None`."""
    lv = _levels(client, token, org_id)
    body = dict(extra)
    if influence:
        body["influence_level_id"] = lv["influence"][influence]
    if interest:
        body["interest_level_id"] = lv["interest"][interest]
    return _create_project_stakeholder(client, token, project_id, **body)


def _log(client, token, project_id, days_ago: int = 0, **extra) -> dict:
    return _create_engagement(client, token, project_id, engagement_date=_days_ago(days_ago), **extra)


def _participate(client, token, project_id, engagement_id, stakeholder_id) -> None:
    resp = client.post(
        f"{_engagements(project_id)}/{engagement_id}/participants", json={"stakeholder_id": stakeholder_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def _cover(client, token, project_id, engagement_id, persona_id) -> None:
    resp = client.post(
        f"{_engagements(project_id)}/{engagement_id}/personas", json={"persona_id": persona_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def _requirements(client, token, project_id, *names) -> list[dict]:
    """Requirements with these names, sharing one component and category."""
    component_id, category_id = create_component_and_category(client, token, project_id)
    out = []
    for name in names:
        resp = client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        out.append(resp.json())
    return out


def _relate(client, token, project_id, holder_kind, holder_id, kind, target_type, target_id) -> None:
    resp = client.post(
        _rels(project_id, holder_kind, holder_id), json={"kind": kind, "target_type": target_type, "target_id": target_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


# --- S1 ---------------------------------------------------------------------------


def test_s1_places_stakeholders_in_quadrants_and_lists_the_unscored(client, admin_token):
    org, project, token = _setup(client, admin_token, "S1 Co")
    pid = project["id"]
    _scored(client, token, org["id"], pid, "High", "High", name="Sponsor")
    _scored(client, token, org["id"], pid, "High", "Low", name="Regulator")
    _scored(client, token, org["id"], pid, "Low", "High", name="End user")
    _scored(client, token, org["id"], pid, "Low", "Low", name="Bystander")
    _scored(client, token, org["id"], pid, "High", None, name="Half rated")
    report = _report(client, token, pid, "power-interest-grid")

    def names(key):
        return _col(_section(report, key), "Stakeholder")

    assert names("manage_closely") == ["Sponsor"] and names("keep_satisfied") == ["Regulator"]
    assert names("keep_informed") == ["End user"] and names("monitor") == ["Bystander"]
    assert names("unscored") == ["Half rated"] and _section(report, "unscored")["gap"] is True
    assert _section(report, "manage_closely")["title"] == "Manage closely"  # the label, never `manage_closely`
    sponsor = _section(report, "manage_closely")["rows"][0]
    assert sponsor[_section(report, "manage_closely")["columns"].index("Influence")] == "High"
    assert _metric(report, "Stakeholders") == 5 and _metric(report, "Not scored") == 1
    assert report["data"]["quadrants"]["manage_closely"][0]["name"] == "Sponsor"
    assert report["eligible_projects"] == 1


def test_s1_leaves_out_retired_archived_and_hidden_stakeholders(client, admin_token):
    org, project, token = _setup(client, admin_token, "S1 Hidden Co")
    pid = project["id"]
    h = auth_headers(token)
    base = _project_base(pid)
    keep = _scored(client, token, org["id"], pid, "High", "High", name="Kept")
    retired = _scored(client, token, org["id"], pid, "High", "High", name="Retired one")
    archived = _scored(client, token, org["id"], pid, "High", "High", name="Archived one")
    shared = _create_org_stakeholder(client, token, org["id"], name="Hidden shared")
    assert client.post(f"{base}/stakeholders/{retired['id']}/activate", headers=h).status_code == 200
    assert client.post(f"{base}/stakeholders/{retired['id']}/retire", json={"comment": ""}, headers=h).status_code == 200
    assert client.post(f"{base}/stakeholders/{archived['id']}/archive", headers=h).status_code == 200
    visible = _report(client, token, pid, "power-interest-grid")
    assert sorted(_col(_section(visible, "unscored"), "Stakeholder")) == ["Hidden shared"]
    assert client.put(f"{base}/stakeholders/{shared['id']}/visibility", json={"hidden": True}, headers=h).status_code == 200
    hidden = _report(client, token, pid, "power-interest-grid")
    assert _col(_section(hidden, "manage_closely"), "Stakeholder") == [keep["name"]]
    assert _metric(hidden, "Stakeholders") == 1


def test_s1_filters_by_group_and_arranges_by_branch(client, admin_token):
    org, project, token = _setup(client, admin_token, "S1 Group Co")
    pid = project["id"]
    acme = _group(client, token, pid, "Acme")
    emea = _group(client, token, pid, "EMEA", parent=acme["id"])
    apac = _group(client, token, pid, "APAC", parent=acme["id"])
    other = _group(client, token, pid, "Other")
    ann = _scored(client, token, org["id"], pid, "High", "High", name="Ann")
    bob = _scored(client, token, org["id"], pid, "High", "High", name="Bob")
    cat = _scored(client, token, org["id"], pid, "High", "High", name="Cat")
    for group, person in ((emea, ann), (apac, bob), (other, cat)):
        _add_to_group(client, token, pid, group["id"], person["id"])

    def grid(**params):
        return _report(client, token, pid, "power-interest-grid", **params)

    assert sorted(_col(_section(grid(group_id=acme["id"]), "manage_closely"), "Stakeholder")) == ["Ann", "Bob"]  # descendants included
    assert _col(_section(grid(group_id=emea["id"]), "manage_closely"), "Stakeholder") == ["Ann"]
    arranged = _section(grid(group_by=acme["id"]), "manage_closely")
    assert _col(arranged, "Stakeholder") == ["Bob", "Ann", "Cat"]  # APAC, EMEA, then the one outside Acme
    assert _col(arranged, "Branch") == ["APAC", "EMEA", ""]
    assert "Branch" not in _section(grid(), "manage_closely")["columns"]
    _report(client, token, pid, "power-interest-grid", expect=404, group_id="00000000-0000-0000-0000-000000000001")
    _report(client, token, pid, "power-interest-grid", expect=400, group_by=emea["id"])  # not a top-level group


def test_a_group_the_project_cannot_see_is_refused_not_ignored(client, admin_token):
    org, project, token = _setup(client, admin_token, "S1 Foreign Group Co")
    sibling = create_project(client, token, org["id"], "S1 Foreign Sibling")
    _, other_project, other_token = _setup(client, admin_token, "S1 Foreign Other Co")
    sibling_group = _group(client, token, sibling["id"], "Sibling only")
    foreign_group = _group(client, other_token, other_project["id"], "Other org")
    for slug in ("power-interest-grid", "engagement-staleness"):
        for group in (sibling_group, foreign_group):
            _report(client, token, project["id"], slug, expect=404, group_id=group["id"])
            _report(client, token, project["id"], slug, expect=400, group_by=group["id"])


# --- S2 ---------------------------------------------------------------------------


def test_s2_shows_each_personas_evidence_and_flags_assumptions(client, admin_token):
    org, project, token = _setup(client, admin_token, "S2 Co")
    pid = project["id"]
    h = auth_headers(token)
    _subcomponent(client, token, org["id"], "research_extras", True)
    backed = _create_project_persona(client, token, pid, name="Technician", weight=3)
    assumed = _create_org_persona(client, token, org["id"], name="Planner")
    tagged = _create_project_persona(client, token, pid, name="Manager")
    person = _create_project_stakeholder(client, token, pid, name="Tara")
    assert client.post(f"{_project_base(pid)}/stakeholders/{person['id']}/personas", json={"persona_id": backed["id"]}, headers=h).status_code == 201
    covered = _log(client, token, pid, 3)
    _cover(client, token, pid, covered["id"], backed["id"])
    assert client.post(f"{_engagements(pid)}/{covered['id']}/findings", json={"title": "Slow"}, headers=h).status_code == 201
    anon = _log(client, token, pid, 2)
    assert client.post(
        f"{_engagements(pid)}/{anon['id']}/anonymous-participants", json={"label": "P1", "persona_id": tagged["id"]}, headers=h,
    ).status_code == 201
    future = _log(client, token, pid, -5)  # planned, so not evidence yet
    _cover(client, token, pid, future["id"], assumed["id"])

    report = _report(client, token, pid, "persona-validation")
    evidence = _section(report, "evidence")
    row = {r[1]: dict(zip(evidence["columns"], r, strict=True)) for r in evidence["rows"]}
    assert row["Technician"]["Evidence"] == "Evidenced" and row["Technician"]["Linked stakeholders"] == "Tara"
    assert row["Technician"]["Engagements"] == "1" and row["Technician"]["Findings"] == "1"
    assert row["Technician"]["Weight"] == "3" and row["Technician"]["Last engagement"] == _days_ago(3)
    assert row["Manager"]["Anonymous participants"] == "1" and row["Manager"]["Evidence"] == "Evidenced"
    assert row["Planner"]["Evidence"] == "Assumption" and row["Planner"]["Weight"] == "Equal (not set)"
    assert _col(_section(report, "assumptions"), "Persona") == ["Planner"]
    assert _metric(report, "Personas") == 3 and _metric(report, "Assumptions") == 1

    _subcomponent(client, token, org["id"], "research_extras", False)  # extras off: the tagged persona loses its evidence
    off = {r[1]: r for r in _section(_report(client, token, pid, "persona-validation"), "evidence")["rows"]}
    assert off["Manager"][evidence["columns"].index("Evidence")] == "Assumption"


# --- S3 ---------------------------------------------------------------------------


def test_s3_lists_needs_without_requirements_and_requirements_without_an_origin(client, admin_token):
    org, project, token = _setup(client, admin_token, "S3 Co")
    pid = project["id"]
    h = auth_headers(token)
    served = _create_need(client, token, pid, name="Served need")
    _create_need(client, token, pid, name="Orphan need")
    from_need, from_person, only_approved, nobody = _requirements(
        client, token, pid, "From a need", "From a person", "Only approved by someone", "Nobody asked",
    )
    assert client.post(
        f"{_project_base(pid)}/needs/{served['id']}/requirements", json={"requirement_id": from_need["id"]}, headers=h,
    ).status_code == 201
    person = _create_project_stakeholder(client, token, pid, name="Pat")
    _relate(client, token, pid, "stakeholder", person["id"], "provides_requirement", "requirement", from_person["id"])
    _relate(client, token, pid, "stakeholder", person["id"], "approves", "requirement", only_approved["id"])
    assert client.post(
        f"{_project_base(pid)}/needs/{served['id']}/holders", json={"kind": "stakeholder", "id": person["id"]}, headers=h,
    ).status_code == 201

    report = _report(client, token, pid, "need-coverage")
    assert _col(_section(report, "needs_without_requirement"), "Need") == ["Orphan need"]
    untraced = _section(report, "requirements_without_origin")
    assert sorted(_col(untraced, "Requirement")) == sorted([only_approved["name"], nobody["name"]])
    assert set(_col(untraced, "Status")) == {"Draft"}  # the label
    assert _metric(report, "Active Needs") == 2 and _metric(report, "Needs with no Requirement") == 1
    assert _metric(report, "Requirements") == 4 and _metric(report, "Requirements with no origin") == 2

    # A Need that is retired stops being a gap.
    orphan_id = next(n["id"] for n in client.get(f"{_project_base(pid)}/needs", headers=h).json() if n["name"] == "Orphan need")
    assert client.post(f"{_project_base(pid)}/needs/{orphan_id}/activate", headers=h).status_code == 200
    assert client.post(f"{_project_base(pid)}/needs/{orphan_id}/retire", json={"comment": ""}, headers=h).status_code == 200
    assert _col(_section(_report(client, token, pid, "need-coverage"), "needs_without_requirement"), "Need") == []


def test_s3_does_not_count_a_stakeholder_hidden_from_the_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "S3 Hidden Co")
    pid = project["id"]
    h = auth_headers(token)
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared")
    (requirement,) = _requirements(client, token, pid, "Shared asked")
    _relate(client, token, pid, "stakeholder", shared["id"], "provides_requirement", "requirement", requirement["id"])
    assert _col(_section(_report(client, token, pid, "need-coverage"), "requirements_without_origin"), "Requirement") == []
    assert client.put(f"{_project_base(pid)}/stakeholders/{shared['id']}/visibility", json={"hidden": True}, headers=h).status_code == 200
    assert _col(_section(_report(client, token, pid, "need-coverage"), "requirements_without_origin"), "Requirement") == [
        "Shared asked",
    ]


# --- S4 ---------------------------------------------------------------------------


def test_s4_lists_overdue_stakeholders_by_influence_and_skips_one_off_and_ad_hoc(client, admin_token):
    org, project, token = _setup(client, admin_token, "S4 Co")
    pid = project["id"]
    fresh = _scored(client, token, org["id"], pid, "High", "High", name="Fresh", target_cadence="monthly")
    stale = _scored(client, token, org["id"], pid, "Low", "Low", name="Stale", target_cadence="monthly", availability_constraints="Only Fridays")
    never = _scored(client, token, org["id"], pid, "High", "High", name="Never", target_cadence="weekly")
    _scored(client, token, org["id"], pid, "High", "High", name="Once", target_cadence="one_off")
    _scored(client, token, org["id"], pid, "High", "High", name="Whenever", target_cadence="ad_hoc")
    none_set = _scored(client, token, org["id"], pid, "High", "High", name="Unset")
    planned = _scored(client, token, org["id"], pid, "High", "High", name="Planned only", target_cadence="weekly")
    h = auth_headers(token)
    assert client.put(f"{_project_base(pid)}/stakeholders/{none_set['id']}", json={"target_cadence": None}, headers=h).status_code == 200
    _participate(client, token, pid, _log(client, token, pid, 10)["id"], fresh["id"])
    _participate(client, token, pid, _log(client, token, pid, 70)["id"], stale["id"])
    _participate(client, token, pid, _log(client, token, pid, -3)["id"], planned["id"])  # future: not yet engaged

    report = _report(client, token, pid, "engagement-staleness")
    overdue = _section(report, "overdue")
    assert _col(overdue, "Stakeholder") == ["Never", "Planned only", "Stale"]  # High influence first, never-engaged before the rest
    by_name = {r[1]: dict(zip(overdue["columns"], r, strict=True)) for r in overdue["rows"]}
    assert by_name["Never"]["Overdue by"] == "Never engaged" and by_name["Never"]["Target cadence"] == "Weekly"
    assert by_name["Stale"]["Overdue by"] == "40 days" and by_name["Stale"]["Availability"] == "Only Fridays"
    assert by_name["Stale"]["Last engaged"] == _days_ago(70)
    no_cadence = _section(report, "no_cadence")
    assert _col(no_cadence, "Stakeholder") == ["Unset"] and _col(no_cadence, "Suggested cadence") == ["Monthly"]
    assert _metric(report, "Stakeholders tracked") == 4 and _metric(report, "One-off / ad hoc (excluded)") == 2
    assert _metric(report, "Overdue") == 3 and _metric(report, "No target cadence") == 1
    assert never["name"] not in _col(no_cadence, "Stakeholder")


def test_s4_lists_personas_not_engaged_inside_the_window(client, admin_token):
    org, project, token = _setup(client, admin_token, "S4 Persona Co")
    pid = project["id"]
    recent = _create_project_persona(client, token, pid, name="Recent")
    old = _create_project_persona(client, token, pid, name="Old", weight=2)
    _create_project_persona(client, token, pid, name="Never")
    _cover(client, token, pid, _log(client, token, pid, 20)["id"], recent["id"])
    _cover(client, token, pid, _log(client, token, pid, 200)["id"], old["id"])

    default = _section(_report(client, token, pid, "engagement-staleness"), "personas_not_engaged")
    assert _col(default, "Persona") == ["Old", "Never"]  # heavier weight first
    assert _col(default, "Last engagement")[0] == _days_ago(200)
    wide = _section(_report(client, token, pid, "engagement-staleness", persona_months=12), "personas_not_engaged")
    assert _col(wide, "Persona") == ["Never"]
    _report(client, token, pid, "engagement-staleness", expect=422, persona_months=0)


def test_s4_filters_by_group(client, admin_token):
    org, project, token = _setup(client, admin_token, "S4 Group Co")
    pid = project["id"]
    team = _group(client, token, pid, "Team")
    inside = _scored(client, token, org["id"], pid, "High", "High", name="Inside", target_cadence="weekly")
    _scored(client, token, org["id"], pid, "High", "High", name="Outside", target_cadence="weekly")
    _add_to_group(client, token, pid, team["id"], inside["id"])
    report = _report(client, token, pid, "engagement-staleness", group_id=team["id"])
    assert _col(_section(report, "overdue"), "Stakeholder") == ["Inside"]


# --- S5 ---------------------------------------------------------------------------


def test_s5_summarises_engagements_by_channel_persona_and_outcome(client, admin_token):
    org, project, token = _setup(client, admin_token, "S5 Co")
    pid = project["id"]
    h = auth_headers(token)
    _subcomponent(client, token, org["id"], "research_extras", True)
    persona = _create_project_persona(client, token, pid, name="Technician")
    pain = _create_pain_point(client, token, org["id"], pid)
    question = _create_open_question(client, token, org["id"], pid)
    need = _create_need(client, token, pid)
    person = _create_project_stakeholder(client, token, pid, name="Pat")
    interview = _log(client, token, pid, 5, channel="interview", title="Interview")
    survey = _log(client, token, pid, 4, channel="survey", title="Survey")
    _log(client, token, pid, 3, channel="interview", title="Fruitless chat")
    _log(client, token, pid, -4, channel="call", title="Planned call")  # future: not counted
    _participate(client, token, pid, interview["id"], person["id"])
    _cover(client, token, pid, interview["id"], persona["id"])
    url = f"{_engagements(pid)}/{interview['id']}"
    for kind, target_type, target in (("raised", "pain_point", pain), ("raised", "stakeholder_need", need), ("answered", "open_question", question)):
        assert client.post(
            url + "/outcomes", json={"kind": kind, "target_type": target_type, "target_id": target["id"]}, headers=h,
        ).status_code == 201
    assert client.post(
        f"{_engagements(pid)}/{survey['id']}/anonymous-participants", json={"label": "S1", "persona_id": persona["id"]}, headers=h,
    ).status_code == 201
    assert client.post(f"{_engagements(pid)}/{survey['id']}/findings", json={"title": "Wants offline"}, headers=h).status_code == 201

    report = _report(client, token, pid, "engagement-yield")
    yield_rows = dict(_section(report, "yield")["rows"])
    assert yield_rows["Engagements"] == "3" and yield_rows["Engagements that produced an outcome"] == "2"
    assert yield_rows["Pain Points raised"] == "1" and yield_rows["Needs raised"] == "1"
    assert yield_rows["Open Questions answered"] == "1" and yield_rows["Findings"] == "1"
    channels = {r[0]: r for r in _section(report, "by_channel")["rows"]}
    assert channels["Interview"][1:] == ["2", "1", "0"] and channels["Survey"][1:] == ["1", "0", "1"]
    assert "Call" not in channels
    persona_row = _section(report, "by_persona")["rows"][0]
    assert persona_row[1] == "Technician" and persona_row[3:6] == ["2", "1", "1"]
    assert _col(_section(report, "no_outcome"), "Engagement") == ["Fruitless chat"]
    assert _metric(report, "No outcome") == 1 and _metric(report, "Findings") == 1

    narrowed = _report(client, token, pid, "engagement-yield", since=_days_ago(4))
    assert dict(_section(narrowed, "yield")["rows"])["Engagements"] == "2"
    _subcomponent(client, token, org["id"], "research_extras", False)
    off = _report(client, token, pid, "engagement-yield")
    assert "Findings" not in dict(_section(off, "yield")["rows"]) and all(m["label"] != "Findings" for m in off["metrics"])
    # The survey's only yield was a finding, which is not counted while the extras are off.
    assert _col(_section(off, "no_outcome"), "Engagement") == ["Fruitless chat", "Survey"]


def test_s5_works_with_the_module_alone(client, admin_token):
    org, project, token = _setup(client, admin_token, "S5 Alone Co")
    for sub in ("persona", "stakeholder", "stakeholder_need"):
        _subcomponent(client, token, org["id"], sub, False)
    _log(client, token, project["id"], 1)
    report = _report(client, token, project["id"], "engagement-yield")
    assert report["eligible_projects"] == 1 and dict(_section(report, "yield")["rows"])["Engagements"] == "1"
    for slug in ("power-interest-grid", "persona-validation", "need-coverage", "engagement-staleness"):
        _report(client, token, project["id"], slug, expect=404)  # their own sub-component is off


# --- Cross-cutting ----------------------------------------------------------------


def test_reports_are_hidden_from_non_members_other_organisations_and_a_disabled_module(client, admin_token):
    org, project, token = _setup(client, admin_token, "Gate Co")
    _, _, other_token = _setup(client, admin_token, "Gate Other Co")
    org2, outsider = create_org_admin_in(client, admin_token, "Gate Outsider Co")
    off_project = create_project(client, outsider, org2["id"], "Off Project")
    _, member_token = _add_member(client, token, org["id"], project["id"], "gate-member@stakeholder-rep.example.com")
    for slug in SLUGS:
        _report(client, member_token, project["id"], slug)  # any project member may read
        _report(client, other_token, project["id"], slug, expect=404)
        _report(client, outsider, off_project["id"], slug, expect=404)  # module not enabled for that org


def test_include_children_adds_readable_children_with_the_module_on(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Children Co")
    parent = create_project(client, admin, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, admin, org["id"], "Child", parent_project_id=parent["id"])
    _scored(client, admin, org["id"], parent["id"], "High", "High", name="Parent person")
    _scored(client, admin, org["id"], child["id"], "High", "High", name="Child person")

    own = _report(client, admin, parent["id"], "power-interest-grid")
    assert _col(_section(own, "manage_closely"), "Stakeholder") == ["Parent person"]
    widened = _report(client, admin, parent["id"], "power-interest-grid", include_children=True)
    assert sorted(_col(_section(widened, "manage_closely"), "Stakeholder")) == ["Child person", "Parent person"]
    assert set(_col(_section(widened, "manage_closely"), "Project")) == {"Parent", "Child"} and widened["eligible_projects"] == 2

    resp = client.put(
        f"/api/v1/projects/{child['id']}/modules/{MODULE_KEY}/enablement", json={"enabled": False}, headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    off = _report(client, admin, parent["id"], "power-interest-grid", include_children=True)
    assert _col(_section(off, "manage_closely"), "Stakeholder") == ["Parent person"]
    assert _report(client, admin, parent["id"], "engagement-yield", include_children=True)["eligible_projects"] == 1


def test_one_projects_engagements_never_count_in_another(client, admin_token):
    org, project, token = _setup(client, admin_token, "Isolation Co")
    sibling = create_project(client, token, org["id"], "Isolation Sibling")
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared", target_cadence="weekly")
    _participate(client, token, sibling["id"], _log(client, token, sibling["id"], 1)["id"], shared["id"])
    report = _report(client, token, project["id"], "engagement-staleness")
    row = _section(report, "overdue")["rows"][0]
    assert row[0] == "IC-STK-001" and row[1] == "Shared" and row[_section(report, "overdue")["columns"].index("Overdue by")] == "Never engaged"
    assert dict(_section(_report(client, token, project["id"], "engagement-yield"), "yield")["rows"])["Engagements"] == "0"


def test_csv_and_pdf_render_for_every_report(client, admin_token):
    org, project, token = _setup(client, admin_token, "Render Co")
    pid = project["id"]
    _scored(client, token, org["id"], pid, "High", "High", name='=HYPERLINK("http://evil.example","x")', target_cadence="weekly")
    _scored(client, token, org["id"], pid, "Low", None, name="<img src='file:///etc/passwd'/> & <b>bold</b>", interests="word " * 5000)
    _create_project_persona(client, token, pid, name="Persona")
    _log(client, token, pid, 1)
    for slug in SLUGS:
        csv = _report(client, token, pid, slug, format="csv")
        assert csv.headers["content-type"].startswith("text/csv")
        assert _report(client, token, pid, slug, format="pdf").content[:5] == b"%PDF-"
    assert "'=HYPERLINK" in _report(client, token, pid, "power-interest-grid", format="csv").text


def test_catalogue_lists_the_five_project_reports_and_none_organisation_wide(client, admin_token):
    org, project, token = _setup(client, admin_token, "Catalogue Co")
    entries = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()
    mine = {e["slug"]: e for e in entries if e["module_key"] == MODULE_KEY}
    assert set(mine) == set(SLUGS)
    for slug, entry in mine.items():
        assert entry["path"] == f"{_project_base(project['id'])}/reports/{slug}"
        assert client.get(entry["path"], headers=auth_headers(token)).status_code == 200
    assert {p["name"] for p in mine["power-interest-grid"]["params"]} == {"group_id", "group_by"}
    assert {p["name"] for p in mine["engagement-staleness"]["params"]} == {"group_id", "group_by", "persona_months"}
    assert {p["name"] for p in mine["engagement-yield"]["params"]} == {"since"}
    org_entries = client.get(f"/api/v1/orgs/{org['id']}/report-catalogue", headers=auth_headers(token)).json()
    assert not [e for e in org_entries if e["module_key"] == MODULE_KEY]


def test_each_report_is_declared_as_a_read_only_mcp_tool():
    tools = {t.name: t for t in build_mcp_tool_manifest() if t.name.startswith("stakeholders_get_")}
    for slug in SLUGS:
        tool = tools[f"stakeholders_get_{slug.replace('-', '_')}_report"]
        assert tool.method == "GET" and not tool.mutates
    assert {p["name"] for p in tools["stakeholders_get_engagement_staleness_report"].params} >= {"project_id", "persona_months"}


def test_report_codes_qualify_organisation_owned_records_and_tags_are_listed(client, admin_token):
    """An organisation-owned Persona or Stakeholder is always named with the organisation's code (a bare `PER-001`
    would also match a project's own), a project-scoped one is bare unless the organisation enforces the project code,
    the viewer's preference never matters, and the Tags column carries the tags."""
    org, project, token = _setup(client, admin_token, "Codes Report Co")
    pid = project["id"]
    h = auth_headers(token)
    owned = _create_org_persona(client, token, org["id"], name="Shared persona")
    local = _create_project_persona(client, token, pid, name="Local persona")
    org_stakeholder = _create_org_stakeholder(client, token, org["id"], name="Shared person", target_cadence="weekly")
    assert client.put(
        f"/api/v1/projects/{pid}/artefacts/persona/{local['id']}/tags", json={"tags": ["Fieldwork"]}, headers=h,
    ).status_code == 200

    def codes(slug, section, column):
        found = _section(_report(client, token, pid, slug), section)
        return dict(zip(_col(found, column), _col(found, "Code"), strict=True)), found

    for preference in (False, True):
        assert client.patch("/api/v1/auth/me/preferences", json={"ui_preferences": {"show_project_code": preference}}, headers=h).status_code == 200
        personas, evidence = codes("persona-validation", "evidence", "Persona")
        assert personas == {"Shared persona": f"{org['code']}-PER-001", "Local persona": "PER-001"}
        assert dict(zip(_col(evidence, "Persona"), _col(evidence, "Tags"), strict=True)) == {"Shared persona": "", "Local persona": "Fieldwork"}
        assert codes("engagement-staleness", "overdue", "Stakeholder")[0] == {"Shared person": f"{org['code']}-STK-001"}
    assert org_stakeholder["unique_code"] == "STK-001" and owned["unique_code"] == "PER-001"

    body = {"kind": "alphanumeric", "min_length": 2, "max_length": 6, "assignment": "auto", "enforce_code_everywhere": True}
    assert client.put(f"/api/v1/orgs/{org['id']}/code-policy", json=body, headers=h).status_code == 200
    assert codes("persona-validation", "evidence", "Persona")[0] == {
        "Shared persona": f"{org['code']}-PER-001", "Local persona": f"{project['code']}-PER-001",
    }
    for slug in SLUGS:
        _report(client, token, pid, slug)
