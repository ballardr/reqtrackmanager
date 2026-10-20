"""Tests for the global search service (`services.search`, `POST /api/v1/search`).

Each test builds its own organisation (`tests.link_world.World`), so none depends on state
left by another test or run.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from app.database import SessionLocal
from app.models.user import User
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login
from tests.link_world import ACTION, REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Search Org", context_strategy=True)


def _search(world: World, body: dict, token: str | None = None):
    return world.client.post("/api/v1/search", json=body, headers=auth_headers(token or world.token))


def _hits(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]


def _titles(resp) -> list[str]:
    return [h["title"] for h in _hits(resp)]


def _member(world: World, project: dict, role: str = "member") -> str:
    """A user holding only `role` on `project`; returns their token."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _tag(world: World, project: dict, artefact_type: str, artefact_id: uuid.UUID, name: str) -> None:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact_type}/{artefact_id}/tags", json={"name": name},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text


def _set_requirement_description(world: World, project: dict, requirement_id: uuid.UUID, description: str) -> None:
    base = f"/api/v1/projects/{project['id']}/requirements/{requirement_id}"
    current = world.client.get(base, headers=auth_headers(world.token)).json()
    payload = {
        "name": current["name"], "description": description, "component_id": current["component_id"],
        "category_id": current["category_id"], "owner": {"type": current["owner"]["type"], "id": current["owner"]["id"]},
    }
    resp = world.client.put(base, json=payload, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text


def _scope_project(project: dict) -> dict:
    return {"scope": "project", "project_id": project["id"]}


def test_finds_a_record_by_title_and_code_in_one_project(world):
    project = world.project()
    other = world.project("Other")
    req = world.requirement(project, "Voltage limit")
    world.requirement(other, "Voltage elsewhere")

    by_title = _hits(_search(world, {"q": "voltage", **_scope_project(project)}))
    assert [h["title"] for h in by_title] == ["Voltage limit"]
    hit = by_title[0]
    assert hit["id"] == str(req) and hit["type"] == REQ and hit["type_label"] == "Requirement"
    assert hit["project_id"] == project["id"] and hit["project_code"] == project["code"]
    assert hit["status"] == "draft" and hit["status_label"] == "Draft"
    assert (hit["open_type"], hit["open_id"], hit["open_project_id"]) == (REQ, str(req), project["id"])

    by_code = _hits(_search(world, {"q": hit["code"].lower(), **_scope_project(project)}))
    assert [h["id"] for h in by_code] == [str(req)]


def test_default_fields_are_id_title_and_tags_not_description(world):
    project = world.project()
    req = world.requirement(project, "Plain name")
    _set_requirement_description(world, project, req, "mentions zebra crossing")

    default = _search(world, {"q": "zebra", **_scope_project(project)})
    assert _hits(default) == []
    assert default.json()["fields_used"] == ["id", "title", "tags"]

    with_description = _search(world, {"q": "zebra", "fields": ["id", "title", "description"], **_scope_project(project)})
    hits = _hits(with_description)
    assert [h["id"] for h in hits] == [str(req)]
    snippet = hits[0]["snippet"]
    assert snippet["field_key"] == "description" and snippet["field_label"] == "Description"
    assert snippet["text"][slice(*snippet["ranges"][0])].lower() == "zebra"


def test_a_tag_finds_a_record_by_default_and_not_once_tags_is_deselected(world):
    project = world.project()
    req = world.requirement(project, "Untitled thing")
    _tag(world, project, REQ, req, "Safety-Critical")

    found = _hits(_search(world, {"q": "safety-crit", **_scope_project(project)}))
    assert [h["id"] for h in found] == [str(req)]
    assert found[0]["snippet"]["field_key"] == "tags" and found[0]["snippet"]["text"] == "Safety-Critical"
    # Case-insensitive.
    assert [h["id"] for h in _hits(_search(world, {"q": "SAFETY-CRIT", **_scope_project(project)}))] == [str(req)]
    assert _hits(_search(world, {"q": "safety-crit", "fields": ["id", "title"], **_scope_project(project)})) == []


def test_every_word_must_match_unless_phrase_mode(world):
    project = world.project()
    world.requirement(project, "Brake pedal travel")
    world.requirement(project, "Travel brake pedal")
    world.requirement(project, "Brake only")

    both = _titles(_search(world, {"q": "pedal brake", **_scope_project(project)}))
    assert sorted(both) == ["Brake pedal travel", "Travel brake pedal"]
    phrase = _titles(_search(world, {"q": "brake pedal", "match": "phrase", **_scope_project(project)}))
    assert sorted(phrase) == ["Brake pedal travel", "Travel brake pedal"]
    assert _titles(_search(world, {"q": "pedal brake", "match": "phrase", **_scope_project(project)})) == []


def test_like_wildcards_in_the_query_are_literal(world):
    project = world.project()
    world.requirement(project, "100% coverage")
    world.requirement(project, "1000 units")
    assert _titles(_search(world, {"q": "0%", **_scope_project(project)})) == ["100% coverage"]
    assert _titles(_search(world, {"q": "1_0", **_scope_project(project)})) == []


def test_short_and_overlong_queries_and_deep_pages_are_refused(world):
    project = world.project()
    assert _search(world, {"q": "a", **_scope_project(project)}).status_code == 422
    assert _search(world, {"q": "x" * 201, **_scope_project(project)}).status_code == 422
    assert _search(world, {"q": "ok", "limit": 50, "offset": 460, **_scope_project(project)}).status_code == 422
    assert _search(world, {"q": "ok", "scope": "project"}).status_code == 422  # a project is required


def test_all_projects_scope_spans_projects_and_labels_each(world):
    first, second = world.project("First"), world.project("Second")
    world.requirement(first, "Shared wording one")
    world.requirement(second, "Shared wording two")

    resp = _search(world, {"q": "shared wording", "scope": "all"})
    hits = _hits(resp)
    assert {h["project_id"] for h in hits} == {first["id"], second["id"]}
    assert {h["project_name"] for h in hits} == {"First", "Second"}
    counts = {c["type"]: c["count"] for c in resp.json()["type_counts"]}
    assert counts[REQ] == 2 and resp.json()["total"] == 2


def test_projects_are_results_for_all_scope_only(world):
    project = world.project("Zephyr programme")
    hits = _hits(_search(world, {"q": "zephyr", "scope": "all"}))
    assert [(h["type"], h["id"], h["open_type"]) for h in hits] == [("project", project["id"], "project")]
    assert _hits(_search(world, {"q": "zephyr", **_scope_project(project)})) == []


def test_a_user_without_a_role_never_sees_a_project_or_its_records(world, client):
    project = world.project("Secret programme")
    world.requirement(project, "Hidden requirement")
    outsider_email = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, world.token, world.org["id"], outsider_email)
    outsider = login(client, outsider_email, "Password123!")

    assert _hits(_search(world, {"q": "hidden", "scope": "all"}, outsider)) == []
    assert _hits(_search(world, {"q": "secret", "scope": "all"}, outsider)) == []
    # Naming the project directly answers like a missing one.
    assert _search(world, {"q": "hidden", **_scope_project(project)}, outsider).status_code == 404
    assert _search(world, {"q": "hidden", "scope": "project", "project_id": str(uuid.uuid4())}).status_code == 404


