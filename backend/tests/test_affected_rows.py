"""`services.lookups.affected_rows` narrows the result of an UPDATE or DELETE to its row count, and refuses a result
that is not one (a SELECT), so a caller never reads a count off the general result type."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update

from app.database import SessionLocal
from app.models.user import User
from app.services.lookups import affected_rows


def test_the_count_of_an_update_and_a_delete_is_the_rows_they_changed():
    with SessionLocal() as db:
        none = uuid.uuid4()
        assert affected_rows(db.execute(update(User).where(User.id == none).values(display_name="x"))) == 0
        assert affected_rows(db.execute(delete(User).where(User.id == none))) == 0
        db.rollback()


def test_a_select_result_is_refused():
    with SessionLocal() as db:
        with pytest.raises(TypeError):
            affected_rows(db.execute(select(User).limit(1)))
