"""Tests for tags on any record: name rules, free and restricted vocabularies, nested-project
inheritance, authority, the vocabulary tools (rename, merge, delete, reclassify), usage tables,
the list filter and requirement keywords (which are tags).

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left
by another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.tag import ArtefactTag, Tag
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login
from tests.link_world import REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Tag Org", context_strategy=True)


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}"


def _tags_url(project: dict, record: tuple[str, uuid.UUID]) -> str:
    return f"{_base(project)}/artefacts/{record[0]}/{record[1]}/tags"


def _set(world: World, project: dict, record, names: list[str], token: str | None = None):
    return world.client.put(
        _tags_url(project, record), json={"tags": names}, headers=auth_headers(token or world.token),
    )


def _names(resp) -> list[str]:
    assert resp.status_code in (200, 201), resp.text
    return [t["name"] for t in resp.json()["tags"]]


def _vocab(world: World, project: dict, token: str | None = None) -> dict:
    resp = world.client.get(f"{_base(project)}/tags", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tag_id(world: World, project: dict, name: str) -> str:
    return next(t["id"] for t in _vocab(world, project)["tags"] if t["name"] == name)


def _member_token(world: World, project: dict, role: str = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"{_base(project)}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# --- names ----------------------------------------------------------------------------------


def test_names_are_trimmed_and_unique_ignoring_case(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    assert _names(_set(world, project, record, ["Safety", "safety", "  SAFETY "])) == ["Safety"]
    other = (REQ, world.requirement(project, "B"))
    assert _names(_set(world, project, other, ["safety"])) == ["Safety"]
    assert [t["name"] for t in _vocab(world, project)["tags"]] == ["Safety"]


@pytest.mark.parametrize("bad", ["", "   ", "a,b", "a;b", "x" * 41, "bell\x07char"])
def test_invalid_names_are_rejected(world, bad):
    project = world.project()
    record = (REQ, world.requirement(project))
    assert _set(world, project, record, [bad]).status_code == 422
    assert _vocab(world, project)["tags"] == []


def test_a_forty_character_name_is_accepted(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    assert _names(_set(world, project, record, ["y" * 40])) == ["y" * 40]


def test_a_record_carries_at_most_fifty_tags(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    assert _set(world, project, record, [f"t{i}" for i in range(51)]).status_code == 422
    assert _names(_set(world, project, record, [f"t{i}" for i in range(50)]))


# --- free and restricted --------------------------------------------------------------------


def test_restricted_mode_accepts_only_listed_tags_but_keeps_what_a_record_has(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["old"])
    resp = world.client.put(f"{_base(project)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json()["mode"] == "restricted"
    assert _set(world, project, record, ["old", "new"]).status_code == 422
    assert _names(_set(world, project, record, ["old"])) == ["old"], "a tag already on the record is not rejected"
    created = world.client.post(f"{_base(project)}/tags", json={"name": "new"}, headers=auth_headers(world.token))
    assert created.status_code == 201
    assert sorted(_names(_set(world, project, record, ["old", "NEW"]))) == ["new", "old"]


def test_only_a_manager_can_change_the_list_and_mode(world):
    project = world.project()
    token = _member_token(world, project)
    assert world.client.post(f"{_base(project)}/tags", json={"name": "x"}, headers=auth_headers(token)).status_code == 403
    assert world.client.put(
        f"{_base(project)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(token)
    ).status_code == 403


def test_an_unknown_mode_is_rejected(world):
    project = world.project()
    resp = world.client.put(f"{_base(project)}/tag-settings", json={"mode": "chaos"}, headers=auth_headers(world.token))
    assert resp.status_code == 422


# --- nested projects ------------------------------------------------------------------------


def test_a_child_without_tags_offers_its_ancestors_list_and_mode(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.client.post(f"{_base(parent)}/tags", json={"name": "release-1"}, headers=auth_headers(world.token))
    world.client.put(f"{_base(parent)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(world.token))
    vocab = _vocab(world, child)
    assert [t["name"] for t in vocab["tags"]] == ["release-1"]
    assert vocab["inherited"] is True and vocab["mode"] == "restricted" and vocab["mode_inherited"] is True
    assert all(t["editable"] is False for t in vocab["tags"])
    record = (REQ, world.requirement(child))
    assert _names(_set(world, child, record, ["release-1"])) == ["release-1"]
    assert _set(world, child, record, ["release-1", "other"]).status_code == 422


def test_an_inherited_tag_is_managed_in_the_parent_only(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    created = world.client.post(f"{_base(parent)}/tags", json={"name": "shared"}, headers=auth_headers(world.token)).json()
    renamed = world.client.patch(
        f"{_base(child)}/tags/{created['id']}", json={"name": "mine"}, headers=auth_headers(world.token)
    )
    assert renamed.status_code == 404
    assert world.client.delete(f"{_base(child)}/tags/{created['id']}", headers=auth_headers(world.token)).status_code == 404


def test_a_child_that_sets_its_own_mode_overrides_the_parent(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.client.put(f"{_base(parent)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(world.token))
    world.client.put(f"{_base(child)}/tag-settings", json={"mode": "free"}, headers=auth_headers(world.token))
    vocab = _vocab(world, child)
    assert vocab["mode"] == "free" and vocab["mode_inherited"] is False and vocab["own_mode"] == "free"
    cleared = world.client.put(f"{_base(child)}/tag-settings", json={"mode": None}, headers=auth_headers(world.token))
    assert cleared.json()["mode"] == "restricted"


def test_a_child_that_coins_a_tag_gets_a_vocabulary_of_its_own(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.client.post(f"{_base(parent)}/tags", json={"name": "from-parent"}, headers=auth_headers(world.token))
    record = (REQ, world.requirement(child))
    _set(world, child, record, ["from-parent"])
    assert _names(_set(world, child, record, ["from-parent", "child-only"])) == ["child-only", "from-parent"]
    vocab = _vocab(world, child)
    assert vocab["inherited"] is False and [t["name"] for t in vocab["tags"]] == ["child-only"]
    # The record keeps the ancestor tag it already carried.
    assert "from-parent" in _names(world.client.get(_tags_url(child, record), headers=auth_headers(world.token)))


# --- authority and isolation ----------------------------------------------------------------


def test_a_view_only_member_can_read_tags_but_not_change_them(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["a"])
    token = _member_token(world, project)
    got = world.client.get(_tags_url(project, record), headers=auth_headers(token))
    assert got.status_code == 200 and got.json()["can_edit"] is False and _names(got) == ["a"]
    assert _set(world, project, record, ["a", "b"], token).status_code == 403
    assert world.client.delete(
        f"{_tags_url(project, record)}/{got.json()['tags'][0]['id']}", headers=auth_headers(token)
    ).status_code == 403
    assert _names(world.client.get(_tags_url(project, record), headers=auth_headers(world.token))) == ["a"]


def test_a_stakeholder_can_tag_a_requirement(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    token = _member_token(world, project, "stakeholder")
    assert _names(_set(world, project, record, ["from-stakeholder"], token)) == ["from-stakeholder"]


def test_a_non_member_cannot_see_a_records_tags(world, client, admin_token):
    project = world.project()
    record = (REQ, world.requirement(project))
    _, outsider = create_org_admin_in(client, admin_token, f"Outsider {uuid.uuid4().hex[:6]}")
    assert client.get(_tags_url(project, record), headers=auth_headers(outsider)).status_code in (403, 404)
    assert client.get(f"{_base(project)}/tags", headers=auth_headers(outsider)).status_code in (403, 404)


def test_a_record_of_another_project_is_not_found(world):
    one, two = world.project("One"), world.project("Two")
    record = (REQ, world.requirement(two))
    assert world.client.get(_tags_url(one, record), headers=auth_headers(world.token)).status_code == 404
    assert _set(world, one, record, ["x"]).status_code == 404


def test_an_unregistered_type_and_a_missing_record_are_not_found(world):
    project = world.project()
    assert world.client.get(
        _tags_url(project, ("nonsense", uuid.uuid4())), headers=auth_headers(world.token)
    ).status_code == 404
    assert world.client.get(_tags_url(project, (REQ, uuid.uuid4())), headers=auth_headers(world.token)).status_code == 404


def test_a_tag_from_another_organisation_cannot_be_touched(world, client, admin_token):
    project = world.project()
    other = World(client, admin_token, "Other Tag Org", context_strategy=True)
    theirs = other.project()
    created = client.post(f"{_base(theirs)}/tags", json={"name": "secret"}, headers=auth_headers(other.token)).json()
    assert client.patch(
        f"{_base(project)}/tags/{created['id']}", json={"name": "x"}, headers=auth_headers(world.token)
    ).status_code == 404
    assert client.delete(f"{_base(project)}/tags/{created['id']}", headers=auth_headers(world.token)).status_code == 404
    merged = client.post(
        f"{_base(project)}/tags/{created['id']}/merge", json={"into_tag_id": created["id"]}, headers=auth_headers(world.token)
    )
    assert merged.status_code in (404, 422)
    assert _tag_id(other, theirs, "secret") == created["id"]


# --- a module's type needs no core edit -----------------------------------------------------


def test_a_module_record_is_taggable_with_no_core_edit(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    assert _names(_set(world, project, record, ["ux"])) == ["ux"]
    from app.modules.registry import get_all_registered_artefact_types

    assert PAIN in get_all_registered_artefact_types()


def test_every_registered_type_is_accepted_as_a_taggable_type():
    """`ArtefactTag.artefact_type` is a plain validated string, not a closed enum."""
    from app.modules.registry import get_all_registered_artefact_types

    assert Tag.__table__.c.name_key is not None
    assert ArtefactTag.__table__.c.artefact_type.type.length >= max(len(t) for t in get_all_registered_artefact_types())


# --- vocabulary tools -----------------------------------------------------------------------


def test_rename_changes_every_record_and_refuses_a_clash(world):
    project = world.project()
    a, b = (REQ, world.requirement(project, "A")), (REQ, world.requirement(project, "B"))
    _set(world, project, a, ["alpha", "beta"])
    _set(world, project, b, ["alpha"])
    alpha = _tag_id(world, project, "alpha")
    ok = world.client.patch(f"{_base(project)}/tags/{alpha}", json={"name": "Gamma"}, headers=auth_headers(world.token))
    assert ok.status_code == 200 and ok.json()["usage_count"] == 2
    assert sorted(_names(world.client.get(_tags_url(project, a), headers=auth_headers(world.token)))) == ["Gamma", "beta"]
    clash = world.client.patch(f"{_base(project)}/tags/{alpha}", json={"name": "BETA"}, headers=auth_headers(world.token))
    assert clash.status_code == 409


def test_colour_is_validated_and_clearable(world):
    project = world.project()
    _set(world, project, (REQ, world.requirement(project)), ["c"])
    tag_id = _tag_id(world, project, "c")
    url = f"{_base(project)}/tags/{tag_id}"
    assert world.client.patch(url, json={"colour": "red"}, headers=auth_headers(world.token)).status_code == 422
    assert world.client.patch(url, json={"colour": "#AABBCC"}, headers=auth_headers(world.token)).json()["colour"] == "#aabbcc"
    assert world.client.patch(url, json={"clear_colour": True}, headers=auth_headers(world.token)).json()["colour"] is None


CSS_INJECTION_COLOURS = [
    "#aabbcc;background:url(//evil.example/x)",
    "#aabbcc\n",
    "red",
    "#abc",
    "#aabbccdd",
    "url(javascript:alert(1))",
    "#aabbcc\"onmouseover=\"x",
    "var(--color-danger)",
    "#gggggg",
]


@pytest.mark.parametrize("bad", CSS_INJECTION_COLOURS)
def test_a_colour_that_is_not_plain_hex_is_rejected_on_create_and_update(world, bad):
    project = world.project()
    headers = auth_headers(world.token)
    created = world.client.post(f"{_base(project)}/tags", json={"name": "styled", "colour": bad}, headers=headers)
    assert created.status_code == 422
    ok = world.client.post(f"{_base(project)}/tags", json={"name": "styled", "colour": "#2B6CB0"}, headers=headers)
    assert ok.json()["colour"] == "#2b6cb0"
    url = f"{_base(project)}/tags/{ok.json()['id']}"
    assert world.client.patch(url, json={"colour": bad}, headers=headers).status_code == 422
    assert _vocab(world, project)["tags"][0]["colour"] == "#2b6cb0"


def test_merge_moves_records_once_and_removes_the_source(world):
    project = world.project()
    a, b, c = ((REQ, world.requirement(project, n)) for n in "ABC")
    _set(world, project, a, ["old", "new"])
    _set(world, project, b, ["old"])
    _set(world, project, c, ["new"])
    old, new = _tag_id(world, project, "old"), _tag_id(world, project, "new")
    merged = world.client.post(f"{_base(project)}/tags/{old}/merge", json={"into_tag_id": new}, headers=auth_headers(world.token))
    assert merged.status_code == 200 and merged.json()["records_moved"] == 1
    assert [t["name"] for t in _vocab(world, project)["tags"]] == ["new"]
    assert _vocab(world, project)["tags"][0]["usage_count"] == 3
    assert _names(world.client.get(_tags_url(project, b), headers=auth_headers(world.token))) == ["new"]
    assert world.client.post(
        f"{_base(project)}/tags/{new}/merge", json={"into_tag_id": new}, headers=auth_headers(world.token)
    ).status_code == 422


def test_delete_reports_how_many_records_lost_it(world):
    project = world.project()
    a, b = (REQ, world.requirement(project, "A")), (REQ, world.requirement(project, "B"))
    _set(world, project, a, ["gone", "stay"])
    _set(world, project, b, ["gone"])
    gone = _tag_id(world, project, "gone")
    resp = world.client.delete(f"{_base(project)}/tags/{gone}", headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json()["records_untagged"] == 2
    assert _names(world.client.get(_tags_url(project, a), headers=auth_headers(world.token))) == ["stay"]
    assert _names(world.client.get(_tags_url(project, b), headers=auth_headers(world.token))) == []


def test_add_and_remove_one_tag_keep_the_others(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["one"])
    added = world.client.post(_tags_url(project, record), json={"name": "two"}, headers=auth_headers(world.token))
    assert sorted(_names(added)) == ["one", "two"]
    removed = world.client.delete(f"{_tags_url(project, record)}/{_tag_id(world, project, 'one')}", headers=auth_headers(world.token))
    assert _names(removed) == ["two"]


# --- reclassify -----------------------------------------------------------------------------


def _reclassify(world: World, project: dict, **body):
    return world.client.post(f"{_base(project)}/tags/reclassify", json=body, headers=auth_headers(world.token))


def test_reclassify_previews_then_applies_across_types(world):
    project = world.project()
    req = (REQ, world.requirement(project))
    pain = (PAIN, world.pain_point(project))
    other = (REQ, world.requirement(project, "Other"))
    _set(world, project, req, ["old"])
    _set(world, project, pain, ["old"])
    _set(world, project, other, ["keep"])
    old, new = _tag_id(world, project, "old"), None
    world.client.post(f"{_base(project)}/tags", json={"name": "new"}, headers=auth_headers(world.token))
    new = _tag_id(world, project, "new")
    preview = _reclassify(world, project, from_tag_id=old, add=[new], remove=[old])
    assert preview.status_code == 200 and preview.json() == {"matched": 2, "added": 2, "removed": 2, "dry_run": True}
    assert _names(world.client.get(_tags_url(project, req), headers=auth_headers(world.token))) == ["old"]
    done = _reclassify(world, project, from_tag_id=old, add=[new], remove=[old], dry_run=False)
    assert done.status_code == 200 and done.json()["added"] == 2
    assert _names(world.client.get(_tags_url(project, req), headers=auth_headers(world.token))) == ["new"]
    assert _names(world.client.get(_tags_url(project, pain), headers=auth_headers(world.token))) == ["new"]
    assert _names(world.client.get(_tags_url(project, other), headers=auth_headers(world.token))) == ["keep"]


def test_reclassify_can_be_limited_to_some_types(world):
    project = world.project()
    req = (REQ, world.requirement(project))
    pain = (PAIN, world.pain_point(project))
    _set(world, project, req, ["x"])
    _set(world, project, pain, ["x"])
    world.client.post(f"{_base(project)}/tags", json={"name": "y"}, headers=auth_headers(world.token))
    done = _reclassify(world, project, from_tag_id=_tag_id(world, project, "x"), artefact_types=[PAIN],
                       add=[_tag_id(world, project, "y")], dry_run=False)
    assert done.json()["matched"] == 1
    assert _names(world.client.get(_tags_url(project, req), headers=auth_headers(world.token))) == ["x"]
    assert sorted(_names(world.client.get(_tags_url(project, pain), headers=auth_headers(world.token)))) == ["x", "y"]


def test_reclassify_is_all_or_nothing(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["a"])
    bad = _reclassify(world, project, from_tag_id=_tag_id(world, project, "a"), add=[str(uuid.uuid4())], dry_run=False)
    assert bad.status_code == 404
    assert _names(world.client.get(_tags_url(project, record), headers=auth_headers(world.token))) == ["a"]


def test_reclassify_needs_something_to_do_and_a_selection(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["a"])
    a = _tag_id(world, project, "a")
    assert _reclassify(world, project, from_tag_id=a).status_code == 422
    assert _reclassify(world, project, add=[a]).status_code == 422


def test_reclassify_by_listed_records_needs_tag_authority_for_each(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    world.client.post(f"{_base(project)}/tags", json={"name": "t"}, headers=auth_headers(world.token))
    tag = _tag_id(world, project, "t")
    body = {"records": [{"artefact_type": REQ, "artefact_id": str(record[1])}], "add": [tag], "dry_run": False}
    token = _member_token(world, project)
    assert world.client.post(f"{_base(project)}/tags/reclassify", json=body, headers=auth_headers(token)).status_code == 403
    ok = world.client.post(f"{_base(project)}/tags/reclassify", json=body, headers=auth_headers(world.token))
    assert ok.status_code == 200 and ok.json()["added"] == 1
    by_tag = world.client.post(
        f"{_base(project)}/tags/reclassify", json={"from_tag_id": tag, "remove": [tag]}, headers=auth_headers(token)
    )
    assert by_tag.status_code == 403, "choosing by tag is a vocabulary-wide change"


def test_reclassify_caps_the_number_of_records(world):
    from app.services.tags import MAX_RECLASSIFY_RECORDS

    project = world.project()
    world.client.post(f"{_base(project)}/tags", json={"name": "t"}, headers=auth_headers(world.token))
    records = [{"artefact_type": REQ, "artefact_id": str(uuid.uuid4())} for _ in range(MAX_RECLASSIFY_RECORDS + 1)]
    resp = _reclassify(world, project, records=records, add=[_tag_id(world, project, "t")])
    assert resp.status_code in (404, 422)


# --- usage and filter -----------------------------------------------------------------------


def test_usage_tables_count_per_type_and_list_unused_tags(world):
    project = world.project()
    a, b = (REQ, world.requirement(project, "A")), (REQ, world.requirement(project, "B"))
    pain = (PAIN, world.pain_point(project))
    _set(world, project, a, ["x", "y"])
    _set(world, project, b, ["x"])
    _set(world, project, pain, ["x"])
    world.client.post(f"{_base(project)}/tags", json={"name": "idle"}, headers=auth_headers(world.token))
    body = world.client.get(f"{_base(project)}/tags/usage", headers=auth_headers(world.token)).json()
    by_type = {t["artefact_type"]: {r["name"]: r["count"] for r in t["rows"]} for t in body["tables"]}
    assert by_type[REQ] == {"x": 2, "y": 1} and by_type[PAIN] == {"x": 1}
    assert [t["name"] for t in body["unused"]] == ["idle"]
    only = world.client.get(f"{_base(project)}/tags/usage", params={"artefact_type": PAIN}, headers=auth_headers(world.token)).json()
    assert [t["artefact_type"] for t in only["tables"]] == [PAIN]


def test_usage_only_counts_this_projects_records(world):
    one, two = world.project("One"), world.project("Two")
    _set(world, one, (REQ, world.requirement(one)), ["shared-name"])
    _set(world, two, (REQ, world.requirement(two)), ["shared-name"])
    _set(world, two, (REQ, world.requirement(two, "B")), ["shared-name"])
    rows = world.client.get(f"{_base(one)}/tags/usage", headers=auth_headers(world.token)).json()["tables"][0]["rows"]
    assert [(r["name"], r["count"]) for r in rows] == [("shared-name", 1)]


def _list_requirement_names(world: World, project: dict, **params) -> list[str]:
    resp = world.client.get(f"{_base(project)}/requirements", params=params, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return sorted(r["name"] for r in resp.json())


def test_the_requirement_list_filters_by_any_or_all_tags(world):
    project = world.project()
    for name, tags in {"AB": ["a", "b"], "A": ["a"], "B": ["B"], "none": []}.items():
        rid = world.requirement(project, name)
        if tags:
            _set(world, project, (REQ, rid), tags)
    assert _list_requirement_names(world, project, tag=["a"]) == ["A", "AB"]
    assert _list_requirement_names(world, project, tag=["A", "b"]) == ["A", "AB", "B"]
    assert _list_requirement_names(world, project, tag=["a", "b"], tag_mode="all") == ["AB"]
    assert _list_requirement_names(world, project, tag=["missing"]) == []
    assert _list_requirement_names(world, project, tag=[" "]) == ["A", "AB", "B", "none"]


# --- requirement keywords are tags ----------------------------------------------------------


def test_requirement_keywords_are_tags_in_both_directions(world):
    project = world.project()
    created = world.client.post(
        f"{_base(project)}/requirements",
        json={"name": "K", "component_id": project["component_id"], "category_id": project["category_id"],
              "keywords": ["Security", "latency"]},
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert sorted(created.json()["keywords"]) == ["Security", "latency"]
    assert sorted(_names(world.client.get(_tags_url(project, (REQ, uuid.UUID(rid))), headers=auth_headers(world.token)))) == [
        "Security", "latency",
    ]
    _set(world, project, (REQ, uuid.UUID(rid)), ["latency", "ops"])
    got = world.client.get(f"{_base(project)}/requirements/{rid}", headers=auth_headers(world.token)).json()
    assert sorted(got["keywords"]) == ["latency", "ops"]
    assert _list_requirement_names(world, project, keyword="OPS") == ["K"]


def test_a_restricted_project_rejects_an_unlisted_keyword_on_create(world):
    project = world.project()
    world.client.put(f"{_base(project)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(world.token))
    resp = world.client.post(
        f"{_base(project)}/requirements",
        json={"name": "K", "component_id": project["component_id"], "category_id": project["category_id"],
              "keywords": ["nope"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 422


# --- audit ----------------------------------------------------------------------------------


def test_tagging_is_audited_and_shows_in_the_activity_timeline(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    _set(world, project, record, ["audited"])
    _set(world, project, record, [])
    db = SessionLocal()
    try:
        actions = db.scalars(
            select(AuditEvent.action).where(AuditEvent.entity_type == REQ, AuditEvent.entity_id == str(record[1]))
        ).all()
        assert "tagged" in actions and "untagged" in actions
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_type == "tag", AuditEvent.action == "created")) >= 1
    finally:
        db.close()


def test_vocabulary_changes_are_audited(world):
    project = world.project()
    _set(world, project, (REQ, world.requirement(project)), ["v"])
    tag_id = _tag_id(world, project, "v")
    world.client.patch(f"{_base(project)}/tags/{tag_id}", json={"name": "w"}, headers=auth_headers(world.token))
    world.client.delete(f"{_base(project)}/tags/{tag_id}", headers=auth_headers(world.token))
    db = SessionLocal()
    try:
        actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "tag", AuditEvent.entity_id == tag_id)).all())
        assert {"created", "updated", "deleted"} <= actions
    finally:
        db.close()


# --- cleanup --------------------------------------------------------------------------------


def test_deleting_a_project_removes_its_tags(world, client):
    project = world.project("Doomed")
    _set(world, project, (REQ, world.requirement(project)), ["bye"])
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(Tag).where(Tag.project_id == uuid.UUID(project["id"]))) == 1
        from app.models.project import Project

        db.delete(db.get(Project, uuid.UUID(project["id"])))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Tag).where(Tag.project_id == uuid.UUID(project["id"]))) == 0
        assert db.scalar(select(func.count()).select_from(ArtefactTag).where(ArtefactTag.project_id == uuid.UUID(project["id"]))) == 0
    finally:
        db.close()


# --- the list filter on module and core lists -----------------------------------------------


def test_the_filter_works_on_actions_pain_points_and_decisions(client, admin_token):
    world = World(client, admin_token, "Tag Filter Org", decisions=True, context_strategy=True)
    project = world.project()
    base = _base(project)
    records = {
        "action": ("requirement_action", world.action(project, "A1"), world.action(project, "A2"), f"{base}/actions"),
        PAIN: (PAIN, world.pain_point(project, "P1"), world.pain_point(project, "P2"), f"{base}/modules/context_strategy/pain-points"),
        "decision": ("decision", world.decision(project, "DEC-1"), world.decision(project, "DEC-2"), f"{base}/modules/decisions"),
    }
    for artefact_type, tagged, other, url in records.values():
        assert _names(_set(world, project, (artefact_type, tagged), ["wanted"])) == ["wanted"]
        _set(world, project, (artefact_type, other), ["other"])
        everything = world.client.get(url, headers=auth_headers(world.token)).json()
        assert len(everything) == 2
        filtered = world.client.get(url, params={"tag": "WANTED"}, headers=auth_headers(world.token))
        assert filtered.status_code == 200, filtered.text
        assert [row["id"] for row in filtered.json()] == [str(tagged)]
        both = world.client.get(url, params={"tag": ["wanted", "other"], "tag_mode": "all"}, headers=auth_headers(world.token))
        assert both.json() == []


# --- find by tag across types ---------------------------------------------------------------


def test_find_tagged_records_spans_types_and_omits_what_the_caller_cannot_open(world):
    project = world.project()
    req = (REQ, world.requirement(project, "Alpha"))
    pain = (PAIN, world.pain_point(project, "Beta"))
    untagged = (REQ, world.requirement(project, "Gamma"))
    _set(world, project, req, ["wanted"])
    _set(world, project, pain, ["Wanted", "extra"])
    url = f"{_base(project)}/tags/records"
    found = world.client.get(url, params={"tag": "WANTED"}, headers=auth_headers(world.token)).json()
    assert {(r["artefact_type"], r["id"]) for r in found["records"]} == {(REQ, str(req[1])), (PAIN, str(pain[1]))}
    assert found["truncated"] is False and all(r["label"] for r in found["records"])
    both = world.client.get(url, params={"tag": ["wanted", "extra"], "tag_mode": "all"}, headers=auth_headers(world.token)).json()
    assert [r["id"] for r in both["records"]] == [str(pain[1])]
    only = world.client.get(url, params={"tag": "wanted", "artefact_type": REQ}, headers=auth_headers(world.token)).json()
    assert [r["id"] for r in only["records"]] == [str(req[1])]
    assert str(untagged[1]) not in {r["id"] for r in found["records"]}
    assert world.client.get(url, params={"tag": " "}, headers=auth_headers(world.token)).status_code == 422
    assert world.client.get(url, params={"tag": "x", "artefact_type": "nonsense"}, headers=auth_headers(world.token)).status_code == 404


def test_find_tagged_records_never_crosses_projects(world):
    one, two = world.project("One"), world.project("Two")
    _set(world, two, (REQ, world.requirement(two, "Elsewhere")), ["shared"])
    found = world.client.get(f"{_base(one)}/tags/records", params={"tag": "shared"}, headers=auth_headers(world.token)).json()
    assert found["records"] == []


def test_a_draft_record_returns_the_picker_without_tags(world):
    from app.services.link_authoring import DRAFT_ARTEFACT_ID

    project = world.project()
    _set(world, project, (REQ, world.requirement(project)), ["known"])
    got = world.client.get(_tags_url(project, (REQ, DRAFT_ARTEFACT_ID)), headers=auth_headers(world.token))
    assert got.status_code == 200 and got.json()["tags"] == [] and got.json()["can_edit"] is True
    assert [t["name"] for t in got.json()["suggestions"]] == ["known"]
    token = _member_token(world, project)
    assert world.client.get(_tags_url(project, (REQ, DRAFT_ARTEFACT_ID)), headers=auth_headers(token)).json()["can_edit"] is False
    assert _set(world, project, (REQ, DRAFT_ARTEFACT_ID), ["x"]).status_code == 404
    unknown = world.client.get(_tags_url(project, ("nonsense", DRAFT_ARTEFACT_ID)), headers=auth_headers(world.token))
    assert unknown.status_code == 404


def test_a_requirement_update_that_omits_keywords_leaves_the_tags_alone(world):
    project = world.project()
    rid = world.requirement(project, "Keep")
    _set(world, project, (REQ, rid), ["added-later"])
    url = f"{_base(project)}/requirements/{rid}"
    current = world.client.get(url, headers=auth_headers(world.token)).json()
    body = {
        "name": "Renamed", "reasoning": current["reasoning"], "clarification": current["clarification"],
        "description": current["description"], "component_id": current["component_id"],
        "category_id": current["category_id"], "change_note": "rename only",
        "owner": {"type": current["owner"]["type"], "id": current["owner"]["id"]},
    }
    assert world.client.put(url, json=body, headers=auth_headers(world.token)).status_code == 200
    assert _names(world.client.get(_tags_url(project, (REQ, rid)), headers=auth_headers(world.token))) == ["added-later"]
    cleared = world.client.put(url, json={**body, "keywords": []}, headers=auth_headers(world.token))
    assert cleared.status_code == 200 and cleared.json()["keywords"] == []


# --- project bundle -------------------------------------------------------------------------


def _round_trip(world: World, project: dict, name: str, *, into: World | None = None) -> dict:
    """Exports `project` and imports the bundle as a new project; returns the new project."""
    target = into or world
    exported = world.client.get(f"{_base(project)}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    imported = target.client.post(
        "/api/v1/projects/import", data={"organization_id": target.org["id"], "name": name},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(target.token),
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["project"]


def test_a_bundle_carries_the_vocabulary_the_mode_and_requirement_tags(world):
    project = world.project("Bundle source")
    world.client.post(f"{_base(project)}/tags", json={"name": "Unused", "colour": "#2b6cb0"}, headers=auth_headers(world.token))
    rid = world.requirement(project, "Tagged req")
    _set(world, project, (REQ, rid), ["Kept", "Also kept"])
    world.client.put(f"{_base(project)}/tag-settings", json={"mode": "restricted"}, headers=auth_headers(world.token))
    new = _round_trip(world, project, "Bundle copy")
    vocab = _vocab(world, new)
    assert vocab["own_mode"] == "restricted"
    assert {t["name"]: t["colour"] for t in vocab["tags"]} == {"Unused": "#2b6cb0", "Kept": None, "Also kept": None}
    copied = next(r for r in world.client.get(f"{_base(new)}/requirements", headers=auth_headers(world.token)).json() if r["name"] == "Tagged req")
    assert sorted(copied["keywords"]) == ["Also kept", "Kept"], "restored even though the copy is restricted"
    assert [t["usage_count"] for t in vocab["tags"] if t["name"] == "Unused"] == [0]


def test_a_bundle_carries_module_record_tags(world):
    project = world.project("Bundle modules")
    world.enable("stakeholders")
    persona = world.client.post(
        f"{_base(project)}/modules/stakeholders/personas", json={"name": "Tagged persona"}, headers=auth_headers(world.token),
    ).json()
    _set(world, project, ("persona", uuid.UUID(persona["id"])), ["Regulatory"])
    new = _round_trip(world, project, "Bundle modules copy")
    copied = world.client.get(f"{_base(new)}/modules/stakeholders/personas", headers=auth_headers(world.token)).json()
    mine = next(p for p in copied if p["name"] == "Tagged persona" and p["project_id"] == new["id"])
    got = world.client.get(_tags_url(new, ("persona", uuid.UUID(mine["id"]))), headers=auth_headers(world.token))
    assert _names(got) == ["Regulatory"]


# --- nested projects: counts and ownership --------------------------------------------------


def test_an_inherited_tags_usage_count_covers_only_the_childs_own_records(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    _set(world, parent, (REQ, world.requirement(parent, "P1")), ["shared"])
    _set(world, parent, (REQ, world.requirement(parent, "P2")), ["shared"])
    _set(world, child, (REQ, world.requirement(child, "C1")), ["shared"])
    assert [t["usage_count"] for t in _vocab(world, parent)["tags"]] == [3], "the owner sees the whole tree's use"
    seen_by_child = _vocab(world, child)
    assert seen_by_child["inherited"] is True
    assert [t["usage_count"] for t in seen_by_child["tags"]] == [1], "the child sees only its own records"


def test_reclassifying_by_a_parents_tag_keeps_a_child_records_ownership(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.client.post(f"{_base(parent)}/tags", json={"name": "new"}, headers=auth_headers(world.token))
    child_record = (REQ, world.requirement(child, "C1"))
    _set(world, parent, (REQ, world.requirement(parent, "P1")), ["old"])
    _set(world, child, child_record, ["old"])
    done = _reclassify(
        world, parent, from_tag_id=_tag_id(world, parent, "old"), add=[_tag_id(world, parent, "new")], dry_run=False,
    )
    assert done.status_code == 200 and done.json()["matched"] == 2
    db = SessionLocal()
    try:
        owner = db.scalar(
            select(ArtefactTag.project_id).join(Tag, Tag.id == ArtefactTag.tag_id)
            .where(Tag.name == "new", ArtefactTag.artefact_id == child_record[1])
        )
        assert owner == uuid.UUID(child["id"])
    finally:
        db.close()
    rows = world.client.get(f"{_base(child)}/tags/usage", headers=auth_headers(world.token)).json()["tables"][0]["rows"]
    assert {r["name"]: r["count"] for r in rows} == {"old": 1, "new": 1}
    assert "new" in _names(world.client.get(_tags_url(child, child_record), headers=auth_headers(world.token)))


def test_a_record_listed_twice_in_a_reclassify_is_counted_once(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    world.client.post(f"{_base(project)}/tags", json={"name": "t"}, headers=auth_headers(world.token))
    item = {"artefact_type": REQ, "artefact_id": str(record[1])}
    resp = _reclassify(world, project, records=[item, item], add=[_tag_id(world, project, "t")], dry_run=False)
    assert resp.status_code == 200 and resp.json() == {"matched": 1, "added": 1, "removed": 0, "dry_run": False}