def test_another_organisation_is_never_searched(client, admin_token):
    first = World(client, admin_token, "Tenant A")
    second = World(client, admin_token, "Tenant B")
    project_a, project_b = first.project("A"), second.project("B")
    first.requirement(project_a, "Needle in tenant A")
    second.requirement(project_b, "Needle in tenant B")

    assert _titles(_search(first, {"q": "needle", "scope": "all"})) == ["Needle in tenant A"]
    assert _titles(_search(second, {"q": "needle", "scope": "all"})) == ["Needle in tenant B"]
    assert _search(first, {"q": "needle", **_scope_project(project_b)}).status_code == 404


def test_a_module_or_sub_component_that_is_off_is_not_searched(world):
    project = world.project()
    world.pain_point(project, "Findable pain")
    body = {"q": "findable", **_scope_project(project)}
    assert _titles(_search(world, body)) == ["Findable pain"]

    sub = f"/api/v1/projects/{project['id']}/modules/context_strategy/subcomponents/pain_point"
    off = world.client.put(sub, json={"enabled": False}, headers=auth_headers(world.token))
    assert off.status_code == 200, off.text
    result = _search(world, body).json()
    assert result["hits"] == [] and result["type_counts"] == []
    on = world.client.put(sub, json={"enabled": True}, headers=auth_headers(world.token))
    assert on.status_code == 200, on.text
    assert _titles(_search(world, body)) == ["Findable pain"]

    module = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/modules/context_strategy", json={"enabled": False}, headers=auth_headers(world.token),
    )
    assert module.status_code == 200, module.text
    assert _hits(_search(world, body)) == []


