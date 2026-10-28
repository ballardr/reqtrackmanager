"""The audit trail is indexed for the lookups the activity timeline and the change feed make.

The PostgreSQL profile showed a sequential scan of `audit_events` for each of the three statements an activity request
runs. This pins both indexes and that the planner can use each for its filter, so a migration cannot drop them silently.
"""

from sqlalchemy import text

from app.database import SessionLocal


def _columns(db, index: str) -> list[str]:
    return list(db.execute(text(
        "select a.attname from pg_index i join pg_class c on c.oid = i.indexrelid "
        "join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
        "where c.relname = :name order by array_position(i.indkey::int2[], a.attnum)"
    ), {"name": index}).scalars())


def test_audit_events_are_indexed_by_record_and_by_project_and_the_planner_can_use_them():
    db = SessionLocal()
    try:
        assert _columns(db, "ix_audit_events_entity") == ["entity_type", "entity_id"]
        assert _columns(db, "ix_audit_events_project_type") == ["project_id", "entity_type", "created_at"]
        db.execute(text("set local enable_seqscan = off"))
        # With a nearly empty table the planner may pick either index for either filter, so each is proved usable on its
        # own: the other index is dropped inside this transaction, which is rolled back.
        db.execute(text("drop index ix_audit_events_project_type"))
        record = "\n".join(db.execute(text(
            "explain select * from audit_events where entity_type = 'requirement' and entity_id = '00000000-0000-0000-0000-000000000001'"
        )).scalars())
        assert "ix_audit_events_entity" in record
        db.rollback()
        db.execute(text("set local enable_seqscan = off"))
        db.execute(text("drop index ix_audit_events_entity"))
        db.execute(text("drop index ix_audit_events_project_entity"))
        project = "\n".join(db.execute(text(
            "explain select * from audit_events where project_id = '00000000-0000-0000-0000-000000000001' and entity_type = 'requirement'"
        )).scalars())
        assert "ix_audit_events_project_type" in project
    finally:
        db.rollback()
        db.close()


def test_an_activity_timelines_link_event_lookup_uses_the_expression_indexes():
    """The generic link events are found by the ids kept in `detail`, not by reading every link event of the project."""
    db = SessionLocal()
    try:
        db.execute(text("set local enable_seqscan = off"))
        db.execute(text("drop index ix_audit_events_project_type"))
        db.execute(text("drop index ix_audit_events_entity"))
        for side in ("source", "target"):
            # With an almost empty table the planner may use one index for both sides, so each is proved on its own.
            other = "target" if side == "source" else "source"
            db.execute(text(f"drop index if exists ix_audit_events_link_{other}"))
            plan = "\n".join(db.execute(text(
                f"explain select * from audit_events where entity_type = 'artefact_link' "
                f"and (detail ->> '{side}_id') = '00000000-0000-0000-0000-000000000001'"
            )).scalars())
            assert f"ix_audit_events_link_{side}" in plan, plan
            db.rollback()
            db.execute(text("set local enable_seqscan = off"))
            db.execute(text("drop index ix_audit_events_project_type"))
            db.execute(text("drop index ix_audit_events_entity"))
    finally:
        db.rollback()
        db.close()


def test_a_records_change_history_lookup_by_project_and_record_id_uses_its_index():
    db = SessionLocal()
    try:
        assert _columns(db, "ix_audit_events_project_entity") == ["project_id", "entity_id"]
        db.execute(text("set local enable_seqscan = off"))
        db.execute(text("drop index ix_audit_events_project_type"))
        db.execute(text("drop index ix_audit_events_entity"))
        plan = "\n".join(db.execute(text(
            "explain select * from audit_events where project_id = '00000000-0000-0000-0000-000000000001' "
            "and entity_id = '00000000-0000-0000-0000-000000000002'"
        )).scalars())
        assert "ix_audit_events_project_entity" in plan, plan
    finally:
        db.rollback()
        db.close()


def test_every_legacy_link_event_type_is_listed():
    """The activity timeline finds the older per-pair link events by a closed list of types (so it can use the project and
    type index). A router that logs another `*_link` entity type would silently drop out of the timeline: list it."""
    import re
    from pathlib import Path

    from app.services.record_activity import LEGACY_LINK_EVENT_TYPES

    app_dir = Path(__file__).resolve().parents[1] / "app"
    logged = set()
    for path in app_dir.rglob("*.py"):
        if "/tests/" in str(path):
            continue
        logged |= set(re.findall(r'entity_type="([a-z_]+_link)"', path.read_text()))
    logged.discard("artefact_link")  # the generic link event is read by its own query
    assert logged <= set(LEGACY_LINK_EVENT_TYPES), sorted(logged - set(LEGACY_LINK_EVENT_TYPES))
    assert set(LEGACY_LINK_EVENT_TYPES) <= logged | {"requirement_link", "requirement_action_link"}, "a listed type nothing logs"
