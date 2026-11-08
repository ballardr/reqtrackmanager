"""Project overview widgets: layout validation, resolution (own, ancestor, organisation, built-in), who may read and
change it, the editor's catalogue, the batched metric endpoint (values, filters, dedupe, cap, time budget, failure
isolation, unavailable instead of zero), the module extension points, audit without titles, bundles and template clone.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import OverviewMetric, OverviewMetricValue, OverviewWidgetType
from app.services import overview_metrics, overview_widgets
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Overview Org", context_strategy=True)


def _layout_url(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/overview-layout"


def _metrics_url(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/overview-metrics"


def _org_layout_url(world: World) -> str:
    return f"/api/v1/orgs/{world.org['id']}/overview-layout"


def _headers(world: World) -> dict:
    return auth_headers(world.token)


def _widget(widget_id: str = "w1", widget_type: str = "metric_tile", **fields) -> dict:
    config = fields.pop("config", {"metric": "requirement_count"})
    return {"id": widget_id, "type": widget_type, "width": 3, "height": 2, "visible": True, "config": config, **fields}


def _put(world: World, project: dict, widgets: list[dict], token: str | None = None, scope: str = "this"):
    return world.client.put(
        _layout_url(project), json={"scope": scope, "widgets": widgets}, headers=auth_headers(token) if token else _headers(world),
    )


def _ask(world: World, project: dict, specs: list[dict], token: str | None = None):
    return world.client.post(
        _metrics_url(project), json={"metrics": specs}, headers=auth_headers(token) if token else _headers(world),
    )


def _spec(spec_id: str, metric: str, scope: str = "this", **params) -> dict:
    return {"id": spec_id, "metric": metric, "params": params, "scope": scope}


def _member_token(world: World, project: dict, role: str = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=_headers(world),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# --- layout ------------------------------------------------------------------------------------------


def test_a_project_with_no_layout_shows_the_built_in_one(world):
    project = world.project()
    body = world.client.get(_layout_url(project), headers=_headers(world)).json()
    assert body["source"] == "default" and body["inherited_source"] is None
    types = [w["type"] for w in body["widgets"]]
    assert types[:5] == ["metric_tile"] * 5
    assert {"record_totals", "stage_progress", "activity"} <= set(types) and "module_tiles" not in types
    # The built-in layout is itself a valid layout, so it can be saved as the project's own.
    assert overview_widgets.validate_layout({"scope": body["scope"], "widgets": body["widgets"]}) == {"scope": "this", "widgets": body["widgets"]}
    assert sum(w["width"] for w in body["widgets"][:5]) == 12


def test_a_manager_sets_and_restores_the_layout(world):
    project = world.project()
    saved = _put(world, project, [_widget("a"), _widget("b", "activity", config={"limit": 3}, width=12, title="  Latest   news ")])
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["source"] == "own" and body["inherited_source"] == "default"
    assert [w["id"] for w in body["widgets"]] == ["a", "b"]
    assert body["widgets"][1]["title"] == "Latest news"
    restored = world.client.delete(_layout_url(project), headers=_headers(world)).json()
    assert restored["source"] == "default" and len(restored["widgets"]) == 11


def test_an_empty_layout_is_a_layout_and_does_not_fall_back(world):
    project = world.project()
    assert _put(world, project, []).json() == {
        "scope": "this", "widgets": [], "source": "own", "inherited_source": "default", "can_customise": True,
    }


@pytest.mark.parametrize("widgets", [
    [_widget("a", "nonsense")],
    [_widget("a", width=13)],
    [_widget("a", width=0)],
    [_widget("a", width=True)],
    [_widget("a", height=13)],
    [_widget("a", height=0)],
    [_widget("a", scope="everywhere")],
    [_widget("a", "stage_progress", config={}, scope="children")],
    [_widget("a", "activity", config={}, scope="both")],
    [_widget("a", "text", config={"markdown": 5})],
    [_widget("a", "text", config={"markdown": "x" * 4001})],
    [_widget("a", "text", config={"markdown": "ok", "html": "<b>"})],
    [_widget("a"), _widget("a")],
    [_widget("bad id")],
    [_widget("a", title="x" * 200)],
    [_widget("a", config={"metric": "no_such_metric"})],
    [_widget("a", config={"metric": "requirements_by_status"})],
    [_widget("a", "status_chart", config={"metric": "requirement_count"})],
    [_widget("a", config={"metric": "requirement_count", "params": {"surprise": 1}})],
    [_widget("a", config={"metric": "record_count", "params": {"record_type": "no_such_type"}})],
    [_widget("a", config={"metric": "record_count", "params": {"record_type": "requirement", "filters": {"password": ["x"]}}})],
    [_widget("a", "gauge", config={"metric": "requirement_count", "minimum": 5, "maximum": 5})],
    [_widget("a", "gauge", config={"metric": "requirement_count", "maximum": "ten"})],
    [_widget("a", "gauge", config={"metric": "requirement_count", "direction": "sideways"})],
    [_widget("a", "activity", config={"limit": 0})],
    [_widget("a", "activity", config={"limit": 26})],
    [_widget("a", "stage_progress", config={"anything": 1})],
    [_widget("a", "status_chart", config={"metric": "requirements_by_status", "chart": "donut"})],
])
def test_an_invalid_layout_is_refused(world, widgets):
    project = world.project()
    assert _put(world, project, widgets).status_code == 422


def test_more_than_the_cap_is_refused(world):
    project = world.project()
    assert _put(world, project, [_widget(f"w{i}") for i in range(24)]).status_code == 200
    assert _put(world, project, [_widget(f"w{i}") for i in range(25)]).status_code == 422


def test_a_gauge_keeps_its_levels(world):
    project = world.project()
    body = _put(world, project, [_widget("g", "gauge", config={
        "metric": "requirement_completed_percent", "minimum": 0, "maximum": 100, "warning": 40, "critical": 20, "direction": "below",
    })]).json()
    assert body["widgets"][0]["config"] == {
        "metric": "requirement_completed_percent", "minimum": 0.0, "maximum": 100.0, "warning": 40.0, "critical": 20.0, "direction": "below",
    }


def test_a_module_widget_type_is_valid_only_while_its_module_is_registered(world, monkeypatch):
    project = world.project()
    assert _put(world, project, [_widget("m", "demo:heat", config={"x": 1})]).status_code == 422
    demo = {"demo:heat": ("decisions", OverviewWidgetType("Heat", "A heat map."))}
    monkeypatch.setattr(overview_widgets, "get_overview_widget_types", lambda: demo)
    assert _put(world, project, [_widget("m", "demo:heat", config={"x": 1})]).status_code == 200
    assert _put(world, project, [_widget("m", "demo:heat", config={"x": "y" * 5000})]).status_code == 422


def test_resolution_is_project_then_ancestor_then_organisation_then_built_in(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    headers = _headers(world)
    org_layout = [_widget("org-tile", config={"metric": "file_count"})]
    assert world.client.put(_org_layout_url(world), json={"widgets": org_layout}, headers=headers).status_code == 200
    assert world.client.get(_layout_url(child), headers=headers).json()["source"] == "organisation"

    _put(world, parent, [_widget("parent-tile")])
    seen = world.client.get(_layout_url(child), headers=headers).json()
    assert (seen["source"], [w["id"] for w in seen["widgets"]]) == ("ancestor", ["parent-tile"])

    _put(world, child, [_widget("child-tile")])
    own = world.client.get(_layout_url(child), headers=headers).json()
    assert (own["source"], own["inherited_source"], [w["id"] for w in own["widgets"]]) == ("own", "ancestor", ["child-tile"])

    world.client.delete(_layout_url(child), headers=headers)
    world.client.delete(_layout_url(parent), headers=headers)
    world.client.delete(_org_layout_url(world), headers=headers)
    assert world.client.get(_layout_url(child), headers=headers).json()["source"] == "default"


def test_only_managers_change_the_layout_and_only_org_admins_the_default(world):
    project = world.project()
    member = _member_token(world, project)
    seen = world.client.get(_layout_url(project), headers=auth_headers(member))
    assert seen.status_code == 200 and seen.json()["can_customise"] is False
    assert world.client.get(_layout_url(project), headers=_headers(world)).json()["can_customise"] is True
    assert _put(world, project, [_widget()], member).status_code == 403
    assert world.client.delete(_layout_url(project), headers=auth_headers(member)).status_code == 403
    assert world.client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=auth_headers(member)).status_code == 403
    assert world.client.get(_org_layout_url(world), headers=auth_headers(member)).status_code == 403
    assert world.client.put(_org_layout_url(world), json={"widgets": []}, headers=auth_headers(member)).status_code == 403
    assert _ask(world, project, [_spec("a", "requirement_count")], token=member).status_code == 200


def test_a_member_can_still_read_a_templates_overview(world):
    """The figures are fetched with a POST that only reads, so the template guard must not refuse it."""
    project = world.project("Overview template")
    member = _member_token(world, project)
    world.client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=_headers(world))
    assert _ask(world, project, [_spec("a", "requirement_count")], token=member).status_code == 200
    assert world.client.get(_layout_url(project), headers=auth_headers(member)).status_code == 200
    assert _put(world, project, [_widget()], member).status_code == 403


def test_another_organisation_cannot_read_or_change_a_layout(client, admin_token, world):
    other = World(client, admin_token, "Overview Other")
    project = world.project()
    headers = auth_headers(other.token)
    assert client.get(_layout_url(project), headers=headers).status_code in (403, 404)
    assert client.put(_layout_url(project), json={"widgets": []}, headers=headers).status_code in (403, 404)
    assert client.post(_metrics_url(project), json={"metrics": []}, headers=headers).status_code in (403, 404)
    assert client.get(_org_layout_url(world), headers=headers).status_code == 403


def test_changes_are_audited_with_counts_and_types_and_never_titles(world):
    project = world.project()
    _put(world, project, [_widget("a", title="Secretive heading"), _widget("b", "activity", config={})])
    world.client.delete(_layout_url(project), headers=_headers(world))
    with SessionLocal() as db:
        details = [e.detail for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "overview_layout")).all()
                   if e.entity_id == project["id"]]
    assert {"count": 2, "types": ["activity", "metric_tile"], "scope": "this"} in details and {"count": 0, "restored": True} in details
    assert "Secretive" not in json.dumps(details)


# --- catalogue ---------------------------------------------------------------------------------------


def test_the_catalogue_offers_what_the_project_can_use(world):
    project = world.project()
    body = world.client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=_headers(world)).json()
    core_types = {"metric_tile", "gauge", "status_chart", "stage_progress", "record_totals", "activity", "text"}
    assert core_types <= {t["key"] for t in body["widget_types"]}
    metrics = {m["key"]: m for m in body["metrics"]}
    assert metrics["requirement_count"]["scalar"] and not metrics["requirement_count"]["breakdown"]
    assert metrics["requirements_by_status"]["breakdown"] and not metrics["requirements_by_status"]["scalar"]
    assert metrics["record_count"]["params"] == ["filters", "record_type"]
    types = {t["type"]: t for t in body["record_types"]}
    assert "requirement" in types and PAIN in types
    assert "component_id" in types["requirement"]["filter_params"]
    assert body["max_widgets"] == 24


def test_the_catalogue_omits_a_module_that_is_off_for_the_organisation(client, admin_token):
    plain = World(client, admin_token, "Overview Plain")
    project = plain.project()
    body = client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=_headers(plain)).json()
    assert PAIN not in {t["type"] for t in body["record_types"]}
    org_body = client.get(f"/api/v1/orgs/{plain.org['id']}/overview-catalogue", headers=_headers(plain)).json()
    assert PAIN not in {t["type"] for t in org_body["record_types"]} and "requirement" in {t["type"] for t in org_body["record_types"]}


# --- metrics -----------------------------------------------------------------------------------------


def test_core_metrics_match_the_records(world):
    project = world.project()
    world.requirement(project, "One")
    world.requirement(project, "Two")
    body = _ask(world, project, [
        _spec("n", "requirement_count"), _spec("p", "requirement_completed_percent"), _spec("s", "requirements_by_status"),
        _spec("c", "change_requests_by_outcome"), _spec("g", "stage_progress"), _spec("t", "records_by_type"),
    ]).json()
    results = body["results"]
    assert results["n"] == {"state": "ok", "unit": "count", "label": "Requirements", "projects": 1, "value": 2.0, "breakdown": None}
    assert results["p"]["value"] == 0.0 and results["p"]["unit"] == "percent"
    assert sum(r["value"] for r in results["s"]["breakdown"]) == 2
    assert [r["key"] for r in results["c"]["breakdown"]] == ["active", "approved", "rejected"]
    assert results["g"]["breakdown"][0]["detail"]
    assert {r["key"]: r["value"] for r in results["t"]["breakdown"]}["requirement"] == 2 and results["t"]["value"] >= 2


def test_the_metrics_endpoint_agrees_with_the_existing_project_metrics(world):
    project = world.project()
    world.requirement(project)
    old = world.client.get(f"/api/v1/projects/{project['id']}/metrics", headers=_headers(world)).json()
    new = _ask(world, project, [_spec("n", "requirement_count"), _spec("f", "file_count"), _spec("stage", "stage_progress")]).json()["results"]
    assert new["n"]["value"] == old["requirement_count"] and new["f"]["value"] == old["file_count"]
    assert [(r["key"], r["value"], r["detail"]) for r in new["stage"]["breakdown"]] == [
        (s["stage_id"], s["completed_percent"], s["phase_name"]) for s in old["stage_progress"]
    ]


def test_a_record_count_applies_the_list_filters(world):
    project = world.project()
    first = (PAIN, world.pain_point(project, "First"))
    world.pain_point(project, "Second")
    third = (PAIN, world.pain_point(project, "Third"))
    base = f"/api/v1/projects/{project['id']}/artefacts"
    world.client.put(f"{base}/{first[0]}/{first[1]}/tags", json={"tags": ["urgent"]}, headers=_headers(world))
    world.client.put(f"{base}/{third[0]}/{third[1]}/tags", json={"tags": ["urgent", "later"]}, headers=_headers(world))
    place = {"component_id": project["component_id"], "category_id": project["category_id"]}
    world.client.put(f"{base}/{first[0]}/{first[1]}/placements", json={"placements": [place]}, headers=_headers(world))

    def count(**filters) -> float:
        spec = _spec("x", "record_count", record_type=PAIN, filters=filters)
        result = _ask(world, project, [spec]).json()["results"]["x"]
        assert result["state"] == "ok", result
        return result["value"]

    assert count() == 3
    assert count(tag=["urgent"]) == 2
    assert count(tag=["urgent", "later"], tag_mode=["all"]) == 1
    assert count(tag=["urgent", "later"], tag_mode=["any"]) == 2
    assert count(component=["SW"]) == 1
    assert count(category=["SW/PERF"]) == 1
    assert count(component=["NOPE"]) == 0
    assert count(component=["SW"], tag=["later"]) == 0


def test_a_requirement_count_uses_the_requirement_list_filters(world):
    project = world.project()
    world.requirement(project)
    world.requirement(project)
    result = _ask(world, project, [_spec("x", "record_count", record_type="requirement", filters={"component": ["SW"]})]).json()["results"]["x"]
    assert result["value"] == 2
    result = _ask(world, project, [_spec("x", "record_count", record_type="requirement", filters={"is_completed": ["true"]})]).json()["results"]["x"]
    assert result["value"] == 0


def test_an_unlisted_filter_or_setting_is_refused_before_any_figure_is_computed(world):
    project = world.project()
    assert _ask(world, project, [_spec("x", "record_count", record_type="requirement", filters={"password": ["x"]})]).status_code == 422
    assert _ask(world, project, [_spec("x", "requirement_count", extra=1)]).status_code == 422
    assert _ask(world, project, [_spec("x", "no_such_metric")]).status_code == 422
    assert _ask(world, project, [_spec("x", "record_count", record_type="requirement", filters={"tag_mode": ["sometimes"]})]).status_code == 422


def test_a_type_the_caller_cannot_read_is_unavailable_not_zero(client, admin_token):
    plain = World(client, admin_token, "Overview Hidden")
    project = plain.project()
    plain.requirement(project)
    result = client.post(
        _metrics_url(project), json={"metrics": [_spec("x", "record_count", record_type=PAIN)]}, headers=_headers(plain),
    ).json()["results"]["x"]
    assert result == {"state": "unavailable", "unit": "count", "label": "Pain points", "projects": 1, "value": None, "breakdown": None}


def test_identical_requests_are_evaluated_once_and_the_batch_is_capped(world, monkeypatch):
    project = world.project()
    calls: list[str] = []

    def counting(ctx, params):
        calls.append("hit")
        return OverviewMetricValue(value=7.0)

    real = overview_metrics.core_metrics()
    monkeypatch.setattr(overview_metrics, "core_metrics", lambda: {**real, "requirement_count": OverviewMetric("Requirements", "count", counting)})
    body = _ask(world, project, [_spec("a", "requirement_count"), _spec("b", "requirement_count")]).json()["results"]
    assert (body["a"]["value"], body["b"]["value"], len(calls)) == (7.0, 7.0, 1)

    too_many = [_spec(f"m{i}", "requirement_count") for i in range(25)]
    assert world.client.post(_metrics_url(project), json={"metrics": too_many}, headers=_headers(world)).status_code == 422
    assert _ask(world, project, [_spec("a", "requirement_count"), _spec("a", "requirement_count")]).status_code == 422


def test_a_slow_batch_reports_timeouts_and_a_failing_metric_does_not_blank_the_rest(world, monkeypatch):
    project = world.project()

    def failing(ctx, params):
        raise RuntimeError("boom")

    real = overview_metrics.core_metrics()
    monkeypatch.setattr(overview_metrics, "core_metrics", lambda: {**real, "file_count": OverviewMetric("Files", "count", failing)})
    body = _ask(world, project, [_spec("bad", "file_count"), _spec("ok", "requirement_count")]).json()["results"]
    assert body["bad"]["state"] == "error" and "boom" not in json.dumps(body)
    assert body["ok"]["state"] == "ok"

    monkeypatch.setattr(overview_metrics, "TIME_BUDGET_SECONDS", -1.0)
    late = _ask(world, project, [_spec("a", "requirement_count")]).json()["results"]["a"]
    assert late["state"] == "timeout" and late["value"] is None


def test_a_module_metric_is_offered_and_evaluated_only_while_its_module_is_enabled(client, admin_token, monkeypatch):
    plain = World(client, admin_token, "Overview Module")
    project = plain.project()
    metric = OverviewMetric("Open decisions", "count", lambda ctx, params: OverviewMetricValue(value=3.0))
    monkeypatch.setattr(overview_metrics, "get_overview_metrics", lambda: {"decisions:open": ("decisions", metric)})
    catalogue = client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=_headers(plain)).json()
    assert "decisions:open" not in {m["key"] for m in catalogue["metrics"]}
    assert _put(plain, project, [_widget("d", config={"metric": "decisions:open"})]).status_code == 200  # a layout may name it

    off = client.post(_metrics_url(project), json={"metrics": [_spec("x", "decisions:open")]}, headers=_headers(plain)).json()["results"]["x"]
    assert off["state"] == "unavailable"
    plain.enable("decisions")
    on = client.post(_metrics_url(project), json={"metrics": [_spec("x", "decisions:open")]}, headers=_headers(plain)).json()["results"]["x"]
    assert (on["state"], on["value"]) == ("ok", 3.0)


# --- bundles and templates ---------------------------------------------------------------------------


def _import_project(world: World, content: bytes, name: str) -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=_headers(world),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_the_project_bundle_round_trips_the_layout_and_an_unknown_metric_is_skipped_with_a_warning(world):
    project = world.project()
    layout = [
        _widget("tiles", config={"metric": "record_count", "params": {"record_type": PAIN, "filters": {"tag": ["urgent"], "component": ["SW"]}}}),
        _widget("act", "activity", config={"limit": 5}, width=12, title="News"),
    ]
    assert _put(world, project, layout).status_code == 200
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=_headers(world))
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert json.loads(archive.read("project.json"))["overview_widgets"]["widgets"][0]["config"]["params"]["filters"]["component"] == ["SW"]

    imported = _import_project(world, export.content, "Layout copy")
    body = world.client.get(_layout_url(imported["project"]), headers=_headers(world)).json()
    assert body["source"] == "own" and [w["id"] for w in body["widgets"]] == ["tiles", "act"]
    assert body["widgets"][0]["config"]["params"]["filters"] == {"tag": ["urgent"], "component": ["SW"]}

    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(export.content)) as source, zipfile.ZipFile(rewritten, "w") as target:
        for entry in source.namelist():
            data = source.read(entry)
            if entry == "project.json":
                content = json.loads(data)
                content["overview_widgets"]["widgets"][0]["config"] = {"metric": "gone_module:figure"}
                data = json.dumps(content).encode()
            target.writestr(entry, data)
    again = _import_project(world, rewritten.getvalue(), "Layout copy two")
    assert any("overview layout" in w for w in again["warnings"])
    assert world.client.get(_layout_url(again["project"]), headers=_headers(world)).json()["source"] == "default"


def test_a_project_without_its_own_layout_exports_none_and_imports_inheriting(world):
    project = world.project()
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=_headers(world))
    assert json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))["overview_widgets"] is None
    imported = _import_project(world, export.content, "Inheriting copy")
    assert world.client.get(_layout_url(imported["project"]), headers=_headers(world)).json()["source"] == "default"


def test_the_organisation_bundle_round_trips_the_default_layout(world, admin_token):
    layout = [_widget("only", config={"metric": "file_count"})]
    world.client.put(_org_layout_url(world), json={"widgets": layout}, headers=_headers(world))
    export = world.client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=_headers(world))
    assert json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))["overview_widgets"]["widgets"][0]["id"] == "only"
    imported = world.client.post(
        "/api/v1/orgs/import", data={"name": "Overview defaults copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        stored = db.get(Organization, imported.json()["organization"]["id"]).overview_widgets
    assert stored is not None and [w["id"] for w in stored["widgets"]] == ["only"]


def test_a_template_clone_copies_the_layout(world):
    template = world.project("Layout template")
    kept = {"metric": "record_count", "params": {"record_type": PAIN, "filters": {"component": ["SW"]}}}
    assert _put(world, template, [_widget("kept", config=kept)]).status_code == 200
    world.client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=_headers(world))
    cloned = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From layout template", "summary": "", "template_project_id": template["id"]},
        headers=_headers(world),
    )
    assert cloned.status_code == 201, cloned.text
    body = world.client.get(_layout_url(cloned.json()), headers=_headers(world)).json()
    assert (body["source"], [w["id"] for w in body["widgets"]]) == ("own", ["kept"])
    # The component named by prefix resolves in the clone's own tree, so the same widget counts there.
    assert body["widgets"][0]["config"]["params"]["filters"]["component"] == ["SW"]


# --- scope, size and the text widget -----------------------------------------------------------------


def test_the_overview_has_a_scope_and_a_widget_may_override_it(world):
    project = world.project()
    saved = _put(world, project, [_widget("a", scope="children"), _widget("b")], scope="both").json()
    assert saved["scope"] == "both"
    assert [w["scope"] for w in saved["widgets"]] == ["children", None]
    assert _put(world, project, [_widget("a")], scope="sideways").status_code == 422
    # The default and a layout saved without a scope are `this`.
    assert world.client.get(_layout_url(world.project("Other")), headers=_headers(world)).json()["scope"] == "this"
    assert world.client.put(_layout_url(project), json={"widgets": []}, headers=_headers(world)).json()["scope"] == "this"


def test_a_widget_keeps_its_size_and_defaults_it(world):
    project = world.project()
    body = _put(world, project, [_widget("a", width=12, height=12), {"id": "b", "type": "activity", "config": {}}]).json()
    assert [(w["width"], w["height"]) for w in body["widgets"]] == [(12, 12), (3, 2)]


def test_a_text_widget_keeps_its_markdown_as_plain_text(world):
    project = world.project()
    text = "## Release notes\n\n- one **bold** point\n- [a link](https://example.com)\n\n\ttabbed"
    body = _put(world, project, [_widget("n", "text", config={"markdown": text}, title="Notes")]).json()
    assert body["widgets"][0]["config"] == {"markdown": text}
    assert _put(world, project, [_widget("n", "text", config={"markdown": "bad\x00char"})]).status_code == 422
    # A text widget asks for no figure, so it is a valid layout entry with nothing to evaluate.
    assert _ask(world, project, []).json() == {"results": {}}


def test_each_figure_is_read_in_its_own_scope(world):
    parent = world.project("Scope parent")
    child = world.project("Scope child", parent=parent)
    world.requirement(parent, "Parent one")
    world.requirement(child, "Child one")
    world.requirement(child, "Child two")
    results = _ask(world, parent, [
        _spec("own", "requirement_count"), _spec("kids", "requirement_count", scope="children"),
        _spec("up", "requirement_count", scope="parents"),
        _spec("kids_records", "record_count", scope="children", record_type="requirement"),
    ]).json()["results"]
    assert (results["own"]["value"], results["own"]["projects"]) == (1.0, 1)
    assert (results["kids"]["value"], results["kids"]["projects"]) == (3.0, 2)
    assert (results["up"]["value"], results["up"]["projects"]) == (1.0, 1)
    assert results["kids_records"]["value"] == 3.0
    # The same figure in two scopes is two figures: each is evaluated once.
    assert _ask(world, parent, [_spec("a", "requirement_count"), _spec("b", "requirement_count", scope="children")]).status_code == 200
    assert world.client.post(
        _metrics_url(parent), json={"metrics": [{"id": "x", "metric": "requirement_count", "scope": "sideways"}]}, headers=_headers(world),
    ).status_code == 422


def test_a_scope_never_widens_to_a_project_the_caller_cannot_open(world):
    parent = world.project("Hidden parent")
    child = world.project("Hidden child", parent=parent)
    world.requirement(child, "Secret child requirement")
    member = _member_token(world, parent)
    seen = _ask(world, parent, [_spec("kids", "requirement_count", scope="children")], token=member).json()["results"]["kids"]
    assert (seen["value"], seen["projects"]) == (0.0, 1)


def test_a_stored_bare_list_is_read_as_a_layout_with_scope_this(world):
    project = world.project()
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.overview_widgets = [{"id": "old", "type": "metric_tile", "title": None, "width": 2, "visible": True, "config": {"metric": "file_count"}}]
        db.commit()
    body = world.client.get(_layout_url(project), headers=_headers(world)).json()
    assert body["scope"] == "this" and body["source"] == "own"
    assert [(w["id"], w["width"], w["height"]) for w in body["widgets"]] == [("old", 6, 2)]


# --- module widgets in the built-in layout -------------------------------------------------------------


def test_an_enabled_modules_widget_is_in_the_built_in_layout_and_moves_like_any_other(client, admin_token):
    plain = World(client, admin_token, "Overview Compliance")  # Compliance is on by default
    project = plain.project()
    body = client.get(_layout_url(project), headers=_headers(plain)).json()
    ids = [w["id"] for w in body["widgets"]]
    assert "compliance-standards_status" in ids and "module_tiles" not in [w["type"] for w in body["widgets"]]
    # It sits after the five key tiles, before the charts, and has a size like any widget.
    assert ids.index("compliance-standards_status") == 5
    compliance = body["widgets"][5]
    assert (compliance["type"], compliance["width"], compliance["height"]) == ("compliance:standards_status", 12, 2)
    # It is an ordinary widget: it can be saved anywhere in the layout, resized, hidden or removed.
    moved = [w for w in body["widgets"] if w["id"] != "compliance-standards_status"]
    moved.insert(len(moved), {**compliance, "width": 6, "visible": False})
    saved = client.put(_layout_url(project), json={"scope": "this", "widgets": moved}, headers=_headers(plain)).json()
    assert saved["widgets"][-1]["id"] == "compliance-standards_status" and saved["widgets"][-1]["visible"] is False
    # The editor offers it with the size a new one starts with.
    catalogue = client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=_headers(plain)).json()
    offered = next(t for t in catalogue["widget_types"] if t["key"] == "compliance:standards_status")
    assert (offered["module_key"], offered["width"], offered["height"]) == ("compliance", 12, 2)


def test_a_module_that_is_off_adds_nothing_to_the_built_in_layout(client, admin_token):
    plain = World(client, admin_token, "Overview No Compliance")
    plain_headers = _headers(plain)
    off = client.put(f"/api/v1/orgs/{plain.org['id']}/modules/compliance", json={"enabled": False}, headers=plain_headers)
    assert off.status_code == 200, off.text
    project = plain.project()
    types = [w["type"] for w in client.get(_layout_url(project), headers=plain_headers).json()["widgets"]]
    assert "compliance:standards_status" not in types
    assert len(types) == 10
    org_types = [w["type"] for w in client.get(_org_layout_url(plain), headers=plain_headers).json()["widgets"]]
    assert "compliance:standards_status" not in org_types