def test_a_type_the_caller_cannot_view_in_a_project_is_not_searched(world, monkeypatch):
    from app.services import search as search_service

    project = world.project()
    world.pain_point(project, "Shared wording pain")
    world.requirement(project, "Shared wording requirement")
    real = search_service.get_effective_permissions

    def without_pain_points(db, user_id, **kwargs):
        return {p for p in real(db, user_id, **kwargs) if not p.startswith("pain_point:")}

    monkeypatch.setattr(search_service, "get_effective_permissions", without_pain_points)
    result = _search(world, {"q": "shared wording", **_scope_project(project)}).json()
    assert [h["type"] for h in result["hits"]] == [REQ]
    assert {c["type"] for c in result["type_counts"]} == {REQ}


def test_a_user_in_two_organisations_is_searched_through_each_organisations_own_gates(client, admin_token):
    from app.models.enums import OrgRole, ProjectRole
    from app.models.organization import UserOrgRole
    from app.models.project import UserProjectRole

    first = World(client, admin_token, "Dual One")
    second = World(client, admin_token, "Dual Two")
    project_a, project_b = first.project("Alpha"), second.project("Beta")
    first.requirement(project_a, "Dual needle one")
    second.requirement(project_b, "Dual needle two")
    second.requirement(second.project("Hidden"), "Dual needle hidden")
    db = SessionLocal()
    try:
        db.add(UserOrgRole(user_id=first.user_id, organization_id=uuid.UUID(second.org["id"]), role=OrgRole.MEMBER))
        db.add(UserProjectRole(user_id=first.user_id, project_id=uuid.UUID(project_b["id"]), role=ProjectRole.MEMBER))
        db.commit()
    finally:
        db.close()

    result = _search(first, {"q": "dual needle", "scope": "all"}).json()
    assert sorted(h["title"] for h in result["hits"]) == ["Dual needle one", "Dual needle two"]  # not the project it has no role in
    assert {o["id"] for o in result["organizations"]} == {first.org["id"], second.org["id"]}
    only_second = _search(first, {"q": "dual needle", "scope": "all", "organization_ids": [second.org["id"]]}).json()
    assert [h["title"] for h in only_second["hits"]] == ["Dual needle two"]
    assert only_second["hits"][0]["project_name"] == "Beta"


def test_a_statement_timeout_answers_408_with_a_narrow_the_search_message(world, monkeypatch):
    import dataclasses

    from sqlalchemy import text

    from app.services import search as search_service
    from app.services import search_core

    project = world.project()
    world.requirement(project, "Slow wording")
    slow = dataclasses.replace(search_core.CORE_SEARCH_PROVIDERS[REQ], where=(text("pg_sleep(0.5) IS NOT NULL"),))
    monkeypatch.setitem(search_core.CORE_SEARCH_PROVIDERS, REQ, slow)
    monkeypatch.setattr(search_service, "STATEMENT_TIMEOUT_MS", 50)
    resp = _search(world, {"q": "slow", **_scope_project(project)})
    assert resp.status_code == 408 and "Narrow the search" in resp.json()["detail"]


def test_the_number_of_queries_does_not_grow_with_the_number_of_results(world):
    from sqlalchemy import event

    from app.database import engine

    project = world.project()
    for i in range(3):
        world.requirement(project, f"Counted item {i}")

    def statements(body: dict) -> int:
        seen: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert _search(world, body).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    body = {"q": "counted item", **_scope_project(project)}
    small = statements(body)
    for i in range(3, 25):
        world.requirement(project, f"Counted item {i}")
    assert statements(body) == small


def test_no_core_search_file_names_a_module():
    from pathlib import Path

    from app.modules.registry import get_module_registry

    root = Path(__file__).resolve().parent.parent / "app"
    core_files = [root / "services" / "search.py", root / "services" / "search_core.py", root / "routers" / "search.py"]
    for module_key in get_module_registry():
        for path in core_files:
            source = path.read_text()
            assert f"modules.{module_key}" not in source, f"{path.name} imports module {module_key}"
            assert f'"{module_key}:' not in source, f"{path.name} names a scope of module {module_key}"


