"""The project History page's Type and Change filters (`services.activity_kinds`): events are classified by entity
type first (a link is a link, never *Created*), the Type list is two levels (Records by module, then Metadata), and
a group or several types narrow the query without growing the statement count."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.modules.registry import get_all_registered_artefact_types, get_module_registry
from app.services.activity_kinds import (
    CORE_ACTION_KINDS,
    CORE_RECORDS_KEY,
    METADATA_GROUPS,
    classify_entity,
    entity_groups,
    is_group_key,
    kind_of,
    types_in_groups,
)
from tests.conftest import auth_headers
from tests.link_world import REQ, World

DEC = "decision"

APP_DIR = Path(__file__).resolve().parents[1] / "app"
TYPES_TS = APP_DIR.parents[1] / "frontend" / "src" / "api" / "types.ts"


def _log(project: dict, entity_type: str, action: str, detail: dict | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(AuditEvent(
            entity_type=entity_type, entity_id=str(uuid.uuid4()), action=action, project_id=uuid.UUID(project["id"]),
            detail=detail or {}, created_at=datetime.now(UTC),
        ))
        db.commit()
    finally:
        db.close()


def _history(world: World, project: dict, **params) -> list[dict]:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/changes", params={"limit": 200, **params}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_every_link_event_has_the_links_kind_whatever_its_action():
    link_types = ["artefact_link", "requirement_link", "requirement_action_link", "context_strategy_link", "decision_link"]
    for entity_type in link_types:
        for action in ("created", "deleted", "linked", "unlinked", "link_type_changed", "updated"):
            assert kind_of(action, None, entity_type) == "links", (entity_type, action)


def test_the_eighth_and_the_fifth_of_november_link_rows_classify_the_same():
    assert kind_of("created", None, "artefact_link") == kind_of("linked", None, "requirement_action_link") == "links"


@pytest.mark.parametrize(("entity_type", "action", "kind"), [
    ("tag", "created", "tags"), ("tag", "deleted", "tags"),
    ("user_project_role", "created", "access"), ("project_group", "deleted", "access"),
    ("file_asset", "uploaded", "links"),
    ("requirement", "created", "created"), ("requirement", "updated", "edited"), ("requirement", "approved", "status"),
    ("requirement", "deleted", "deleted"), ("requirement", "linked", "links"),
    ("project_stage", "created", "created"), ("project_stage", "deleted", "deleted"),
    ("project_status_definition", "updated", "edited"), ("requirement", "no_such_action", "other"),
])
def test_kind_follows_the_entity_type_first_and_the_action_otherwise(entity_type, action, kind):
    assert kind_of(action, None, entity_type) == kind


def test_a_registered_record_type_groups_under_its_module_and_core_types_under_core():
    assert classify_entity("requirement").key == CORE_RECORDS_KEY
    assert classify_entity("requirement").section == "records"
    owners = {
        artefact_type: definition for definition in get_module_registry().values() for artefact_type in definition.artefact_types
    }
    assert owners, "no module declares an artefact type"
    for artefact_type, definition in owners.items():
        group = classify_entity(artefact_type)
        assert (group.key, group.label, group.section) == (f"records:{definition.key}", definition.name, "records")


def test_a_type_nobody_classified_is_listed_under_metadata_other():
    group = classify_entity("something_new_nobody_declared")
    assert (group.key, group.section, group.forced_kind) == ("metadata:other", "metadata", None)


def test_the_type_list_is_core_first_then_modules_then_metadata_in_a_fixed_order():
    groups = entity_groups(["requirement", "artefact_link", "tag", "project_stage", "mystery", "user_project_role", "decision"])
    keys = [group["key"] for group in groups]
    assert keys[0] == CORE_RECORDS_KEY
    assert keys[-5:] == ["metadata:links", "metadata:tags", "metadata:access", "metadata:structure", "metadata:other"]
    assert next(g for g in groups if g["key"] == "metadata:links")["types"] == ["artefact_link"]


def test_group_keys_are_validated_and_types_resolve_through_them():
    assert is_group_key("records:core") and is_group_key("metadata:links")
    assert not is_group_key("metadata:nothing") and not is_group_key("records:no_such_module") and not is_group_key("junk")
    assert types_in_groups(["tag", "artefact_link", "requirement"], ["metadata:links"]) == {"artefact_link"}
    assert types_in_groups(["tag"], ["metadata:no_such"]) == set()


def test_every_logged_entity_type_is_a_record_or_has_a_metadata_group():
    """A literal `entity_type="..."` written anywhere in the app lands in a named group, not Other."""
    records = get_all_registered_artefact_types()
    stray: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        if "/tests/" in str(path) or "/alembic/" in str(path):
            continue
        for entity_type in re.findall(r'entity_type="([a-z_]+)"', path.read_text()):
            if entity_type not in records and classify_entity(entity_type).key == "metadata:other":
                stray.add(entity_type)
    assert not stray, f"declare these in CORE_METADATA_TYPES or ModuleDefinition.activity_metadata_types: {sorted(stray)}"


def test_every_module_metadata_declaration_names_a_real_group():
    for definition in get_module_registry().values():
        for entity_type, group in definition.activity_metadata_types.items():
            assert group in METADATA_GROUPS, (definition.key, entity_type, group)
            assert entity_type not in definition.artefact_types


def test_every_core_action_kind_is_a_known_kind():
    assert set(CORE_ACTION_KINDS.values()) <= {"created", "edited", "status", "links", "tags", "access", "comments", "deleted"}


def test_a_created_link_is_filed_under_links_not_created(client, admin_token):
    world = World(client, admin_token, "History Kind Org", decisions=True)
    project = world.project()
    req, dec = world.requirement(project, "Login"), world.decision(project, "DEC-7")
    type_id = world.link_types_by_name()["Related to"]["id"]
    assert world.generic_link(project, (REQ, req), type_id, (DEC, dec)).status_code == 201

    links = [e for e in _history(world, project, kind="links") if e["entity_type"] == "artefact_link"]
    assert [e["action"] for e in links] == ["created"] and links[0]["kind"] == "links"
    created = _history(world, project, kind="created")
    assert all(e["entity_type"] != "artefact_link" for e in created)
    assert any(e["entity_type"] == "requirement" for e in created)


def test_the_change_filter_takes_several_kinds_and_excludes_metadata(client, admin_token):
    world = World(client, admin_token, "History Change Org")
    project = world.project()
    _log(project, "project_stage", "created")
    _log(project, "project_stage", "deleted")
    _log(project, "tag", "created")
    _log(project, "user_project_role", "role_granted")
    entries = _history(world, project, kind=["created", "deleted"])
    seen = {(e["entity_type"], e["action"]) for e in entries}
    assert ("project_stage", "created") in seen and ("project_stage", "deleted") in seen
    assert not {e["entity_type"] for e in entries} & {"tag", "user_project_role"}


def test_facets_return_the_two_level_groups(client, admin_token):
    world = World(client, admin_token, "History Facet Org")
    project = world.project()
    world.requirement(project, "Login")
    _log(project, "tag", "created")
    _log(project, "artefact_link", "created", {})
    resp = world.client.get(f"/api/v1/projects/{project['id']}/changes/facets", headers=auth_headers(world.token))
    assert resp.status_code == 200
    groups = {g["key"]: g for g in resp.json()["groups"]}
    assert "requirement" in groups[CORE_RECORDS_KEY]["types"]
    assert groups["metadata:tags"]["types"] == ["tag"] and groups["metadata:links"]["section"] == "metadata"
    assert set(resp.json()["entity_types"]) >= {"requirement", "tag", "artefact_link"}


def test_a_group_and_several_types_narrow_the_history(client, admin_token):
    world = World(client, admin_token, "History Group Org")
    project = world.project()
    world.requirement(project, "Login")
    _log(project, "tag", "created")
    _log(project, "artefact_link", "created", {})
    _log(project, "project_stage", "created")

    by_group = _history(world, project, group="metadata:links")
    assert {e["entity_type"] for e in by_group} == {"artefact_link"}
    two_types = _history(world, project, entity_type=["tag", "project_stage"])
    assert {e["entity_type"] for e in two_types} == {"tag", "project_stage"}
    mixed = _history(world, project, entity_type="tag", group="metadata:links")
    assert {e["entity_type"] for e in mixed} == {"tag", "artefact_link"}
    core = _history(world, project, group=CORE_RECORDS_KEY)
    assert core and {e["entity_type"] for e in core} <= {"requirement", "change_request", "requirement_action"}


def test_a_known_group_with_no_events_matches_nothing_and_an_unknown_one_is_ignored(client, admin_token):
    world = World(client, admin_token, "History Unknown Org")
    project = world.project()
    _log(project, "tag", "created")
    assert _history(world, project, group="metadata:access") == []
    assert _history(world, project, group="metadata:not_a_group") == _history(world, project)
    assert _history(world, project, group="records:no_such_module") == _history(world, project)
    unknown_kind = world.client.get(
        f"/api/v1/projects/{project['id']}/changes", params={"kind": "nonsense"}, headers=auth_headers(world.token),
    )
    assert unknown_kind.status_code == 422


class _Statements:
    def __enter__(self):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._count)
        return self

    def _count(self, *_args):
        self.count += 1

    def __exit__(self, *_exc):
        event.remove(engine, "before_cursor_execute", self._count)


def test_the_statement_count_stays_flat_as_events_grow_with_a_group_filter(client, admin_token):
    world = World(client, admin_token, "History Flat Org")
    project = world.project()

    def log_many(count: int) -> None:
        for _ in range(count):
            _log(project, "artefact_link", "created", {})
            _log(project, "tag", "created")

    log_many(3)
    _history(world, project, group="metadata:links", kind="links")
    with _Statements() as few:
        _history(world, project, group="metadata:links", kind="links")
    log_many(30)
    with _Statements() as many:
        _history(world, project, group="metadata:links", kind="links")
    assert many.count == few.count


@pytest.mark.skipif(not TYPES_TS.exists(), reason="frontend sources are not available (backend-only image)")
def test_every_classified_action_has_a_label_in_the_frontend_label_map():
    """No raw action key reaches the Event column: each action the kinds map knows is worded in `ACTIVITY_ACTION_LABEL`."""
    from app.modules.registry import get_activity_action_kinds

    source = TYPES_TS.read_text()
    block = source[source.index("const ACTIVITY_ACTION_LABEL"):source.index("/** The kinds of activity event")]
    labelled = set(re.findall(r"^\s+([a-z_]+):", block, re.M))
    missing = (set(CORE_ACTION_KINDS) | set(get_activity_action_kinds())) - labelled
    assert not missing, f"add these to ACTIVITY_ACTION_LABEL (frontend/src/api/types.ts): {sorted(missing)}"
