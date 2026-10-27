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
        record = "\n".join(db.execute(text(
            "explain select * from audit_events where entity_type = 'requirement' and entity_id = '00000000-0000-0000-0000-000000000001'"
        )).scalars())
        assert "ix_audit_events_entity" in record
        project = "\n".join(db.execute(text(
            "explain select * from audit_events where project_id = '00000000-0000-0000-0000-000000000001' and entity_type = 'artefact_link'"
        )).scalars())
        assert "ix_audit_events_project_type" in project
    finally:
        db.rollback()
        db.close()