def test_every_registered_artefact_type_is_searchable_or_says_why_not():
    from app.modules.registry import get_all_registered_artefact_types, get_not_searchable_types, get_search_providers

    providers = get_search_providers()
    reasons = get_not_searchable_types()
    for artefact_type in get_all_registered_artefact_types():
        assert artefact_type in providers or reasons.get(artefact_type), f"{artefact_type} has no search provider or reason"
    for artefact_type, provider in providers.items():
        if provider.open_owner_type:
            assert provider.open_owner_type in providers, f"{artefact_type} opens an unregistered type"
            assert provider.columns.owner_id is not None, f"{artefact_type} names an owner type but no owner column"
        reserved = {"id", "title", "tags"}
        assert not reserved & {f.key for f in provider.fields}, f"{artefact_type} redeclares a reserved field"
        assert len({f.key for f in provider.fields}) == len(provider.fields), f"{artefact_type} repeats a field key"


def test_a_field_key_has_one_label_across_types():
    from app.modules.registry import get_search_providers

    labels: dict[str, set[str]] = {}
    for provider in get_search_providers().values():
        for f in provider.fields:
            labels.setdefault(f.key, set()).add(f.label)
    assert {key: found for key, found in labels.items() if len(found) > 1} == {}


def test_a_role_without_view_on_a_type_does_not_find_it(world):
    project = world.project()
    req = world.requirement(project, "Alpha requirement")
    token = _member(world, project)
    assert [h["id"] for h in _hits(_search(world, {"q": "alpha", **_scope_project(project)}, token))] == [str(req)]


def test_archived_records_need_the_flag(world):
    project = world.project()
    req = world.requirement(project, "Retired wording")
    resp = world.client.delete(f"/api/v1/projects/{project['id']}/requirements/{req}", headers=auth_headers(world.token))
    assert resp.status_code == 204, resp.text
    assert _hits(_search(world, {"q": "retired", **_scope_project(project)})) == []
    found = _hits(_search(world, {"q": "retired", "include_archived": True, **_scope_project(project)}))
    assert [h["is_archived"] for h in found] == [True]


def test_filters_narrow_by_type_status_and_project(world):
    first, second = world.project("First"), world.project("Second")
    world.requirement(first, "Mixed topic requirement")
    world.action(first, "Mixed topic action")
    world.requirement(second, "Mixed topic other")

    everything = _search(world, {"q": "mixed topic", "scope": "all"})
    assert {c["type"]: c["count"] for c in everything.json()["type_counts"]} == {REQ: 2, ACTION: 1}
    only_actions = _search(world, {"q": "mixed topic", "scope": "all", "types": [ACTION]})
    assert [h["type"] for h in _hits(only_actions)] == [ACTION]
    assert {c["type"]: c["count"] for c in only_actions.json()["type_counts"]} == {REQ: 2, ACTION: 1}  # counts ignore the type filter
    in_first = _search(world, {"q": "mixed topic", "scope": "all", "project_ids": [first["id"]]})
    assert {h["project_id"] for h in _hits(in_first)} == {first["id"]}
    approved = _search(world, {"q": "mixed topic", "scope": "all", "statuses": ["approved"]})
    assert _hits(approved) == []


def test_ranking_prefers_exact_code_then_title_and_sort_updated_is_available(world):
    project = world.project()
    first = world.requirement(project, "Common phrase here")
    world.requirement(project, "Another common phrase")
    code = _hits(_search(world, {"q": "common", **_scope_project(project)}))[0]["code"]
    top = _hits(_search(world, {"q": code, **_scope_project(project)}))
    assert top and top[0]["code"] == code
    by_updated = _hits(_search(world, {"q": "common", "sort": "updated", **_scope_project(project)}))
    assert len(by_updated) == 2 and str(first) in {h["id"] for h in by_updated}


def test_paging_and_totals(world):
    project = world.project()
    for i in range(5):
        world.requirement(project, f"Paged item {i}")
    first = _search(world, {"q": "paged item", "limit": 2, "offset": 0, **_scope_project(project)}).json()
    second = _search(world, {"q": "paged item", "limit": 2, "offset": 2, **_scope_project(project)}).json()
    assert first["total"] == 5 and not first["total_capped"]
    ids = [h["id"] for h in first["hits"]] + [h["id"] for h in second["hits"]]
    assert len(ids) == 4 and len(set(ids)) == 4
    no_counts = _search(world, {"q": "paged item", "counts": False, **_scope_project(project)}).json()
    assert no_counts["total"] is None and no_counts["type_counts"] == []


