"""Review comments are looked up by their target, so the table carries an index for it.

The PostgreSQL profile showed a sequential scan of `review_comments` for every comment count on a requirement list
page (the table has no other index on the target). This pins the index, and that the planner can use it for the
exact filter the list and comment endpoints apply, so the migration cannot be dropped without a failing test.
"""

from sqlalchemy import text

from app.database import SessionLocal


def test_review_comments_are_indexed_by_target_and_the_planner_can_use_it():
    db = SessionLocal()
    try:
        columns = (
            db.execute(
                text(
                    "select a.attname from pg_index i join pg_class c on c.oid = i.indexrelid "
                    "join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
                    "where c.relname = 'ix_review_comments_target' order by array_position(i.indkey::int2[], a.attnum)"
                )
            )
            .scalars()
            .all()
        )
        assert columns == ["target_type", "target_id"]
        db.execute(text("set local enable_seqscan = off"))
        plan = "\n".join(
            db.execute(
                text(
                    "explain select target_id, count(id) from review_comments "
                    "where target_type = 'requirement' and target_id in ('00000000-0000-0000-0000-000000000001') group by target_id"
                )
            ).scalars()
        )
        assert "ix_review_comments_target" in plan
    finally:
        db.rollback()
        db.close()
