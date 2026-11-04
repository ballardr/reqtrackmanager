"""Tests for storing and versioning report layouts (`services.report_layouts`).

Covers creation (version 1, validation, names per owner), appending versions, the unchanged-save
shortcut, optimistic concurrency, immutability of saved versions, audit events that never carry the
layout's text, and cascade deletion with the owner. Each test builds its own organisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.services import report_layouts
from app.services.report_layout_tree import InvalidLayoutError, empty_tree
from app.services.report_layouts import LayoutConflictError, LayoutNameTakenError
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Layouts Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def tree(text: str = "Hello") -> dict:
    return {**empty_tree("document"), "nodes": [{"type": "heading", "text": text}]}


def make(db, world, *, project=None, name="Gap report", family="document", body=None):
    saved = report_layouts.create_layout(
        db, organization_id=uuid.UUID(world.org["id"]), project_id=uuid.UUID(project["id"]) if project else None,
        name=name, description="d", family=family, tree=body or tree(), actor_id=world.user_id,
    )
    db.commit()
    return saved


def test_create_stores_the_layout_and_its_first_version(world, db):
    saved = make(db, world)

    assert saved.changed and saved.layout.current_version == 1 and saved.version.version == 1
    assert saved.version.tree == tree() and len(saved.version.tree_hash) == 64 and saved.version.schema_version == 1
    assert saved.layout.project_id is None and saved.layout.created_by == world.user_id


def test_an_invalid_tree_stores_nothing(world, db):
    with pytest.raises(InvalidLayoutError):
        make(db, world, body={**empty_tree("document"), "nodes": [{"type": "nope"}]})
    db.rollback()

    assert db.scalars(select(ReportLayout).where(ReportLayout.organization_id == uuid.UUID(world.org["id"]))).all() == []


def test_the_tree_must_match_the_family(world, db):
    with pytest.raises(InvalidLayoutError):
        make(db, world, family="table")  # a document tree


@pytest.mark.parametrize(("name", "family"), [("", "document"), ("  ", "document"), ("x" * 201, "document"), ("ok", "slides")])
def test_a_bad_name_or_family_is_refused(world, db, name, family):
    with pytest.raises(ValueError):
        make(db, world, name=name, family=family)


def test_a_name_is_unique_per_owner_ignoring_case(world, db):
    project, other = world.project("Mine"), world.project("Other")
    make(db, world, name="Gap report")

    with pytest.raises(LayoutNameTakenError):
        make(db, world, name="  GAP REPORT ")
    # The same name under a project, or another project, is a different owner.
    make(db, world, project=project, name="Gap report")
    make(db, world, project=other, name="Gap report")
    with pytest.raises(LayoutNameTakenError):
        make(db, world, project=project, name="gap report")


def test_a_failed_create_leaves_the_callers_other_work_alone(world, db):
    make(db, world, name="Taken")
    db.add(AuditEvent(entity_type="probe", entity_id="1", action="x", actor_id=None, detail=None, created_at=datetime.now(UTC)))
    with pytest.raises(LayoutNameTakenError):
        report_layouts.create_layout(
            db, organization_id=uuid.UUID(world.org["id"]), project_id=None, name="Taken", description="",
            family="document", tree=tree(), actor_id=world.user_id,
        )
    db.commit()

    assert db.scalar(select(AuditEvent).where(AuditEvent.entity_type == "probe")) is not None


def test_a_project_of_another_organisation_is_refused(client, admin_token, world, db):
    foreign = World(client, admin_token, "Foreign Org").project("Theirs")
    with pytest.raises(ValueError, match="does not belong"):
        report_layouts.create_layout(
            db, organization_id=uuid.UUID(world.org["id"]), project_id=uuid.UUID(foreign["id"]), name="X", description="",
            family="document", tree=tree(), actor_id=world.user_id,
        )


def test_saving_appends_a_version_and_keeps_the_old_one(world, db):
    saved = make(db, world)

    second = report_layouts.save_version(db, saved.layout.id, tree("Changed"), base_version=1, actor_id=world.user_id, comment="retitle")
    db.commit()

    assert second.changed and second.version.version == 2 and second.layout.current_version == 2
    assert second.version.comment == "retitle"
    versions = report_layouts.list_versions(db, saved.layout.id)
    assert [v.version for v in versions] == [2, 1]
    assert report_layouts.get_version(db, saved.layout.id, 1).tree == tree()
    assert report_layouts.get_version(db, saved.layout.id, 9) is None


def test_an_unchanged_save_stores_no_new_version(world, db):
    saved = make(db, world)

    again = report_layouts.save_version(db, saved.layout.id, tree(), base_version=1, actor_id=world.user_id)
    db.commit()

    assert not again.changed and again.version.version == 1
    assert len(report_layouts.list_versions(db, saved.layout.id)) == 1


def test_a_save_based_on_an_old_version_is_refused(world, db):
    saved = make(db, world)
    report_layouts.save_version(db, saved.layout.id, tree("Mine"), base_version=1, actor_id=world.user_id)
    db.commit()

    with pytest.raises(LayoutConflictError) as caught:
        report_layouts.save_version(db, saved.layout.id, tree("Theirs"), base_version=1, actor_id=world.user_id)

    assert caught.value.current_version == 2
    db.rollback()
    assert report_layouts.get_version(db, saved.layout.id, 3) is None


def test_an_invalid_save_changes_nothing(world, db):
    saved = make(db, world)
    with pytest.raises(InvalidLayoutError):
        report_layouts.save_version(db, saved.layout.id, {**tree(), "nodes": [{"type": "heading"}]}, base_version=1, actor_id=world.user_id)
    db.rollback()

    assert db.get(ReportLayout, saved.layout.id).current_version == 1


def test_saving_an_unknown_layout_is_a_lookup_error(db, world):
    with pytest.raises(LookupError):
        report_layouts.save_version(db, uuid.uuid4(), tree(), base_version=1, actor_id=world.user_id)


def test_a_saved_version_cannot_be_rewritten(world, db):
    saved = make(db, world)
    version = db.get(ReportLayoutVersion, saved.version.id)
    version.tree = tree("Tampered")

    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_rename_and_describe_do_not_make_a_version(world, db):
    saved = make(db, world, name="Old")
    make(db, world, name="Taken")

    report_layouts.update_details(db, saved.layout, name="New", description="new text", actor_id=world.user_id)
    db.commit()
    assert (saved.layout.name, saved.layout.description, saved.layout.current_version) == ("New", "new text", 1)
    with pytest.raises(LayoutNameTakenError):
        report_layouts.update_details(db, saved.layout, name="taken", actor_id=world.user_id)
    # Renaming to its own name in another case is allowed.
    report_layouts.update_details(db, saved.layout, name="NEW", actor_id=world.user_id)
    assert saved.layout.name == "NEW"


def test_every_change_is_audited_without_the_layouts_text(world, db):
    saved = make(db, world, body=tree("Confidential wording"))
    report_layouts.save_version(db, saved.layout.id, tree("More confidential wording"), base_version=1, actor_id=world.user_id)
    report_layouts.update_details(db, saved.layout, name="Renamed", actor_id=world.user_id)
    report_layouts.delete_layout(db, saved.layout, actor_id=world.user_id)
    db.commit()

    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(saved.layout.id)).order_by(AuditEvent.created_at)).all()
    assert [e.action for e in events] == ["created", "version_saved", "updated", "deleted"]
    assert all(e.entity_type == "report_layout" and e.actor_id == world.user_id for e in events)
    assert all(e.organization_id == uuid.UUID(world.org["id"]) for e in events)
    assert "confidential" not in " ".join(str(e.detail) for e in events).casefold()
    assert events[1].detail["version"] == 2 and events[1].detail["blocks"] == 1


def test_deleting_a_layout_removes_its_versions(world, db):
    saved = make(db, world)
    report_layouts.save_version(db, saved.layout.id, tree("Two"), base_version=1, actor_id=world.user_id)
    db.commit()

    report_layouts.delete_layout(db, saved.layout, actor_id=world.user_id)
    db.commit()

    assert report_layouts.list_versions(db, saved.layout.id) == []


def test_deleting_the_owner_removes_the_layouts(client, admin_token, db):
    world = World(client, admin_token, "Cascade Org")
    project = world.project("Doomed")
    layout_id = make(db, world, project=project).layout.id
    org_layout_id = make(db, world, name="Org level").layout.id

    db.execute(ReportLayout.__table__.delete().where(ReportLayout.project_id == uuid.UUID(project["id"])))
    db.commit()
    assert db.get(ReportLayout, layout_id) is None and db.get(ReportLayout, org_layout_id) is not None

    project2 = world.project("Doomed too")
    kept = make(db, world, project=project2, name="Goes with project").layout.id
    db.execute(Project.__table__.delete().where(Project.id == uuid.UUID(project2["id"])))
    db.commit()
    db.expire_all()
    assert db.get(ReportLayout, kept) is None
