"""Tests for the Product Feedback reports F1-F5 through the real HTTP endpoints: F1 Demand ranking, F2 Unlinked
requests, F3 Close the loop, F4 Triage ageing and F5 Problem demand.

Covers, per report: content, ordering, filters and the gap tables, and that each report reads the module's own
definitions (demand, links, the open loop). Cross-cutting: access (non-member, other organisation, disabled module
and a missing organisation role), the inbox rule (organisation-wide runs only, on request), that F3 names no
requester, the catalogue and the generated MCP tools. Every test builds its own organisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.modules.product_feedback.models import EnhancementRequestVersion
from app.modules.product_feedback.reports import REPORT_DEFINITIONS, collect_problem_demand
from app.modules.product_feedback.tests._helpers import (
    MODULE_KEY,
    add_link,
    add_member,
    add_requester,
    create_core_requirement,
    create_inbox_request,
    create_pain_point,
    create_request,
    create_stakeholder,
    enable_other_module,
    grant_org_role,
    mark_informed,
    org_base,
    project_base,
    setup_with_people,
    transition,
)
from app.modules.registry import build_mcp_tool_manifest
from app.services.report_framework import ReportContext
from tests.conftest import auth_headers, create_org_admin_in, create_project

SLUGS = ("demand-ranking", "unlinked-requests", "close-the-loop", "triage-ageing", "problem-demand")


def _report(client, token, project_id, slug, expect=200, **params):
    resp = client.get(f"{project_base(project_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _org_report(client, token, org_id, slug, expect=200, **params):
    resp = client.get(f"{org_base(org_id)}/reports/{slug}", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 200 and params.get("format", "json") == "json" else resp


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def _col(section, column: str) -> list[str]:
    index = section["columns"].index(column)
    return [row[index] for row in section["rows"]]


def _metric(report, label: str):
    return next(m["value"] for m in report["metrics"] if m["label"] == label)


def _world(client, admin_token, name: str):
    """An org with Product Feedback, People and Context & Strategy on, a project and its admin token."""
    org, project, token = setup_with_people(client, admin_token, name)
    enable_other_module(client, token, org["id"], "context_strategy")
    return org, project, token


def _ask(client, token, org, pid, request, *names) -> list[dict]:
    """Makes each named (new) stakeholder a requester of `request`."""
    people = [create_stakeholder(client, token, pid, name) for name in names]
    for person in people:
        assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", person["id"]).status_code == 201
    return people


def _scheme_levels(client, token, pid) -> dict[str, dict[str, str]]:
    scheme = client.get(project_base(pid) + "/scoring-scheme", headers=auth_headers(token)).json()
    return {a["key"]: {lv["name"]: lv["id"] for lv in a["levels"]} for a in scheme["axes"]}


def _levels(client, token, pid, **chosen) -> dict:
    """A `levels` payload from `axis=level name` choices."""
    available = _scheme_levels(client, token, pid)
    return {"levels": {axis: available[axis][name] for axis, name in chosen.items()}}


def test_f1_ranks_open_requests_by_weighted_demand_and_flags_those_with_no_problem(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F1 Co")
    pid, base = project["id"], project_base(project["id"])
    loud = create_request(client, token, pid, title="Loud ask")
    quiet = create_request(client, token, pid, title="Quiet ask")
    silent = create_request(client, token, pid, title="No asker")
    gone = create_request(client, token, pid, title="Declined ask")
    _ask(client, token, org, pid, loud, "Ann", "Bob")
    _ask(client, token, org, pid, quiet, "Cy")
    _ask(client, token, org, pid, gone, "Dee", "Eve", "Fay")
    pain = create_pain_point(client, token, pid)
    assert add_link(client, token, org["id"], pid, loud["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
    assert transition(client, token, base, gone["id"], "declined", "Not now").status_code == 200

    report = _report(client, token, pid, "demand-ranking")
    ranking = _section(report, "ranking")
    assert _col(ranking, "Request") == ["Loud ask", "Quiet ask", "No asker"]  # the declined request is not open
    assert _col(ranking, "Rank") == ["1", "2", "3"]
    assert _col(ranking, "Requesters") == ["2", "1", "0"]
    assert _col(ranking, "Weighted demand") == ["2", "1", "0"]
    assert _col(ranking, "Problem") == ["1 linked", "No Pain Point", "No Pain Point"]
    assert _col(ranking, "Code")[0] == loud["unique_code"]
    assert _col(ranking, "Status") == ["New", "New", "New"]
    assert _metric(report, "Open requests") == 3 and _metric(report, "No Pain Point linked") == 2
    assert _metric(report, "Total weighted demand") == "3"
    assert [i["title"] for i in report["data"]["items"]] == ["Loud ask", "Quiet ask", "No asker"]
    assert silent["id"] in {i["id"] for i in report["data"]["items"]}


def test_f1_scores_under_a_model_lists_unscored_requests_after_scored_ones_and_can_rank_by_score(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F1 Score Co")
    pid = project["id"]
    scored = create_request(
        client, token, pid, title="Scored",
        **_levels(client, token, pid, reach="Many", impact="High", confidence="High", effort="Small"),
    )
    unscored = create_request(client, token, pid, title="Unscored")
    _ask(client, token, org, pid, unscored, "Ann", "Bob", "Cy")  # more demand than the scored one

    by_demand = _section(_report(client, token, pid, "demand-ranking", scoring_model="rice"), "ranking")
    assert _col(by_demand, "Request") == ["Unscored", "Scored"]
    assert _col(by_demand, "Score")[0] == "Not scored" and _col(by_demand, "Score")[1].endswith("%")

    by_score = _report(client, token, pid, "demand-ranking", scoring_model="rice", rank_by="score")
    assert _col(_section(by_score, "ranking"), "Request") == ["Scored", "Unscored"]  # a missing score is never zero
    assert _metric(by_score, "Not scored") == 1
    assert by_score["data"]["scoring_model"] and any("Scored under" in n for n in by_score["notes"])
    assert scored["id"] == by_score["data"]["items"][0]["id"]

    ice = _report(client, token, pid, "demand-ranking", scoring_model="ice")  # ICE needs Ease, which neither has
    assert set(_col(_section(ice, "ranking"), "Score")) == {"Not scored"}
    _report(client, token, pid, "demand-ranking", expect=400, scoring_model="no-such-model")


def test_f1_leaves_out_archived_requests_and_merged_duplicates(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F1 Hidden Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    canonical = create_request(client, token, pid, title="Canonical")
    duplicate = create_request(client, token, pid, title="Duplicate")
    archived = create_request(client, token, pid, title="Archived")
    _ask(client, token, org, pid, duplicate, "Ann")
    assert client.post(f"{base}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h).status_code == 200
    assert client.post(f"{base}/requests/{archived['id']}/archive", headers=h).status_code == 200

    ranking = _section(_report(client, token, pid, "demand-ranking"), "ranking")
    assert _col(ranking, "Request") == ["Canonical"]
    assert _col(ranking, "Weighted demand") == ["1"]  # the duplicate's requester is the canonical request's demand
    assert archived["id"] not in {i["id"] for i in _report(client, token, pid, "demand-ranking")["data"]["items"]}


def test_the_inbox_is_listed_only_by_an_organisation_wide_run_that_asks_for_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Inbox Co")
    pid = project["id"]
    create_request(client, token, pid, title="Project ask")
    inbox = create_inbox_request(client, token, org["id"], title="Inbox ask")

    assert _col(_section(_report(client, token, pid, "demand-ranking", include_inbox="true"), "ranking"), "Request") == ["Project ask"]
    plain = _org_report(client, token, org["id"], "demand-ranking")
    assert _col(_section(plain, "ranking"), "Request") == ["Project ask"]

    wide = _org_report(client, token, org["id"], "demand-ranking", include_inbox="true")
    ranking = _section(wide, "ranking")
    assert sorted(_col(ranking, "Request")) == ["Inbox ask", "Project ask"]
    row = ranking["rows"][_col(ranking, "Request").index("Inbox ask")]
    assert row[ranking["columns"].index("Project")] == "Inbox" and row[ranking["columns"].index("Problem")] == "Inbox"
    assert row[ranking["columns"].index("Code")].startswith(org["code"] + "-")  # an organisation-owned code is qualified
    assert _metric(wide, "No Pain Point linked") == 1  # the inbox request cannot be linked, so it is not flagged
    assert inbox["id"] in {i["id"] for i in wide["data"]["items"]}

    off = client.put(
        f"{org_base(org['id'])}/subcomponents/organization_requests", json={"enabled": False}, headers=auth_headers(token),
    )
    assert off.status_code == 200
    assert _col(_section(_org_report(client, token, org["id"], "demand-ranking", include_inbox="true"), "ranking"), "Request") == ["Project ask"]


def test_f2_lists_requests_with_no_pain_point_loudest_first(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F2 Co")
    pid, base = project["id"], project_base(project["id"])
    linked = create_request(client, token, pid, title="Has a problem")
    loud = create_request(client, token, pid, title="Loud, no problem")
    quiet = create_request(client, token, pid, title="Quiet, no problem")
    done = create_request(client, token, pid, title="Delivered, no problem")
    _ask(client, token, org, pid, loud, "Ann", "Bob")
    pain = create_pain_point(client, token, pid)
    assert add_link(client, token, org["id"], pid, linked["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
    requirement = create_core_requirement(client, token, pid)
    assert add_link(client, token, org["id"], pid, quiet["id"], "Realised by", "requirement", requirement["id"]).status_code == 201
    for status in ("under_review", "accepted", "delivered"):
        assert transition(client, token, base, done["id"], status).status_code == 200

    report = _report(client, token, pid, "unlinked-requests")
    table = _section(report, "unlinked")
    assert _col(table, "Request") == ["Loud, no problem", "Quiet, no problem"]
    assert _col(table, "Weighted demand") == ["2", "0"] and _col(table, "Requirements") == ["0", "1"]
    assert _metric(report, "No Pain Point linked") == 2 and _metric(report, "Of which realised by a Requirement") == 1
    assert _metric(report, "Demand with no problem") == "2"
    assert table["rows"][0][table["columns"].index("Age (days)")] == "0"

    with_closed = _section(_report(client, token, pid, "unlinked-requests", include_closed="true"), "unlinked")
    assert "Delivered, no problem" in _col(with_closed, "Request")


def test_f3_lists_requests_with_requesters_still_to_tell_and_names_no_one(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F3 Co")
    pid, base = project["id"], project_base(project["id"])
    request = create_request(client, token, pid, title="Shipped ask")
    declined = create_request(client, token, pid, title="Declined ask")
    open_one = create_request(client, token, pid, title="Still open")
    ann, bob = _ask(client, token, org, pid, request, "Zelda Quill", "Yosef Brandt")
    _ask(client, token, org, pid, declined, "Xena Marsh")
    _ask(client, token, org, pid, open_one, "Wim Hart")
    for status in ("under_review", "accepted", "delivered"):
        assert transition(client, token, base, request["id"], status).status_code == 200
    assert transition(client, token, base, declined["id"], "declined", "Out of scope").status_code == 200

    report = _report(client, token, pid, "close-the-loop")
    table = _section(report, "open_loops")
    assert _col(table, "Request") == ["Shipped ask", "Declined ask"]  # by project, then code
    by_title = dict(zip(_col(table, "Request"), table["rows"], strict=True))
    shipped = by_title["Shipped ask"]
    assert shipped[table["columns"].index("To tell")] == "2" and shipped[table["columns"].index("Told")] == "0"
    assert by_title["Declined ask"][table["columns"].index("Decline reason")] == "Out of scope"
    assert _metric(report, "Requesters still to tell") == 3 and _metric(report, "Requests with an open loop") == 2
    for name in ("Zelda Quill", "Yosef Brandt", "Xena Marsh", "Wim Hart"):
        assert name not in str(report)  # requesters are personal data: counts only

    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])]).status_code == 200
    after = _section(_report(client, token, pid, "close-the-loop"), "open_loops")
    shipped = dict(zip(_col(after, "Request"), after["rows"], strict=True))["Shipped ask"]
    assert shipped[after["columns"].index("To tell")] == "1" and shipped[after["columns"].index("Told")] == "1"

    assert mark_informed(client, token, pid, request["id"], [("stakeholder", bob["id"])]).status_code == 200
    assert "Shipped ask" not in _col(_section(_report(client, token, pid, "close-the-loop"), "open_loops"), "Request")


def test_f4_counts_from_when_the_request_entered_its_status_and_an_edit_does_not_restart_the_clock(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F4 Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    old = create_request(client, token, pid, title="Waiting a month")
    fresh = create_request(client, token, pid, title="Just arrived")
    decided = create_request(client, token, pid, title="Already decided")
    assert transition(client, token, base, decided["id"], "under_review").status_code == 200
    assert transition(client, token, base, decided["id"], "accepted").status_code == 200
    assert client.put(f"{base}/requests/{old['id']}", json={"description": "Edited later"}, headers=h).status_code == 200
    with SessionLocal() as db:
        first = db.scalar(select(EnhancementRequestVersion).where(
            EnhancementRequestVersion.request_id == old["id"], EnhancementRequestVersion.version_number == 1,
        ))
        assert first is not None
        first.valid_from = datetime.now(UTC) - timedelta(days=30)
        db.commit()

    report = _report(client, token, pid, "triage-ageing")
    table = _section(report, "waiting")
    assert _col(table, "Request") == ["Waiting a month"]  # the default threshold is 14 days
    assert _col(table, "Days waiting") == ["30"] and _col(table, "Status") == ["New"]
    assert _metric(report, "Awaiting a decision") == 2 and _metric(report, "Over 14 days") == 1 and _metric(report, "Oldest (days)") == 30

    zero = _report(client, token, pid, "triage-ageing", older_than_days=0)
    assert _col(_section(zero, "waiting"), "Request") == ["Waiting a month"]  # "more than 0 days": a request of today is not
    assert fresh["id"] not in {i["id"] for i in zero["data"]["items"]}
    summary = _section(report, "by_status")
    assert _col(summary, "Status") == ["New", "Under review"] and _col(summary, "Requests") == ["2", "0"]
    _report(client, token, pid, "triage-ageing", expect=422, older_than_days=-1)


def test_f4_can_include_the_inbox_in_an_organisation_wide_run(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F4 Inbox Co")
    inbox = create_inbox_request(client, token, org["id"], title="Old inbox ask")
    with SessionLocal() as db:
        version = db.scalar(select(EnhancementRequestVersion).where(EnhancementRequestVersion.request_id == inbox["id"]))
        assert version is not None
        version.valid_from = datetime.now(UTC) - timedelta(days=40)
        db.commit()
    assert _col(_section(_org_report(client, token, org["id"], "triage-ageing"), "waiting"), "Request") == []
    wide = _org_report(client, token, org["id"], "triage-ageing", include_inbox="true")
    assert _col(_section(wide, "waiting"), "Request") == ["Old inbox ask"] and _col(_section(wide, "waiting"), "Days waiting") == ["40"]


def test_f5_counts_requests_and_distinct_requesters_per_pain_point_and_whether_a_requirement_exists(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback F5 Co")
    pid, base = project["id"], project_base(project["id"])
    popular = create_pain_point(client, token, pid, title="Popular problem")
    lonely = create_pain_point(client, token, pid, title="Lonely problem")
    create_pain_point(client, token, pid, title="Unasked problem")
    first = create_request(client, token, pid, title="First fix")
    second = create_request(client, token, pid, title="Second fix")
    refused = create_request(client, token, pid, title="Refused fix")
    shared = create_stakeholder(client, token, pid, "Shared Asker")
    for request in (first, second):
        assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", shared["id"]).status_code == 201
    _ask(client, token, org, pid, second, "Other Asker")
    _ask(client, token, org, pid, refused, "Ignored Asker")
    for request in (first, second, refused):
        assert add_link(client, token, org["id"], pid, request["id"], "Addresses", "pain_point", popular["id"]).status_code == 201
    assert add_link(client, token, org["id"], pid, refused["id"], "Addresses", "pain_point", lonely["id"]).status_code == 201
    assert transition(client, token, base, refused["id"], "declined", "No").status_code == 200

    report = _report(client, token, pid, "problem-demand")
    table = _section(report, "problems")
    rows = {row[0].split(" ", 1)[-1]: dict(zip(table["columns"], row, strict=True)) for row in table["rows"]}
    assert set(rows) == {"Popular problem"}  # a problem only a declined request addresses, and one nobody addresses, are absent
    popular_row = rows["Popular problem"]
    assert (popular_row["Requests"], popular_row["Requesters"], popular_row["Weighted demand"]) == ("2", "2", "2")
    assert popular_row["Requirement"] == "None yet" and popular_row["Open"] == "2"
    assert _metric(report, "Pain Points asked for") == 1 and _metric(report, "With no Requirement yet") == 1

    requirement = create_core_requirement(client, token, pid)
    assert add_link(client, token, org["id"], pid, first["id"], "Realised by", "requirement", requirement["id"]).status_code == 201
    after = _section(_report(client, token, pid, "problem-demand"), "problems")
    assert _col(after, "Requirement") == ["Yes"]


def test_reports_are_hidden_from_non_members_other_organisations_a_disabled_module_and_users_without_the_role(client, admin_token):
    org, project, admin = _world(client, admin_token, "Feedback Report Access Co")
    other_org, other_token = create_org_admin_in(client, admin_token, "Feedback Report Other Co")
    member_id, member = add_member(client, admin, org["id"], project["id"], "member.reports@example.com")
    for slug in SLUGS:
        _report(client, other_token, project["id"], slug, expect=404)
        assert _report(client, member, project["id"], slug).get("title")
        _org_report(client, member, org["id"], slug, expect=403)  # the organisation-wide run needs the triager role
    grant_org_role(client, admin, org["id"], member_id, "org_feedback_triager")
    for slug in SLUGS:
        assert _org_report(client, member, org["id"], slug)["title"]
    off = create_project(client, other_token, other_org["id"], "Feedback Report Off Project")
    for slug in SLUGS:
        _report(client, other_token, off["id"], slug, expect=404)  # the module is not enabled for that organisation


def test_catalogue_lists_five_reports_at_both_levels_and_each_is_a_read_only_mcp_tool(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Catalogue Co")
    entries = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()
    mine = {e["slug"]: e for e in entries if e["module_key"] == MODULE_KEY}
    assert set(mine) == set(SLUGS)
    for slug, entry in mine.items():
        assert entry["path"] == f"{project_base(project['id'])}/reports/{slug}"
        assert client.get(entry["path"], headers=auth_headers(token)).status_code == 200
    assert {p["name"] for p in mine["demand-ranking"]["params"]} == {"rank_by", "scoring_model", "include_inbox"}
    assert {p["name"] for p in mine["triage-ageing"]["params"]} == {"older_than_days", "include_inbox"}
    org_entries = client.get(f"/api/v1/orgs/{org['id']}/report-catalogue", headers=auth_headers(token)).json()
    assert {e["slug"] for e in org_entries if e["module_key"] == MODULE_KEY} == set(SLUGS)

    tools = {t.name: t for t in build_mcp_tool_manifest() if t.name.startswith(f"{MODULE_KEY}_")}
    for slug in SLUGS:
        tool = tools[f"{MODULE_KEY}_get_{slug.replace('-', '_')}_report"]
        assert tool.method == "GET" and not tool.mutates


def test_csv_and_pdf_render_and_neutralise_formulas(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Render Co")
    pid = project["id"]
    create_request(client, token, pid, title='=HYPERLINK("http://evil.example","x")')
    for slug in SLUGS:
        csv = _report(client, token, pid, slug, format="csv")
        assert csv.headers["content-type"].startswith("text/csv")
        assert _report(client, token, pid, slug, format="pdf").content[:5] == b"%PDF-"
    assert "'=HYPERLINK" in _report(client, token, pid, "demand-ranking", format="csv").text


def test_every_table_a_report_produces_is_declared_as_an_embeddable_part(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Parts Co")
    create_request(client, token, project["id"], title="Anything")
    for definition in REPORT_DEFINITIONS:
        declared = {part.key for part in definition.parts}
        produced = {s["key"] for s in _report(client, token, project["id"], definition.slug)["sections"]}
        assert produced == declared, definition.slug


def test_f5_names_no_pain_point_when_the_viewer_cannot_be_shown_it(client, admin_token):
    """The report framework knows who runs a report; with no viewer (or one without `view` on Pain Points) F5 counts
    the Pain Points it withholds and names none."""
    org, project, token = _world(client, admin_token, "Feedback F5 Viewer Co")
    pid = project["id"]
    request = create_request(client, token, pid, title="A fix")
    pain = create_pain_point(client, token, pid, title="Secret problem")
    assert add_link(client, token, org["id"], pid, request["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
    assert "Secret problem" in str(_report(client, token, pid, "problem-demand")["sections"])

    with SessionLocal() as db:
        organization = db.get(Organization, uuid.UUID(org["id"]))
        stored = db.get(Project, uuid.UUID(pid))
        assert organization is not None and stored is not None
        ctx = ReportContext(module_key=MODULE_KEY, organization=organization, projects=[stored], root_project=stored)
        assert not ctx.can_view(db, "pain_point", stored.id)  # no viewer: fail closed
        result = collect_problem_demand(db, ctx)
    assert result.sections[0].rows == []
    assert any("not listed" in note and "permission" in note for note in result.notes)
    assert "Secret problem" not in str(result.sections) + str(result.data)
