"""Tests for organisation dashboards: the built-in Overview page, extra pages, who may see and change them, the
organisation widget catalogue and its figures, and that a restricted page is hidden on every route (list, read and
metrics) and stays restricted when a group that restricts it is deleted."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    login,
)


@pytest.fixture
def world(client, admin_token):
    """An organisation with an administrator, two plain members and a project; returns a dict of tokens and ids."""
    org, admin = create_org_admin_in(client, admin_token, "Dashboards Org")
    first_id = create_org_user(client, admin_token, org["id"], "dash_first@example.com")
    second_id = create_org_user(client, admin_token, org["id"], "dash_second@example.com")
    create_project(client, admin, org["id"], "Dash Project")
    return {
        "org": org["id"], "admin": admin, "first_id": first_id, "second_id": second_id,
        "first": login(client, "dash_first@example.com", "Password123!"),
        "second": login(client, "dash_second@example.com", "Password123!"),
    }


def _get(client, token, path):
    return client.get(f"/api/v1/orgs/{path}", headers=auth_headers(token))


def _send(client, method, token, path, body=None):
    return client.request(method, f"/api/v1/orgs/{path}", json=body, headers=auth_headers(token))


def _tile(metric="org_project_count", widget_id="w1", **extra):
    return {"id": widget_id, "type": "metric_tile", "width": 3, "height": 2, "config": {"metric": metric}, **extra}


# --- the built-in page ----------------------------------------------------------------------------


def test_the_built_in_overview_page_exists_for_every_member_with_the_four_headline_tiles(client, world):
    org = world["org"]
    pages = _get(client, world["first"], f"{org}/dashboards").json()
    assert [(p["id"], p["name"], p["is_default"], p["can_manage"]) for p in pages] == [("overview", "Overview", True, False)]
    page = _get(client, world["first"], f"{org}/dashboards/overview").json()
    assert page["built_in"] is True
    # The four headline tiles, then the widgets enabled modules ask to be on the built-in page.
    assert [w["config"]["metric"] for w in page["widgets"] if w["type"] == "metric_tile"] == [
        "org_project_count", "org_requirement_count", "org_member_count", "org_file_storage",
    ]
    assert any(w["type"] == "compliance:summary" for w in page["widgets"])


def test_editing_the_built_in_page_stores_it_and_restoring_returns_the_built_in_layout(client, world):
    org, admin = world["org"], world["admin"]
    saved = _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [_tile()]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["built_in"] is False and [w["id"] for w in saved.json()["widgets"]] == ["w1"]
    assert _get(client, world["first"], f"{org}/dashboards/overview").json()["widgets"][0]["id"] == "w1"
    restored = _send(client, "DELETE", admin, f"{org}/dashboards/overview/layout")
    assert restored.json()["built_in"] is True and "w1" not in [w["id"] for w in restored.json()["widgets"]]
    assert len(_get(client, world["first"], f"{org}/dashboards").json()) == 1  # still one Overview page


def test_the_built_in_page_cannot_be_renamed_or_deleted(client, world):
    org, admin = world["org"], world["admin"]
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview", {"name": "Home"}).status_code == 409
    assert _send(client, "DELETE", admin, f"{org}/dashboards/overview").status_code == 409


# --- pages, order, authority ----------------------------------------------------------------------


def test_administrators_manage_pages_and_members_cannot(client, world):
    org, admin, member = world["org"], world["admin"], world["first"]
    assert _send(client, "POST", member, f"{org}/dashboards", {"name": "Risks"}).status_code == 403
    created = _send(client, "POST", admin, f"{org}/dashboards", {"name": "Risks"})
    assert created.status_code == 201, created.text
    page_id = created.json()["dashboard"]["id"]
    assert _send(client, "PUT", member, f"{org}/dashboards/{page_id}", {"name": "Hacked"}).status_code == 403
    assert _send(client, "PUT", member, f"{org}/dashboards/{page_id}/layout", {"scope": "this", "widgets": []}).status_code == 403
    assert _send(client, "DELETE", member, f"{org}/dashboards/{page_id}").status_code == 403
    assert _get(client, member, f"{org}/dashboard-catalogue").status_code == 403
    renamed = _send(client, "PUT", admin, f"{org}/dashboards/{page_id}", {"name": "Risk review"})
    assert renamed.json()["dashboard"]["name"] == "Risk review"
    assert _send(client, "POST", admin, f"{org}/dashboards", {"name": "risk review"}).status_code == 409


def test_pages_are_ordered_after_the_built_in_one_and_reordered(client, world):
    org, admin = world["org"], world["admin"]
    ids = [_send(client, "POST", admin, f"{org}/dashboards", {"name": n}).json()["dashboard"]["id"] for n in ("A", "B", "C")]
    names = lambda: [p["name"] for p in _get(client, admin, f"{org}/dashboards").json()]  # noqa: E731
    assert names() == ["Overview", "A", "B", "C"]
    assert _send(client, "PUT", admin, f"{org}/dashboards/order", {"ids": [ids[2], ids[0], ids[1]]}).status_code == 204
    assert names() == ["Overview", "C", "A", "B"]
    assert _send(client, "PUT", admin, f"{org}/dashboards/order", {"ids": ids[:2]}).status_code == 422  # not every page


def test_a_page_is_deleted_with_its_viewers(client, world):
    org, admin = world["org"], world["admin"]
    page = _send(client, "POST", admin, f"{org}/dashboards", {"name": "Temporary"}).json()["dashboard"]["id"]
    assert _send(client, "DELETE", admin, f"{org}/dashboards/{page}").status_code == 204
    assert _get(client, admin, f"{org}/dashboards/{page}").status_code == 404


# --- who may see a page ---------------------------------------------------------------------------


def _restricted_page(client, world, viewers):
    return _send(client, "POST", world["admin"], f"{world['org']}/dashboards", {"name": "Board", "viewers": viewers}).json()["dashboard"]["id"]


def test_a_restricted_page_is_hidden_from_other_members_on_every_route(client, world):
    org = world["org"]
    page = _restricted_page(client, world, [{"type": "user", "id": world["first_id"]}])
    listed = lambda t: [p["name"] for p in _get(client, t, f"{org}/dashboards").json()]  # noqa: E731
    assert listed(world["first"]) == ["Overview", "Board"]
    assert listed(world["second"]) == ["Overview"]
    assert listed(world["admin"]) == ["Overview", "Board"]
    assert _get(client, world["first"], f"{org}/dashboards/{page}").status_code == 200
    # 404, not 403: the page's existence is not revealed, on the read and on the figures.
    assert _get(client, world["second"], f"{org}/dashboards/{page}").status_code == 404
    figures = _send(client, "POST", world["second"], f"{org}/dashboards/{page}/metrics", {"metrics": []})
    assert figures.status_code == 404
    assert _send(client, "POST", world["first"], f"{org}/dashboards/{page}/metrics", {"metrics": []}).status_code == 200


def test_only_a_manager_sees_who_a_page_is_limited_to(client, world):
    org = world["org"]
    page = _restricted_page(client, world, [{"type": "user", "id": world["first_id"]}])
    as_member = _get(client, world["first"], f"{org}/dashboards/{page}").json()["dashboard"]
    as_admin = _get(client, world["admin"], f"{org}/dashboards/{page}").json()["dashboard"]
    assert as_member["restricted"] is True and as_member["viewers"] == []
    assert [v["id"] for v in as_admin["viewers"]] == [world["first_id"]]


def test_a_group_viewer_admits_its_members_including_through_a_nested_group(client, world):
    org, admin = world["org"], world["admin"]
    inner = create_org_group(client, admin, org, "Inner", users=[world["first_id"]])
    outer = create_org_group(client, admin, org, "Outer", nested=[inner])
    page = _restricted_page(client, world, [{"type": "org_group", "id": outer}])
    assert _get(client, world["first"], f"{org}/dashboards/{page}").status_code == 200
    assert _get(client, world["second"], f"{org}/dashboards/{page}").status_code == 404


def test_a_viewer_from_another_organisation_or_outside_it_is_refused(client, admin_token, world):
    other, other_admin = create_org_admin_in(client, admin_token, "Other Dashboards Org")
    foreign_group = create_org_group(client, other_admin, other["id"], "Foreign")
    outsider_id = create_org_user(client, admin_token, other["id"], "dash_outsider@example.com")
    org, admin = world["org"], world["admin"]
    foreign = {"name": "X", "viewers": [{"type": "org_group", "id": foreign_group}]}
    outsider = {"name": "Y", "viewers": [{"type": "user", "id": outsider_id}]}
    assert _send(client, "POST", admin, f"{org}/dashboards", foreign).status_code == 400
    assert _send(client, "POST", admin, f"{org}/dashboards", outsider).status_code == 400


def test_a_member_of_another_organisation_cannot_list_or_read_pages(client, admin_token, world):
    _, other_admin = create_org_admin_in(client, admin_token, "Snooping Org")
    org = world["org"]
    assert _get(client, other_admin, f"{org}/dashboards").status_code == 403
    assert _get(client, other_admin, f"{org}/dashboards/overview").status_code == 403


def test_deleting_a_group_that_restricts_a_page_needs_a_replacement_and_never_widens_the_page(client, world):
    org, admin = world["org"], world["admin"]
    group = create_org_group(client, admin, org, "Board members", users=[world["first_id"]])
    replacement = create_org_group(client, admin, org, "Replacement", users=[world["first_id"]])
    page = _restricted_page(client, world, [{"type": "org_group", "id": group}])
    refused = client.delete(f"/api/v1/orgs/{org}/groups/{group}", headers=auth_headers(admin))
    assert refused.status_code == 409
    assert _get(client, world["second"], f"{org}/dashboards/{page}").status_code == 404  # still restricted
    done = client.delete(
        f"/api/v1/orgs/{org}/groups/{group}", params={"replacement_type": "org_group", "replacement_id": replacement},
        headers=auth_headers(admin),
    )
    assert done.status_code in (200, 204), done.text
    assert _get(client, world["second"], f"{org}/dashboards/{page}").status_code == 404
    assert _get(client, world["first"], f"{org}/dashboards/{page}").status_code == 200


def test_a_copy_keeps_the_layout_and_the_viewers_and_gets_a_unique_name(client, world):
    org, admin = world["org"], world["admin"]
    page = _restricted_page(client, world, [{"type": "user", "id": world["first_id"]}])
    _send(client, "PUT", admin, f"{org}/dashboards/{page}/layout", {"scope": "this", "widgets": [
        {"id": "note", "type": "text", "config": {"markdown": "for the board only"}},
    ]})
    first = _send(client, "POST", admin, f"{org}/dashboards/{page}/copy", {})
    assert first.status_code == 201, first.text
    assert first.json()["dashboard"]["name"] == "Copy of Board"
    assert [w["id"] for w in first.json()["widgets"]] == ["note"]
    assert first.json()["dashboard"]["restricted"] is True
    copy_id = first.json()["dashboard"]["id"]
    # The copy is restricted like the original: another member cannot see it.
    assert _get(client, world["second"], f"{org}/dashboards/{copy_id}").status_code == 404
    assert _get(client, world["first"], f"{org}/dashboards/{copy_id}").status_code == 200
    again = _send(client, "POST", admin, f"{org}/dashboards/{page}/copy", {})
    assert again.json()["dashboard"]["name"] == "Copy of Board (2)"
    assert _send(client, "POST", admin, f"{org}/dashboards/{page}/copy", {"name": "Board"}).status_code == 409
    assert _send(client, "POST", world["first"], f"{org}/dashboards/{page}/copy", {}).status_code == 403
    # The built-in page can be copied too, and the copy is an ordinary page.
    builtin = _send(client, "POST", admin, f"{org}/dashboards/overview/copy", {"name": "Overview copy"})
    assert builtin.status_code == 201 and builtin.json()["dashboard"]["is_default"] is False


# --- layout validation ----------------------------------------------------------------------------


@pytest.mark.parametrize(("widget", "why"), [
    ({"id": "a", "type": "activity", "config": {}}, "a project-only widget"),
    ({"id": "a", "type": "stage_progress", "config": {}}, "a project-only widget"),
    ({"id": "a", "type": "nonsense", "config": {}}, "an unknown type"),
    (_tile("requirement_completed_percent"), "a project metric"),
    (_tile("nonsense"), "an unknown metric"),
    (_tile("org_record_count"), "a record count with no type"),
    (_tile(scope="children"), "a project scope"),
])
def test_a_layout_may_only_use_organisation_widgets_and_metrics(client, world, widget, why):
    org, admin = world["org"], world["admin"]
    resp = _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [widget]})
    assert resp.status_code == 422, why


def test_a_record_count_names_a_registered_type_and_a_chart_needs_a_breakdown(client, world):
    org, admin = world["org"], world["admin"]
    ok = {"id": "r", "type": "metric_tile", "config": {"metric": "org_record_count", "params": {"record_type": "requirement"}}}
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [ok]}).status_code == 200
    bad_type = {"id": "r", "type": "metric_tile", "config": {"metric": "org_record_count", "params": {"record_type": "nonsense"}}}
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [bad_type]}).status_code == 422
    scalar_chart = {"id": "c", "type": "status_chart", "config": {"metric": "org_project_count", "chart": "pie"}}
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [scalar_chart]}).status_code == 422
    chart = {"id": "c", "type": "status_chart", "config": {"metric": "org_projects_by_status", "chart": "bar"}}
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [chart]}).status_code == 200


def test_the_catalogue_lists_organisation_types_and_metrics_only(client, world):
    cat = _get(client, world["admin"], f"{world['org']}/dashboard-catalogue").json()
    assert {t["key"] for t in cat["widget_types"]} >= {"metric_tile", "gauge", "status_chart", "text"}
    assert not {t["key"] for t in cat["widget_types"]} & {"activity", "stage_progress", "record_totals"}
    assert {m["key"] for m in cat["metrics"]} == {
        "org_project_count", "org_requirement_count", "org_member_count", "org_file_storage", "org_projects_by_status", "org_record_count",
    }
    assert any(r["type"] == "requirement" for r in cat["record_types"])


# --- figures --------------------------------------------------------------------------------------


def _figures(client, token, org, page, metrics):
    resp = _send(client, "POST", token, f"{org}/dashboards/{page}/metrics", {"metrics": metrics})
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


def test_figures_count_what_the_caller_may_open(client, world):
    org = world["org"]
    asked = [
        {"id": "p", "metric": "org_project_count"}, {"id": "m", "metric": "org_member_count"},
        {"id": "s", "metric": "org_projects_by_status"},
        {"id": "r", "metric": "org_record_count", "params": {"record_type": "requirement"}},
    ]
    admin_view = _figures(client, world["admin"], org, "overview", asked)
    assert admin_view["p"]["value"] == 1 and admin_view["m"]["value"] == 3
    assert sum(row["value"] for row in admin_view["s"]["breakdown"]) == 1
    # A member with no role on the project is not told it exists: the count is their own, never the organisation's.
    member_view = _figures(client, world["first"], org, "overview", asked)
    assert member_view["p"]["value"] == 0
    assert member_view["s"]["breakdown"] == []
    assert member_view["r"]["value"] in (0, None) or member_view["r"]["state"] == "unavailable"


def test_a_batch_is_capped_and_ids_must_be_unique(client, world):
    org, admin = world["org"], world["admin"]
    many = [{"id": f"m{i}", "metric": "org_project_count"} for i in range(25)]
    assert _send(client, "POST", admin, f"{org}/dashboards/overview/metrics", {"metrics": many}).status_code in (422,)
    twice = [{"id": "x", "metric": "org_project_count"}, {"id": "x", "metric": "org_member_count"}]
    assert _send(client, "POST", admin, f"{org}/dashboards/overview/metrics", {"metrics": twice}).status_code == 422
    project_metric = {"metrics": [{"id": "x", "metric": "requirement_count"}]}
    assert _send(client, "POST", admin, f"{org}/dashboards/overview/metrics", project_metric).status_code == 422


def test_an_organisation_record_count_takes_the_type_s_own_list_filters(client, world):
    org, admin = world["org"], world["admin"]
    project = client.get("/api/v1/projects", headers=auth_headers(admin)).json()[0]
    component_id, category_id = create_component_and_category(client, admin, project["id"])
    for name in ("First", "Second"):
        made = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "reasoning": "r", "component_id": component_id, "category_id": category_id}, headers=auth_headers(admin),
        )
        assert made.status_code == 201, made.text

    def count(filters):
        spec = {"id": "c", "metric": "org_record_count", "params": {"record_type": "requirement", "filters": filters}}
        return _figures(client, admin, org, "overview", [spec])["c"]["value"]

    assert count({}) == 2
    assert count({"status": ["draft"]}) == 2
    assert count({"status": ["approved"]}) == 0
    unknown = {"id": "c", "metric": "org_record_count", "params": {"record_type": "requirement", "filters": {"nonsense": ["x"]}}}
    assert _send(client, "POST", admin, f"{org}/dashboards/overview/metrics", {"metrics": [unknown]}).status_code == 422
    cat = _get(client, admin, f"{org}/dashboard-catalogue").json()
    assert "status" in next(r for r in cat["record_types"] if r["type"] == "requirement")["filter_params"]


def test_a_module_metric_is_offered_validated_and_evaluated_only_while_the_module_is_enabled(client, world, monkeypatch):
    from app.modules.registry import OverviewMetric, OverviewMetricValue
    from app.services import org_dashboard_metrics

    org, admin = world["org"], world["admin"]
    demo = {"compliance:posture": ("compliance", OverviewMetric("Posture", "percent", lambda ctx, params: OverviewMetricValue(value=42.0)))}
    monkeypatch.setattr(org_dashboard_metrics, "get_org_overview_metrics", lambda: demo)

    cat = _get(client, admin, f"{org}/dashboard-catalogue").json()
    offered = next(m for m in cat["metrics"] if m["key"] == "compliance:posture")
    assert (offered["module_key"], offered["unit"], offered["scalar"]) == ("compliance", "percent", True)
    tile = {"id": "p", "type": "metric_tile", "config": {"metric": "compliance:posture"}}
    assert _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [tile]}).status_code == 200
    assert _figures(client, admin, org, "overview", [{"id": "p", "metric": "compliance:posture"}])["p"]["value"] == 42.0

    # Switched off for the organisation, the module's metric is no longer in the catalogue and cannot be requested.
    monkeypatch.setattr(org_dashboard_metrics, "is_module_enabled", lambda db, organization_id, key: key != "compliance")
    assert all(m["key"] != "compliance:posture" for m in _get(client, admin, f"{org}/dashboard-catalogue").json()["metrics"])
    refused = _send(client, "POST", admin, f"{org}/dashboards/overview/metrics", {"metrics": [{"id": "p", "metric": "compliance:posture"}]})
    assert refused.status_code == 422


# --- audit ----------------------------------------------------------------------------------------


def test_every_change_is_audited_with_counts_and_names_only(client, world):
    org, admin = world["org"], world["admin"]
    body = {"name": "Audited", "viewers": [{"type": "user", "id": world["first_id"]}]}
    page = _send(client, "POST", admin, f"{org}/dashboards", body).json()["dashboard"]["id"]
    _send(client, "PUT", admin, f"{org}/dashboards/{page}/layout", {"scope": "this", "widgets": [
        {"id": "t", "type": "text", "config": {"markdown": "secret board note"}},
    ]})
    _send(client, "DELETE", admin, f"{org}/dashboards/{page}")
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "organization_dashboard").order_by(AuditEvent.created_at)).all()
    assert [e.action for e in events] == ["created", "layout_changed", "deleted"]
    assert events[0].detail == {"name": "Audited", "viewers": 1}
    assert events[1].detail == {"widgets": 1}
    assert "secret board note" not in str([e.detail for e in events])


# --- bundles --------------------------------------------------------------------------------------


def test_pages_and_their_viewers_round_trip_through_the_organisation_bundle(client, admin_token, world):
    import uuid

    org, admin = world["org"], world["admin"]
    _send(client, "PUT", admin, f"{org}/dashboards/overview/layout", {"scope": "this", "widgets": [_tile(widget_id="kept")]})
    group = create_org_group(client, admin, org, "Board", users=[world["first_id"]])
    page = _restricted_page(client, world, [{"type": "org_group", "id": group}, {"type": "user", "id": world["second_id"]}])
    _send(client, "PUT", admin, f"{org}/dashboards/{page}/layout", {"scope": "this", "widgets": [_tile(widget_id="board")]})

    exported = client.get(f"/api/v1/orgs/{org}/export", headers=auth_headers(admin))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Dashboards Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["organization"]["id"]

    with SessionLocal() as db:
        from app.models.org_dashboard import OrganizationDashboard
        from app.services import org_dashboards

        rows = {r.name: r for r in db.scalars(select(OrganizationDashboard).where(OrganizationDashboard.organization_id == uuid.UUID(copy)))}
        assert set(rows) == {"Overview", "Board"} and rows["Overview"].is_default
        assert [w["id"] for w in rows["Overview"].layout["widgets"]] == ["kept"]
        assert [w["id"] for w in rows["Board"].layout["widgets"]] == ["board"]
        viewers = next(p for p in org_dashboards.all_pages(db, uuid.UUID(copy)) if p.name == "Board").viewers
        assert len(viewers) == 2  # restricted, as it was: never widened by an import


def test_an_import_never_widens_a_restricted_page_when_a_viewer_cannot_be_matched(client, world):
    import uuid

    from app.models.user import User
    from app.services import org_dashboards
    from app.services.bundle_common import BundleImportWarnings

    org = uuid.UUID(world["org"])
    bundle = {"organization_dashboards": [{
        "name": "Ghost page", "layout": {}, "viewers": [{"type": "user", "email": "nobody-here@example.com"}],
    }]}
    warnings = BundleImportWarnings()
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.email == "dash_first@example.com"))
        assert actor is not None
        org_dashboards.import_org(db, org, bundle, actor, warnings)
        db.commit()
        page = next(p for p in org_dashboards.all_pages(db, org) if p.name == "Ghost page")
        assert [(v.type.value, v.id) for v in page.viewers] == [("user", actor.id)]
    assert warnings.messages, "the unmatched viewer is reported"
