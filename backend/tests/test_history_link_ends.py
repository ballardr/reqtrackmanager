"""The project History page names the two records a link event joins (`services.activity_link_ends`): the generic
link table and the older requirement and module families, a hidden end shown by its type only, and a statement
count that stays flat as links grow."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.services.activity_link_ends import CORE_LINK_ENDS, link_ends, readers
from tests.conftest import auth_headers
from tests.link_world import REQ, World

DEC = "decision"


def _history(world: World, project: dict, **params) -> list[dict]:
    resp = world.client.get(f"/api/v1/projects/{project['id']}/changes", params={"limit": 100, **params}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _log(project: dict, entity_type: str, action: str, detail: dict) -> None:
    db = SessionLocal()
    try:
        db.add(AuditEvent(
            entity_type=entity_type, entity_id=str(uuid.uuid4()), action=action, project_id=uuid.UUID(project["id"]),
            detail=detail, created_at=datetime.now(UTC),
        ))
        db.commit()
    finally:
        db.close()


def test_a_generic_link_created_and_deleted_names_both_ends_and_the_link_type(client, admin_token):
    world = World(client, admin_token, "History Link Org", decisions=True)
    project = world.project()
    req, dec = world.requirement(project, "Login"), world.decision(project, "DEC-7")
    type_id = world.link_types_by_name()["Related to"]["id"]
    link = world.generic_link(project, (REQ, req), type_id, (DEC, dec))
    assert link.status_code == 201, link.text
    deleted = world.client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{req}/links/{link.json()['id']}", headers=auth_headers(world.token),
    )
    assert deleted.status_code == 204, deleted.text

    entries = [e for e in _history(world, project) if e["entity_type"] == "artefact_link"]
    assert {e["action"] for e in entries} == {"created", "deleted"}
    for entry in entries:
        source, target = entry["linked_records"]
        assert (source["role"], source["entity_type"], source["entity_id"]) == ("source", REQ, str(req))
        assert "Login" in source["label"]
        assert (target["role"], target["entity_type"], target["entity_id"]) == ("target", DEC, str(dec))
        assert "DEC-7" in target["label"] and target["entity_type_label"]
        assert entry["link_type_label"] == "Related to"


def test_a_requirement_link_event_names_both_requirements(client, admin_token):
    world = World(client, admin_token, "History Req Link Org")
    project = world.project()
    a, b = world.requirement(project, "Alpha"), world.requirement(project, "Beta")
    type_id = world.link_types_by_name()["Derives from"]["id"]
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a}/links",
        json={"target_requirement_id": str(b), "link_type_id": str(type_id)}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    entry = next(e for e in _history(world, project) if e["entity_type"] == "requirement_link")
    assert [r["entity_id"] for r in entry["linked_records"]] == [str(a), str(b)]
    assert entry["link_type_label"] == "Derives from"


def test_a_module_family_names_its_ends_through_the_module_reader(client, admin_token):
    world = World(client, admin_token, "History Module Link Org", decisions=True)
    project = world.project()
    new, old = world.decision(project, "DEC-1"), world.decision(project, "DEC-2")
    _log(project, "decision_link", "created", {"kind": "supersession", "new_decision_id": str(new), "old_decision_id": str(old)})
    entry = next(e for e in _history(world, project) if e["entity_type"] == "decision_link")
    assert [r["entity_id"] for r in entry["linked_records"]] == [str(new), str(old)]
    assert entry["link_type_label"] == "Supersedes"


def test_an_end_the_viewer_cannot_open_keeps_its_type_and_loses_its_identity(client, admin_token):
    world = World(client, admin_token, "History Hidden End Org", decisions=True)
    project, other = world.project("P"), world.project("Elsewhere")
    mine, hidden = world.requirement(project, "Visible"), world.decision(other, "DEC-99")
    _log(project, "artefact_link", "created", {
        "source_type": REQ, "source_id": str(mine), "target_type": DEC, "target_id": str(hidden),
    })
    entry = next(e for e in _history(world, project) if e["entity_type"] == "artefact_link")
    source, target = entry["linked_records"]
    assert source["entity_id"] == str(mine)
    assert target["entity_type"] == DEC and target["entity_type_label"]
    assert target["entity_id"] is None and target["label"] is None and target["project_id"] is None
    assert "DEC-99" not in str(entry)


def test_an_unreadable_detail_yields_no_ends():
    assert link_ends("artefact_link", {"source_id": "nope"}) is None
    assert link_ends("artefact_link", None) is None
    assert link_ends("unknown_link", {"source_id": str(uuid.uuid4())}) is None


def test_every_logged_link_event_type_has_an_ends_reader():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    logged: set[str] = set()
    for path in app_dir.rglob("*.py"):
        if "/tests/" in str(path):
            continue
        logged |= set(re.findall(r'entity_type="([a-z_]+_link)"', path.read_text()))
    assert logged <= set(readers()), sorted(logged - set(readers()))
    assert set(CORE_LINK_ENDS) <= set(readers())


class _Statements:
    def __enter__(self):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._count)
        return self

    def _count(self, *_args):
        self.count += 1

    def __exit__(self, *_exc):
        event.remove(engine, "before_cursor_execute", self._count)


def test_the_statement_count_stays_flat_as_link_events_grow(client, admin_token):
    world = World(client, admin_token, "History Link Count Org", decisions=True)
    project = world.project()
    reqs = [world.requirement(project, f"R{i}") for i in range(3)]
    decisions = [world.decision(project, f"DEC-{i + 10}") for i in range(3)]
    url = f"/api/v1/projects/{project['id']}/changes"

    def log_links(count: int) -> None:
        for i in range(count):
            _log(project, "artefact_link", "created", {
                "source_type": REQ, "source_id": str(reqs[i % 3]), "target_type": DEC, "target_id": str(decisions[i % 3]),
            })

    def measure() -> int:
        assert client.get(url, params={"limit": 50}, headers=auth_headers(world.token)).status_code == 200
        with _Statements() as statements:
            assert client.get(url, params={"limit": 50}, headers=auth_headers(world.token)).status_code == 200
        return statements.count

    log_links(3)
    small = measure()
    log_links(30)
    assert measure() == small


def test_context_strategy_events_read_their_target_type_and_name_from_the_kind():
    strategy, requirement, old = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    plain = link_ends("context_strategy_link", {"kind": "drives_requirement", "strategy_id": str(strategy), "target_id": str(requirement)})
    assert plain is not None
    assert plain.source == ("strategy", strategy) and plain.target == (REQ, requirement) and plain.link_type_label == "Drives"
    superseded = link_ends("context_strategy_link", {"kind": "supersession", "new_strategy_id": str(strategy), "old_strategy_id": str(old)})
    assert superseded is not None
    assert superseded.source == ("strategy", strategy) and superseded.target == ("strategy", old)
    untyped = link_ends("context_strategy_link", {"kind": "related_to_requirement", "future_state_id": str(strategy), "target_id": str(requirement)})
    assert untyped is not None and untyped.link_type_label is None and untyped.source[0] == "future_state"


def test_the_export_names_both_records_of_a_link_event(client, admin_token):
    world = World(client, admin_token, "History Link Export Org", decisions=True)
    project = world.project()
    req, dec = world.requirement(project, "Exported"), world.decision(project, "DEC-5")
    type_id = world.link_types_by_name()["Related to"]["id"]
    assert world.generic_link(project, (REQ, req), type_id, (DEC, dec)).status_code == 201
    resp = client.get(
        f"/api/v1/projects/{project['id']}/changes/export", params={"format": "csv", "entity_type": "artefact_link"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    assert "Exported" in text and "→" in text and "DEC-5" in text and "(Related to)" in text