def test_the_query_text_is_never_logged(world, caplog):
    project = world.project()
    world.requirement(project, "Logged wording")
    with caplog.at_level(logging.DEBUG):
        assert _hits(_search(world, {"q": "ultra-secret-phrase-xyz", **_scope_project(project)})) == []
        _hits(_search(world, {"q": "logged wording", **_scope_project(project)}))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ultra-secret-phrase-xyz" not in text and "logged wording" not in text.lower()
    assert any(r.name == "app.services.search" for r in caplog.records)


def test_a_stored_default_applies_when_fields_are_omitted_and_is_overridden_when_given(world):
    project = world.project()
    req = world.requirement(project, "Plain")
    _set_requirement_description(world, project, req, "contains giraffe")
    db = SessionLocal()
    try:
        email = db.query(User.email).filter(User.id == world.user_id).scalar()
        user = db.get(User, world.user_id)
        user.ui_preferences = {"search_default_fields": ["id", "title", "description", "no_such_field"]}
        db.commit()
        assert email
    finally:
        db.close()
    stored = _search(world, {"q": "giraffe", **_scope_project(project)}).json()
    assert [h["id"] for h in stored["hits"]] == [str(req)]
    assert stored["fields_used"] == ["id", "title", "description"]  # the stale key is ignored
    overridden = _search(world, {"q": "giraffe", "fields": ["id", "title"], **_scope_project(project)}).json()
    assert overridden["hits"] == []


def test_search_fields_lists_labels_only_for_viewable_types(world):
    world.project()
    fields = world.client.get("/api/v1/search/fields", headers=auth_headers(world.token))
    assert fields.status_code == 200
    keys = [f["key"] for f in fields.json()]
    assert keys[:3] == ["id", "title", "tags"]
    assert "description" in keys and "reasoning" in keys
    by_key = {f["key"]: f for f in fields.json()}
    assert "Requirement" in by_key["reasoning"]["types"]

    outsider_email = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], outsider_email)
    outsider = login(world.client, outsider_email, "Password123!")
    nothing = world.client.get("/api/v1/search/fields", headers=auth_headers(outsider)).json()
    assert [f["key"] for f in nothing][:3] == ["id", "title", "tags"]
    # With no project role the only types on offer are the organisation-level ones a member may read.
    assert all(set(f["types"]) <= {"Strategy", "Future state", "Guiding principle"} for f in nothing)
    assert "requirement" not in {f["key"] for f in nothing} and "reasoning" not in {f["key"] for f in nothing}


def test_organisation_filter_data_lists_only_the_callers_organisations(client, admin_token):
    first = World(client, admin_token, "Orgs One")
    second = World(client, admin_token, "Orgs Two")
    first.project()
    second.project()
    result = _search(first, {"q": "anything", "scope": "all"}).json()
    assert [o["id"] for o in result["organizations"]] == [first.org["id"]]
    assert create_org_admin_in is not None


def test_an_unknown_module_scope_is_not_found(world):
    world.project()
    for scope in ("nosuch:scope:" + str(uuid.uuid4()), "compliance:standard:not-a-uuid", "compliance:standard:" + str(uuid.uuid4()), "garbage"):
        assert _search(world, {"q": "anything", "scope": scope}).status_code == 404


