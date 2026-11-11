"""Tests for placing records in the component/category tree: validation, many placements per record, the
requirement's resolved view, authority, the list filter and keeping the tree consistent when it changes.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.placement import ArtefactPlacement
from app.models.project import Project
from app.modules.registry import RecordCellError, RecordImportContext
from app.services.placements import PlacementFilter, forget_record_placements, pairs_for_records, placement_column
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Placement Org", context_strategy=True)


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}"


def _url(project: dict, record: tuple[str, uuid.UUID]) -> str:
    return f"{_base(project)}/artefacts/{record[0]}/{record[1]}/placements"


def _put(world: World, project: dict, record, places: list[dict], token: str | None = None):
    return world.client.put(
        _url(project, record), json={"placements": places}, headers=auth_headers(token or world.token),
    )


def _component(world: World, project: dict, name: str, prefix: str) -> str:
    resp = world.client.post(
        f"{_base(project)}/components", json={"name": name, "prefix": prefix}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _category(world: World, project: dict, component_id: str, name: str, prefix: str) -> str:
    resp = world.client.post(
        f"{_base(project)}/categories", json={"name": name, "prefix": prefix, "component_id": component_id},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _member_token(world: World, project: dict, role: str = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"{_base(project)}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _shown(resp) -> list[tuple[str, str | None]]:
    assert resp.status_code == 200, resp.text
    return [(p["component_name"], p["category_name"]) for p in resp.json()["placements"]]


def test_a_record_holds_several_placements_in_tree_order(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Tuning", "TUN")
    resp = _put(world, project, record, [
        {"component_id": hardware, "category_id": tuning}, {"component_id": project["component_id"]},
    ])
    # Software was created with the project, so it sorts before Hardware.
    assert _shown(resp) == [("Software", None), ("Hardware", "Tuning")]
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == _shown(resp)


def test_replacing_placements_removes_the_ones_left_out_and_audits_each_change(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    hardware = _component(world, project, "Hardware", "HW")
    _put(world, project, record, [{"component_id": project["component_id"]}, {"component_id": hardware}])
    assert _shown(_put(world, project, record, [{"component_id": hardware}])) == [("Hardware", None)]
    assert _shown(_put(world, project, record, [])) == []
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == str(record[1]), AuditEvent.action.in_(["placed", "unplaced"]))
        ).all()
        assert sorted(e.action for e in events) == ["placed", "placed", "unplaced", "unplaced"]
        assert {e.detail["place"] for e in events} == {"Software", "Hardware"}


def test_duplicates_collapse_and_an_unchanged_put_writes_nothing(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    place = {"component_id": project["component_id"], "category_id": project["category_id"]}
    assert len(_put(world, project, record, [place, place]).json()["placements"]) == 1
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == str(record[1])))
    _put(world, project, record, [place])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == str(record[1]))) == before


def test_a_category_must_sit_under_its_component(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    hardware = _component(world, project, "Hardware", "HW")
    resp = _put(world, project, record, [{"component_id": hardware, "category_id": project["category_id"]}])
    assert resp.status_code == 422
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == []


def test_a_component_of_another_project_is_rejected(world):
    project, other = world.project("A"), world.project("B")
    record = (PAIN, world.pain_point(project))
    assert _put(world, project, record, [{"component_id": other["component_id"]}]).status_code == 422
    foreign = {"component_id": other["component_id"], "category_id": other["category_id"]}
    assert _put(world, project, record, [foreign]).status_code == 422


def test_a_record_holds_at_most_fifty_placements(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    places = [{"component_id": _component(world, project, f"C{i}", f"C{i}")} for i in range(51)]
    assert _put(world, project, record, places).status_code == 422
    assert _put(world, project, record, places[:50]).status_code == 200


def test_a_requirement_shows_its_own_pair_read_only(world):
    project = world.project()
    requirement = (REQ, world.requirement(project))
    resp = world.client.get(_url(project, requirement), headers=auth_headers(world.token))
    assert _shown(resp) == [("Software", "Performance")]
    assert resp.json()["can_edit"] is False and resp.json()["managed_on_record"] is True
    assert _put(world, project, requirement, []).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ArtefactPlacement)) == 0


def test_the_resolved_view_reads_columns_for_requirements_and_rows_for_the_rest(world):
    project = world.project()
    requirement, pain = world.requirement(project), world.pain_point(project)
    _put(world, project, (PAIN, pain), [{"component_id": project["component_id"]}])
    with SessionLocal() as db:
        by_req = pairs_for_records(db, REQ, [requirement])
        by_pain = pairs_for_records(db, PAIN, [pain, uuid.uuid4()])
    assert [(str(p.component_id), str(p.category_id)) for p in by_req[requirement]] == [
        (project["component_id"], project["category_id"])
    ]
    assert list(by_pain) == [pain] and by_pain[pain][0].category_id is None


def test_a_plain_member_cannot_place_but_can_read(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    _put(world, project, record, [{"component_id": project["component_id"]}])
    token = _member_token(world, project)
    resp = world.client.get(_url(project, record), headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["can_edit"] is False
    assert _put(world, project, record, [], token).status_code == 403
    assert len(world.client.get(_url(project, record), headers=auth_headers(world.token)).json()["placements"]) == 1


def test_a_user_outside_the_project_sees_nothing(world, client):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    email = f"out-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, world.token, world.org["id"], email)
    token = login(client, email, "Password123!")
    assert client.get(_url(project, record), headers=auth_headers(token)).status_code in (403, 404)
    assert _put(world, project, record, [], token).status_code in (403, 404)


def test_a_record_of_another_project_or_an_unknown_type_is_not_found(world):
    project, other = world.project("A"), world.project("B")
    record = (PAIN, world.pain_point(other))
    assert world.client.get(_url(project, record), headers=auth_headers(world.token)).status_code == 404
    assert world.client.get(_url(project, ("nonsense", uuid.uuid4())), headers=auth_headers(world.token)).status_code == 404


def test_a_draft_record_reports_whether_the_caller_may_place(world):
    from app.services.link_authoring import DRAFT_ARTEFACT_ID

    project = world.project()
    url = _url(project, (PAIN, DRAFT_ARTEFACT_ID))
    resp = world.client.get(url, headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json() == {"placements": [], "can_edit": True, "managed_on_record": False}
    token = _member_token(world, project)
    assert world.client.get(url, headers=auth_headers(token)).json()["can_edit"] is False
    assert world.client.put(url, json={"placements": []}, headers=auth_headers(world.token)).status_code == 404


def test_the_filter_matches_any_listed_component_or_category(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Tuning", "TUN")
    a, b, c = (world.pain_point(project, t) for t in ("a", "b", "c"))
    _put(world, project, (PAIN, a), [{"component_id": project["component_id"]}])
    _put(world, project, (PAIN, b), [{"component_id": hardware, "category_id": tuning}])
    project_id = uuid.UUID(project["id"])
    with SessionLocal() as db:
        def ids(**kw):
            return PlacementFilter(
                component_id=[uuid.UUID(x) for x in kw.get("components", [])],
                category_id=[uuid.UUID(x) for x in kw.get("categories", [])],
            ).ids(db, project_id, PAIN)

        assert ids(components=[project["component_id"]]) == {a}
        assert ids(components=[hardware]) == {b}
        assert ids(categories=[tuning]) == {b}
        assert ids(components=[project["component_id"]], categories=[tuning]) == {a, b}
        assert ids() == set() and c not in ids(components=[hardware, project["component_id"]])
        rows = [type("R", (), {"id": x})() for x in (a, b, c)]
        assert len(PlacementFilter(component_id=[], category_id=[]).keep(db, project_id, PAIN, rows)) == 3


def test_deleting_a_category_moves_its_placements_and_drops_a_duplicate(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    old = _category(world, project, hardware, "Old", "OLD")
    new = _category(world, project, hardware, "New", "NEW")
    moved, both = world.pain_point(project, "moved"), world.pain_point(project, "both")
    _put(world, project, (PAIN, moved), [{"component_id": hardware, "category_id": old}])
    _put(world, project, (PAIN, both), [
        {"component_id": hardware, "category_id": old}, {"component_id": hardware, "category_id": new},
    ])
    resp = world.client.delete(
        f"{_base(project)}/categories/{old}", params={"reassign_to": new}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 204, resp.text
    assert _shown(world.client.get(_url(project, (PAIN, moved)), headers=auth_headers(world.token))) == [("Hardware", "New")]
    assert _shown(world.client.get(_url(project, (PAIN, both)), headers=auth_headers(world.token))) == [("Hardware", "New")]


def test_a_component_with_placed_records_cannot_be_deleted(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    record = (PAIN, world.pain_point(project))
    _put(world, project, record, [{"component_id": hardware}])
    resp = world.client.delete(f"{_base(project)}/components/{hardware}", headers=auth_headers(world.token))
    assert resp.status_code == 409
    _put(world, project, record, [])
    assert world.client.delete(f"{_base(project)}/components/{hardware}", headers=auth_headers(world.token)).status_code == 204


def test_forgetting_a_record_drops_only_its_placements(world):
    project = world.project()
    one, two = world.pain_point(project, "one"), world.pain_point(project, "two")
    for pain in (one, two):
        _put(world, project, (PAIN, pain), [{"component_id": project["component_id"]}])
    with SessionLocal() as db:
        forget_record_placements(db, PAIN, one)
        db.commit()
        assert set(db.scalars(select(ArtefactPlacement.artefact_id)).all()) == {two}


def test_deleting_the_project_removes_its_placements(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    _put(world, project, record, [{"component_id": project["component_id"]}])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ArtefactPlacement)) == 1
        db.delete(db.get(Project, uuid.UUID(project["id"])))
        db.commit()
        assert db.scalar(select(func.count()).select_from(ArtefactPlacement)) == 0


def test_a_list_endpoint_filters_by_placement_and_combines_with_tags(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    a, b, c = (world.pain_point(project, t) for t in ("a", "b", "c"))
    _put(world, project, (PAIN, a), [{"component_id": project["component_id"]}])
    _put(world, project, (PAIN, b), [{"component_id": hardware}])
    world.client.put(
        f"{_base(project)}/artefacts/{PAIN}/{a}/tags", json={"tags": ["x"]}, headers=auth_headers(world.token)
    )
    url = f"{_base(project)}/modules/context_strategy/pain-points"

    def listed(**params) -> set[str]:
        resp = world.client.get(url, params=params, headers=auth_headers(world.token))
        assert resp.status_code == 200, resp.text
        return {row["id"] for row in resp.json()}

    assert listed() == {str(a), str(b), str(c)}
    assert listed(component_id=[project["component_id"]]) == {str(a)}
    assert listed(component_id=[hardware, project["component_id"]]) == {str(a), str(b)}
    assert listed(category_id=[project["category_id"]]) == set()
    assert listed(component_id=[hardware, project["component_id"]], tag=["x"]) == {str(a)}
    assert listed(component_id=[hardware], tag=["x"]) == set()


# --- export and import ------------------------------------------------------------------------


def _export_rows(world: World, project: dict, record_type: str = PAIN, token: str | None = None) -> list[dict]:
    resp = world.client.get(
        f"{_base(project)}/records/{record_type}/export", headers=auth_headers(token or world.token)
    )
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(world: World, project: dict, rows: list[dict], *, apply: bool = True, token: str | None = None):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return world.client.post(
        f"{_base(project)}/records/{PAIN}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", out.getvalue().encode("utf-8"), "text/csv")},
        headers=auth_headers(token or world.token),
    )


def test_export_carries_a_shared_placements_column_by_prefix(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Tuning", "TUN")
    record = world.pain_point(project)
    _put(world, project, (PAIN, record), [
        {"component_id": hardware, "category_id": tuning}, {"component_id": project["component_id"]},
    ])
    [row] = _export_rows(world, project)
    assert row["placements"] == "SW;HW/TUN"


def test_a_requirement_export_keeps_its_own_columns_and_has_no_placements_column(world):
    project = world.project()
    world.requirement(project)
    [row] = _export_rows(world, project, REQ)
    assert "placements" not in row and row["component"] == "SW" and row["category"] == "PERF"


def test_a_project_without_components_has_no_placements_column(world):
    project = world.client.post(
        "/api/v1/projects", json={"name": "Bare", "organization_id": world.org["id"]}, headers=auth_headers(world.token)
    ).json()
    world.pain_point(project)
    [row] = _export_rows(world, project)
    assert "placements" not in row


def test_import_changes_placements_and_reports_the_change(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    record = (PAIN, world.pain_point(project))
    [row] = _export_rows(world, project)
    row["placements"] = "SW;HW"
    preview = _import(world, project, [row], apply=False).json()
    assert preview["rows"][0]["action"] == "update"
    assert [c["column"] for c in preview["rows"][0]["changes"]] == ["placements"]
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == []
    assert _import(world, project, [row]).json()["rows"][0]["action"] == "update"
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == [
        ("Software", None), ("Hardware", None),
    ]
    assert hardware
    assert _import(world, project, [row]).json()["rows"][0]["action"] == "unchanged"
    row["placements"] = ""
    _import(world, project, [row])
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == []


def test_import_creates_a_record_with_its_placements(world):
    project = world.project()
    world.pain_point(project)
    [row] = _export_rows(world, project)
    row.update({"code": "", "title": "Imported", "placements": "SW/PERF"})
    body = _import(world, project, [row]).json()
    assert body["rows"][0]["action"] == "create", body
    created = next(r for r in _export_rows(world, project) if r["title"] == "Imported")
    assert created["placements"] == "SW/PERF"


@pytest.mark.parametrize("cell", ["NOPE", "SW/NOPE", ";SW/BAD"])
def test_import_refuses_an_unknown_prefix_and_leaves_the_record_alone(world, cell):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    [row] = _export_rows(world, project)
    row["placements"] = cell
    body = _import(world, project, [row]).json()
    assert body["rows"][0]["action"] == "error"
    assert _shown(world.client.get(_url(project, record), headers=auth_headers(world.token))) == []


def test_the_import_column_refuses_a_placement_from_someone_who_may_not_place(world):
    project = world.project()
    with SessionLocal() as db:
        owner = db.get(Project, uuid.UUID(project["id"]))
        for may_place in (True, False):
            built = placement_column(db, owner, PAIN, may_place=may_place, id_of=lambda r: r.id)
            assert built is not None and built[0].parse is not None
            ctx = RecordImportContext(db=db, project=owner, user=None)
            assert built[0].parse(ctx, "") == []
            if may_place:
                assert len(built[0].parse(ctx, "SW/PERF")) == 1
            else:
                with pytest.raises(RecordCellError, match="permission"):
                    built[0].parse(ctx, "SW/PERF")


# --- project bundle ---------------------------------------------------------------------------


def _round_trip(world: World, project: dict, name: str) -> dict:
    """Exports `project` and imports the bundle as a new project; returns the new project."""
    exported = world.client.get(f"{_base(project)}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["project"]


def _only_id(world: World, project: dict, path: str) -> str:
    rows = world.client.get(f"{_base(project)}/{path}", headers=auth_headers(world.token)).json()
    assert len(rows) == 1, rows
    return rows[0]["id"]


def test_a_bundle_carries_placements_for_pain_points_decisions_and_change_requests(client, admin_token):
    world = World(client, admin_token, "Placement Bundle Org", context_strategy=True, decisions=True)
    project = world.project("Source")
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Tuning", "TUN")
    pain, decision = world.pain_point(project), world.decision(project)
    cr = world.client.post(
        f"{_base(project)}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "Wider doors", "reason": "needed"},
        headers=auth_headers(world.token),
    ).json()["id"]
    both = [{"component_id": hardware, "category_id": tuning}, {"component_id": project["component_id"]}]
    for record in ((PAIN, pain), ("decision", decision), ("change_request", uuid.UUID(cr))):
        assert _put(world, project, record, both).status_code == 200, record
        world.client.put(
            _url(project, record).replace("placements", "tags"), json={"tags": ["kept"]}, headers=auth_headers(world.token)
        )

    copy = _round_trip(world, project, "Copy")

    new_ids = {
        PAIN: _only_id(world, copy, "modules/context_strategy/pain-points"),
        "decision": _only_id(world, copy, "modules/decisions"),
        "change_request": _only_id(world, copy, "change-requests"),
    }
    for artefact_type, record_id in new_ids.items():
        got = world.client.get(
            _url(copy, (artefact_type, uuid.UUID(record_id))), headers=auth_headers(world.token)
        )
        assert _shown(got) == [("Software", None), ("Hardware", "Tuning")], artefact_type
        tags = world.client.get(
            _url(copy, (artefact_type, uuid.UUID(record_id))).replace("placements", "tags"), headers=auth_headers(world.token)
        ).json()
        assert [t["name"] for t in tags["tags"]] == ["kept"], artefact_type
    copied_components = world.client.get(f"{_base(copy)}/components", headers=auth_headers(world.token)).json()
    for artefact_type, record_id in new_ids.items():
        for placement in world.client.get(
            _url(copy, (artefact_type, uuid.UUID(record_id))), headers=auth_headers(world.token)
        ).json()["placements"]:
            assert placement["component_id"] in {c["id"] for c in copied_components}, "a copy never points at the source tree"


def test_every_module_that_bundles_tags_bundles_placements_the_same_number_of_times():
    """A record type that travels in a bundle with its tags must travel with its placements: the two calls sit
    side by side wherever a bundle row is written or read."""
    root = Path(__file__).resolve().parent.parent / "app"
    gaps = []
    for path in root.rglob("*.py"):
        if "/tests/" in str(path) or path.name in {"tags.py", "placements.py"}:
            continue
        text = path.read_text()
        for tags_call, placements_call in (
            ("restore_record_tags(", "restore_record_placements("),
            ("record_tag_names(", "record_placements("),
        ):
            tags_n = len(re.findall(rf"(?<![\w.]){re.escape(tags_call)}", text))
            placements_n = len(re.findall(rf"(?<![\w.]){re.escape(placements_call)}", text))
            if tags_n != placements_n and "triage" not in path.name:
                gaps.append(f"{path.relative_to(root)}: {tags_call} x{tags_n} but {placements_call} x{placements_n}")
    assert not gaps, gaps


# --- search -----------------------------------------------------------------------------------


def _search(world: World, text: str, fields: list[str]) -> list[dict]:
    resp = world.client.post(
        "/api/v1/search", json={"q": text, "fields": fields, "scope": "all"}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]


def test_search_finds_records_by_component_and_category_name_when_asked(world):
    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Turbo tuning", "TUN")
    placed, other = world.pain_point(project, "Placed"), world.pain_point(project, "Other")
    _put(world, project, (PAIN, placed), [{"component_id": hardware, "category_id": tuning}])
    requirement = world.requirement(project, "Boot time")

    assert _search(world, "turbo", ["title"]) == [], "placements are searched only when the field is chosen"
    hits = _search(world, "turbo", ["title", "placements"])
    assert [h["id"] for h in hits] == [str(placed)] and other
    assert hits[0]["snippet"]["field_key"] == "placements" and "Hardware / Turbo tuning" in hits[0]["snippet"]["text"]
    assert str(requirement) in {h["id"] for h in _search(world, "performance", ["title", "placements"])}


def test_the_search_field_picker_lists_the_placements_field(world):
    resp = world.client.get("/api/v1/search/fields", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    assert "placements" in [f["key"] for f in resp.json()]


# --- scaling ----------------------------------------------------------------------------------


def test_placed_records_do_not_add_statements_to_the_list_export_or_bundle(world):
    """Placements are read for a whole page at once, so the statements behind a list, its export and the project
    bundle stay the same however many records are placed."""
    from tests.test_scaling_shapes import _Statements

    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    paths = {
        "list": f"{_base(project)}/modules/context_strategy/pain-points",
        "export": f"{_base(project)}/records/{PAIN}/export",
        "bundle": f"{_base(project)}/export",
    }

    def measure() -> dict[str, int]:
        found = {}
        for name, path in paths.items():
            assert world.client.get(path, headers=auth_headers(world.token)).status_code == 200
            with _Statements() as statements:
                assert world.client.get(path, headers=auth_headers(world.token)).status_code == 200
            found[name] = statements.count
        return found

    def add(count: int) -> None:
        for i in range(count):
            pain = world.pain_point(project, f"Pain {uuid.uuid4().hex[:6]}-{i}")
            _put(world, project, (PAIN, pain), [{"component_id": hardware}, {"component_id": project["component_id"]}])

    add(2)
    small = measure()
    add(8)
    assert measure() == small


# --- reports ----------------------------------------------------------------------------------


def test_reports_offer_a_placements_field_for_placeable_types_only(world):
    from app.services.report_fields import field_catalogue, field_domain, load_records

    project = world.project()
    hardware = _component(world, project, "Hardware", "HW")
    tuning = _category(world, project, hardware, "Tuning", "TUN")
    placed, bare = world.pain_point(project, "Placed"), world.pain_point(project, "Bare")
    _put(world, project, (PAIN, placed), [
        {"component_id": project["component_id"]}, {"component_id": hardware, "category_id": tuning},
    ])
    requirement = world.requirement(project)
    with SessionLocal() as db:
        assert "placements" in [f.key for f in field_catalogue(PAIN)]
        assert "placements" not in [f.key for f in field_catalogue("compliance_requirement")]
        assert field_domain(db, PAIN, "placements", [uuid.UUID(project["id"])]) is None
        records = load_records(db, PAIN, [placed, bare], ["placements"])
        assert records[placed].values["placements"] == "Software; Hardware / Tuning"
        assert "placements" not in records[bare].values or not records[bare].values["placements"]
        assert load_records(db, REQ, [requirement], ["placements"])[requirement].values["placements"] == "Software / Performance"
        with pytest.raises(KeyError):
            load_records(db, "compliance_requirement", [uuid.uuid4()], ["placements"])


# --- a page of records ------------------------------------------------------------------------


def test_a_page_read_returns_the_places_of_visible_records_only(world):
    project, other = world.project("A"), world.project("B")
    hardware = _component(world, project, "Hardware", "HW")
    placed, bare = world.pain_point(project, "Placed"), world.pain_point(project, "Bare")
    foreign = world.pain_point(other, "Foreign")
    _put(world, project, (PAIN, placed), [{"component_id": hardware}, {"component_id": project["component_id"]}])
    _put(world, other, (PAIN, foreign), [{"component_id": other["component_id"]}])
    url = f"{_base(project)}/placements/{PAIN}"
    resp = world.client.get(
        url, params={"id": [str(placed), str(bare), str(foreign), str(uuid.uuid4())]}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["placements"]
    assert list(body) == [str(placed)]
    assert [p["component_name"] for p in body[str(placed)]] == ["Software", "Hardware"]
    assert world.client.get(f"{_base(project)}/placements/nonsense", headers=auth_headers(world.token)).status_code == 404
    assert world.client.get(url, headers=auth_headers(world.token)).json() == {"placements": {}}
    outsider = _member_token(world, other)
    assert world.client.get(url, params={"id": [str(placed)]}, headers=auth_headers(outsider)).status_code in (403, 404)
