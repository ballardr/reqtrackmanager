"""Tests that the row locks the application takes to serialise work do not also block foreign-key checks.

A `FOR UPDATE` lock on a project conflicts with the `KEY SHARE` lock every insert referencing the project takes, so while one
request held it (every create takes it to number the new record) every other insert for the project, an audit event or a
comment, waited too. `FOR NO KEY UPDATE` keeps two lockers exclusive without that. Two sessions, a short lock timeout.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.services.rbac import lock_organization_for_update, lock_project_for_update, lock_row_for_update
from tests.conftest import create_org_admin_in, create_project


def _audit_event(organization_id, project_id) -> AuditEvent:
    return AuditEvent(entity_type="requirement", entity_id=uuid.uuid4(), action="created", organization_id=organization_id,
                      project_id=project_id, created_at=datetime.now(UTC))


def _short_lock_timeout(db) -> None:
    db.execute(text("SET LOCAL lock_timeout = '400ms'"))


def test_a_project_lock_does_not_block_inserts_that_reference_the_project_but_excludes_another_lock(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Lock Level Co")
    project = create_project(client, token, org["id"], "Lock Level Project")
    project_id, organization_id = uuid.UUID(project["id"]), uuid.UUID(org["id"])

    holder, other = SessionLocal(), SessionLocal()
    try:
        lock_project_for_update(holder, project_id)

        _short_lock_timeout(other)
        other.add(_audit_event(organization_id, project_id))
        other.flush()  # takes KEY SHARE on the project row: must not wait for the holder
        other.rollback()

        _short_lock_timeout(other)
        with pytest.raises(OperationalError):
            lock_project_for_update(other, project_id)  # the guard and the counter still exclude each other
        other.rollback()
    finally:
        holder.rollback()
        holder.close()
        other.close()


def test_organisation_and_row_locks_are_also_compatible_with_foreign_key_checks(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Row Lock Co")
    project = create_project(client, token, org["id"], "Row Lock Project")
    organization_id, project_id = uuid.UUID(org["id"]), uuid.UUID(project["id"])
    from app.models.project import Project

    holder, other = SessionLocal(), SessionLocal()
    try:
        lock_organization_for_update(holder, organization_id)
        lock_row_for_update(holder, Project, project_id)
        _short_lock_timeout(other)
        other.add(_audit_event(organization_id, project_id))
        other.flush()
        other.rollback()
        _short_lock_timeout(other)
        with pytest.raises(OperationalError):
            lock_row_for_update(other, Project, project_id)
        other.rollback()
    finally:
        holder.rollback()
        holder.close()
        other.close()