def test_default_search_fields_are_validated_when_saved(world):
    world.project()
    headers = auth_headers(world.token)

    def save(value):
        return world.client.patch("/api/v1/auth/me/preferences", json={"ui_preferences": {"search_default_fields": value}}, headers=headers)

    saved = save(["description", "tags"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["ui_preferences"]["search_default_fields"] == ["id", "title", "description", "tags"]
    assert save(["description", "no_such_field"]).status_code == 422
    assert save("description").status_code == 422
    assert save([1]).status_code == 422
    cleared = world.client.patch("/api/v1/auth/me/preferences", json={"ui_preferences": {"search_default_fields": None}}, headers=headers)
    assert cleared.status_code == 200 and "search_default_fields" not in cleared.json()["ui_preferences"]


def test_the_frontend_access_log_never_records_the_query_string():
    from pathlib import Path

    config = (Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf").read_text()
    code = "\n".join(line for line in config.splitlines() if not line.lstrip().startswith("#"))
    assert "log_format path_only" in code and "access_log /dev/stdout path_only;" in code
    log_format = code.split("log_format path_only", 1)[1].split(";", 2)[0:2]
    joined = " ".join(log_format)
    for forbidden in ("$request ", "$request_uri", "$args", "$query_string", "$http_referer"):
        assert forbidden not in joined + " ", f"the access log format uses {forbidden.strip()}"
    assert "$uri" in joined and "$referer_path" in joined


def test_an_organisation_that_requires_two_factor_is_not_searchable_without_it(world):
    from app.models.organization import Organization

    project = world.project()
    world.requirement(project, "Locked lockzq requirement")
    body = {"q": "lockzq", "scope": "all"}
    assert len(_hits(_search(world, body))) == 1
    db = SessionLocal()
    try:
        db.get(Organization, uuid.UUID(world.org["id"])).require_2fa = True
        db.commit()
    finally:
        db.close()
    locked = _search(world, body).json()
    assert locked["hits"] == [] and locked["type_counts"] == []
    assert _hits(_search(world, {"q": "lockzq", "scope": "project", "project_id": project["id"]})) == []


def _comment(world: World, project: dict, requirement_id: uuid.UUID, body: str, token: str | None = None):
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}/comments", json={"body": body},
        headers=auth_headers(token or world.token),
    )
    assert resp.status_code == 201, resp.text


def test_comments_are_searched_only_when_asked_for_never_by_default_or_as_a_stored_default(world):
    project = world.project()
    req = world.requirement(project, "Commented thing")
    _comment(world, project, req, "the reviewer raised commentzq about torque")
    scope = _scope_project(project)

    assert _hits(_search(world, {"q": "commentzq", **scope})) == []  # not a default field
    asked = _search(world, {"q": "commentzq", "fields": ["id", "title", "comments"], **scope}).json()
    assert [h["id"] for h in asked["hits"]] == [str(req)]
    assert asked["hits"][0]["snippet"]["field_key"] == "comments" and asked["hits"][0]["snippet"]["field_label"] == "Comments"

    fields = {f["key"]: f for f in world.client.get("/api/v1/search/fields", headers=auth_headers(world.token)).json()}
    assert "Requirement" in fields["comments"]["types"] and fields["comments"]["default_allowed"] is False
    assert fields["description"]["default_allowed"] is True

    headers = auth_headers(world.token)
    refused = world.client.patch(
        "/api/v1/auth/me/preferences", json={"ui_preferences": {"search_default_fields": ["comments"]}}, headers=headers,
    )
    assert refused.status_code == 422 and "one search at a time" in refused.json()["detail"]
    # A stale stored default that somehow carries it is ignored too.
    db = SessionLocal()
    try:
        db.get(User, world.user_id).ui_preferences = {"search_default_fields": ["id", "title", "comments"]}
        db.commit()
    finally:
        db.close()
    stale = _search(world, {"q": "commentzq", **scope}).json()
    assert stale["hits"] == [] and "comments" not in stale["fields_used"]


def test_a_comment_carries_its_records_read_gate(client, admin_token):
    first = World(client, admin_token, "Comment Gate One")
    second = World(client, admin_token, "Comment Gate Two")
    project_a, project_b = first.project("A"), second.project("B")
    req_a, req_b = first.requirement(project_a, "Alpha record"), second.requirement(project_b, "Beta record")
    _comment(first, project_a, req_a, "shared gatecommentzq text")
    _comment(second, project_b, req_b, "shared gatecommentzq text")
    body = {"q": "gatecommentzq", "scope": "all", "fields": ["comments"]}
    assert [h["title"] for h in _hits(_search(first, body))] == ["Alpha record"]
    assert [h["title"] for h in _hits(_search(second, body))] == ["Beta record"]


def test_comments_are_found_for_module_types_too(client, admin_token):
    from app.modules.risk_management.tests._helpers import create_risk, project_base, setup

    _, project, token = setup(client, admin_token, "Search Comment Risk Co")

    risk = create_risk(client, token, project["id"], title="Plain risk title")
    resp = client.post(
        f"{project_base(project['id'])}/risks/{risk['id']}/comments", json={"body": "note about riskcommentzq"}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    found = client.post(
        "/api/v1/search", json={"q": "riskcommentzq", "scope": "all", "fields": ["id", "title", "comments"]}, headers=auth_headers(token),
    ).json()
    assert [h["id"] for h in found["hits"]] == [risk["id"]] and found["hits"][0]["snippet"]["field_key"] == "comments"


def test_every_commenting_type_declares_a_real_comment_table():
    from sqlalchemy import inspect

    from app.modules.registry import get_search_providers

    for artefact_type, provider in get_search_providers().items():
        if provider.comments is not None:
            table = inspect(provider.comments.model).local_table
            assert provider.comments.body.table is table and provider.comments.created_at.table is table, artefact_type
