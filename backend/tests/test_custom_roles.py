"""Tests for Fine-Grained Access Control's Phase 1 data model
(`docs/plans/core-fine-grained-access-control-plan.md`): the
`CustomRoleDefinition`/`CustomRolePermission`/`UserCustomRoleGrant`/
`GroupCustomRoleGrant` tables, the permission-atom vocabulary
(`app.services.permissions`), and the new sub-type-provider registry
(`app.modules.registry.get_subtype_providers`/`get_subtypes`) — including
Decision Management's own registration, this phase's "real consumer on day
one" (Phase 1 scope).

Phase 2 (`require_permission`/`get_effective_permissions`) doesn't exist
yet, so nothing here exercises an actual authorization decision — only that
the vocabulary and storage this phase builds behave as designed.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.custom_role import (
    CustomRoleDefinition,
    CustomRolePermission,
    GroupCustomRoleGrant,
    UserCustomRoleGrant,
)
from app.models.enums import PermissionLevel
from app.modules.decisions.service import DEFAULT_DECISION_TYPES
from app.modules.registry import get_subtype_providers, get_subtypes
from app.services.permissions import (
    ADMINISTRATIVE_PERMISSIONS,
    encode_permission,
    get_all_permissions,
    validate_permission_key,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project


def test_custom_role_definition_unique_per_org_name(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Custom Role Uniqueness Org")
    db = SessionLocal()
    try:
        db.add(CustomRoleDefinition(organization_id=org["id"], name="Reviewer", description="", scope="org"))
        db.flush()
        db.add(CustomRoleDefinition(organization_id=org["id"], name="Reviewer", description="", scope="org"))
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_custom_role_permission_unique_per_role(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Custom Role Permission Uniqueness Org")
    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org["id"], name="Reviewer", description="", scope="org")
        db.add(role)
        db.flush()
        permission = encode_permission("requirement", PermissionLevel.VIEW.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_user_and_group_custom_role_grants_round_trip(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Grant Org")
    project = create_project(client, org_admin_token, org["id"])
    group = client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Reviewers"}, headers=auth_headers(org_admin_token)
    ).json()

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org["id"], name="Reviewer", description="", scope="project")
        db.add(role)
        db.flush()

        user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(org_admin_token)).json()["id"])
        user_grant = UserCustomRoleGrant(
            user_id=user_id, custom_role_id=role.id, organization_id=org["id"], project_id=project["id"],
        )
        group_grant = GroupCustomRoleGrant(
            org_group_id=group["id"], custom_role_id=role.id, organization_id=org["id"], project_id=project["id"],
        )
        db.add_all([user_grant, group_grant])
        db.commit()

        # Duplicate (user, role, project) is rejected...
        with db.begin_nested():
            db.add(
                UserCustomRoleGrant(
                    user_id=user_id, custom_role_id=role.id, organization_id=org["id"], project_id=project["id"],
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()

        # ...but the same user/role is fine at a *different* scope (org-wide, no project_id).
        db.add(UserCustomRoleGrant(user_id=user_id, custom_role_id=role.id, organization_id=org["id"]))
        db.flush()
    finally:
        db.rollback()
        db.close()


def test_get_all_permissions_includes_administrative_and_artefact_atoms(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Permission Vocabulary Org")
    db = SessionLocal()
    try:
        permissions = get_all_permissions(db, uuid.UUID(org["id"]))
    finally:
        db.close()

    keys = {p.key for p in permissions}
    for admin_key in ADMINISTRATIVE_PERMISSIONS:
        assert admin_key in keys

    # A pure-VIEW atom exists independently of any write tier (Phase 0 Q1).
    view_key = encode_permission("requirement", PermissionLevel.VIEW.value)
    assert view_key in keys
    manage_key = encode_permission("requirement", PermissionLevel.MANAGE.value)
    assert manage_key in keys
    assert view_key != manage_key

    # No sub-type provider is registered for "requirement", so only the
    # wildcard (empty-string) atom exists for it, never a specific sub-type.
    assert not any(p.artefact_type == "requirement" and p.subtype for p in permissions)


def test_validate_permission_key_accepts_valid_and_rejects_invalid(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Permission Validation Org")
    db = SessionLocal()
    try:
        validate_permission_key(db, uuid.UUID(org["id"]), "grant_roles")
        validate_permission_key(db, uuid.UUID(org["id"]), encode_permission("requirement", PermissionLevel.VIEW.value))
        with pytest.raises(ValueError):
            validate_permission_key(db, uuid.UUID(org["id"]), "not_a_real_permission")
        with pytest.raises(ValueError):
            # "Architecture" isn't a registered sub-type for "requirement" (no provider).
            validate_permission_key(
                db, uuid.UUID(org["id"]), encode_permission("requirement", PermissionLevel.VIEW.value, "Architecture")
            )
    finally:
        db.close()


def test_decision_management_registers_a_subtype_provider(client, admin_token):
    """Decision Management's `subtype_providers["decision"]` registration
    (Phase 1's "real consumer on day one") is live in the merged registry,
    and returns that organisation's actual current Decision Type names."""
    assert "decision" in get_subtype_providers()

    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision Subtype Provider Org")
    create_project(client, org_admin_token, org["id"])  # seeds the 5 default decision types (root project)

    db = SessionLocal()
    try:
        subtypes = get_subtypes(db, uuid.UUID(org["id"]), "decision")
    finally:
        db.close()

    assert subtypes == sorted(DEFAULT_DECISION_TYPES)


def test_get_subtypes_returns_empty_for_unregistered_artefact_type(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "No Subtype Provider Org")
    db = SessionLocal()
    try:
        assert get_subtypes(db, uuid.UUID(org["id"]), "requirement") == []
    finally:
        db.close()


def test_decision_permission_vocabulary_includes_org_decision_types(client, admin_token):
    """`get_all_permissions` folds Decision Management's own sub-type
    provider in for the "decision" artefact type, once at least one
    project in the org has Decision Types (seeded on the first project)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision Permission Vocabulary Org")
    create_project(client, org_admin_token, org["id"])

    db = SessionLocal()
    try:
        permissions = get_all_permissions(db, uuid.UUID(org["id"]))
    finally:
        db.close()

    decision_subtype_keys = {p.key for p in permissions if p.artefact_type == "decision" and p.subtype}
    assert encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value, "Architecture") in decision_subtype_keys
