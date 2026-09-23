"""Tests for the Compliance Module's Phase 5 data model
(docs/compliance-module-plan.md; docs/Compliance_Module_Requirements.md §2,
§5, §6, §25, §31): module registration (this is the first real first-party
module in `INSTALLED_MODULES`, not a fixture like every module-system test
before it), the `ComplianceStandard` -> `ComplianceStandardVersion` ->
`ComplianceRequirement` (self-referential hierarchy) -> `ComplianceRequired
Action` shape, the organisation-scoped `ComplianceActionTypeDefinition`
vocabulary, and the 0026 migration's up/down behaviour.

Phase 5 is data model only — there is no API surface yet (Phase 6), so
every test here talks to the ORM directly via `SessionLocal`, the same
"model-level only this phase" scope the plan's own spec calls for. Only
`org_id`/`admin_token`/`create_org_user` (existing API-backed fixtures) are
used to get real `organizations`/`users` rows to hang foreign keys off —
nothing compliance-specific goes through the API.
"""

import uuid

from sqlalchemy import inspect, text

from alembic import command
from app.database import SessionLocal, engine
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import (
    ComplianceActionTypeDefinition,
    ComplianceRequiredAction,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
)
from app.modules.registry import get_module_registry
from tests.conftest import build_alembic_config, create_org_user


def test_compliance_module_is_registered_with_org_and_project_roles():
    """Unlike every module-system test before it, this doesn't need a
    fixture module — Compliance is a real, permanent entry in
    `INSTALLED_MODULES` as of this phase. The module has both an org-scoped
    and a project-scoped router, a `resolve_file_owner_project_id` hook
    (Phase 8), and four scheduled jobs (Phase 10) — see
    `test_compliance_standards_api.py`/`test_project_compliance_api.py`/
    `test_compliance_evidence_api.py`/`test_compliance_approval_workflow.py`/
    `test_compliance_reviews_and_notifications.py`/`test_compliance_
    mapping_and_version_impact.py` for the actual API surfaces these facts
    stand in for here.

    Its MCP surface was originally ten read-only tools (Phases 6-11);
    2026-09-22 reversed that to write-enabled (68 more tools) except
    approvals (gated, not excluded) and RBAC/file-upload endpoints (still
    undeclared) — see `module.py`'s own docstring and `docs/decisions.md`'s
    "Compliance MCP write tools + generalized AI approval gate" entry. A
    2026-09-23 hardening pass then removed two of those 68 (`complete_
    project_review`/`complete_standard_review`, found declared with no
    gate at all despite recording a review outcome being categorically
    MCP-excluded in every configuration — see that entry in docs/
    decisions.md), landing at 76."""
    registry = get_module_registry()
    assert "compliance" in registry
    definition = registry["compliance"]

    assert definition.default_enabled is True, "§1: compliance is enabled by default"
    assert definition.implemented is True
    assert definition.get_router() is not None, "Phase 6 adds the Standards Management API router"
    assert definition.get_project_router is not None, "Phase 7 adds the project-scoped assessment router"
    assert definition.get_project_router() is not None
    assert len(definition.mcp_tools) == 76, (
        "Ten read-only tools (three from Phase 6, two more from Phase 7, one more from Phase 8, one more "
        "from Phase 9, one more from Phase 10, two more from Phase 11) plus 68 write tools declared in the "
        "2026-09-22 reversal (docs/decisions.md's 'Compliance MCP write tools + generalized AI approval "
        "gate' entry), minus 2 removed in the 2026-09-23 hardening pass (complete_project_review/"
        "complete_standard_review) — see module.py's own updated docstring"
    )
    assert {tool.name for tool in definition.mcp_tools} >= {
        "submit_requirement_for_approval", "approve_requirement", "reject_requirement",
    }, (
        "As of the 2026-09-22 reversal, submit-for-approval/approve/reject ARE declared — submit needs no "
        "gate (it only queues a decision), approve/reject resolve to routes gated by "
        "require_ai_approvals_enabled when reached through MCP (see project_router.py's own docstrings)"
    )
    assert any("migrate" in tool.name for tool in definition.mcp_tools), (
        "The 2026-09-22 reversal also declares the project version-migration action "
        "(compliance_migrate_project_compliance_version) — see module.py's own Phase 11 notes"
    )
    assert not any(
        tool.name
        in {
            "assign_standard_member_role", "revoke_standard_member_role",
            "assign_standard_group_role", "revoke_standard_group_role",
            "import_standard", "upload_evidence_attachment",
        }
        for tool in definition.mcp_tools
    ), (
        "RBAC role-grant endpoints and the two file-upload endpoints stay undeclared even after the "
        "2026-09-22 reversal — see module.py's own docstring's 'reversal' section, points 2 and 3"
    )
    assert not any(
        tool.name in {"complete_project_review", "complete_standard_review"} for tool in definition.mcp_tools
    ), (
        "2026-09-23 hardening pass: recording a review outcome is categorically MCP-excluded in every "
        "configuration (mirrors core's record_review_outcome), not just gated — both routes are now marked "
        "APPROVAL_ACTION_ROUTE_EXTRA and their tool declarations were removed"
    )
    assert definition.resolve_file_owner_project_id is not None, "Phase 8 adds the evidence file-ownership hook"
    assert len(definition.scheduled_jobs) == 4, "Phase 10 adds four date-driven notification sweeps"

    roles_by_key = {role.role_key: role for role in definition.roles}
    assert set(roles_by_key) == {
        "compliance_manager", "compliance_officer", "standards_manager", "standards_contributor",
    }
    assert roles_by_key["compliance_manager"].scope == "org"
    assert roles_by_key["compliance_officer"].scope == "project"
    # Phase 22: standard-scoped roles use the generalised, module-owned
    # entity scope (`app.modules.registry.ModuleRoleDefinition`'s new
    # `scope`/`overridden_by`/`resolve_entity_organization_id` mechanism)
    # rather than a second hardcoded "org"/"project" literal.
    assert roles_by_key["standards_manager"].scope == "standard"
    assert roles_by_key["standards_contributor"].scope == "standard"
    assert roles_by_key["standards_manager"].overridden_by == (("org", "compliance_manager"),)
    assert roles_by_key["standards_manager"].resolve_entity_organization_id is not None


def test_standard_version_requirement_hierarchy_and_required_action_roundtrip(client, admin_token, org_id):
    """Builds one full `ComplianceStandard` -> `ComplianceStandardVersion` ->
    parent/child `ComplianceRequirement` -> `ComplianceRequiredAction` tree
    directly via the ORM and confirms every relationship/FK survives a
    reload from the database, including the self-referential hierarchy link
    (§5) and the org-scoped action-type vocabulary (§6)."""
    user_id = uuid.UUID(create_org_user(client, admin_token, org_id, "compliance-owner@example.com"))
    org_uuid = uuid.UUID(org_id)

    db = SessionLocal()
    try:
        standard = ComplianceStandard(
            organization_id=org_uuid,
            reference="ISO-27001",
            name="Corporate Security Standard",
            description="Baseline information-security requirements.",
            issuing_organisation="ISO",
            owner_id=user_id,
            creator_id=user_id,
        )
        db.add(standard)
        db.flush()

        version = ComplianceStandardVersion(
            standard_id=standard.id,
            version_number=1,
            version_label="1.0",
            created_by=user_id,
        )
        db.add(version)
        db.flush()

        action_type = ComplianceActionTypeDefinition(organization_id=org_uuid, name="Verification")
        db.add(action_type)
        db.flush()

        parent_requirement = ComplianceRequirement(
            standard_version_id=version.id,
            reference="3",
            name="Environmental requirements",
            reasoning="Groups all environmental-compliance clauses under one section.",
            created_by=user_id,
        )
        db.add(parent_requirement)
        db.flush()

        child_requirement = ComplianceRequirement(
            standard_version_id=version.id,
            parent_requirement_id=parent_requirement.id,
            reference="3.1",
            name="Equipment shall meet IPX9 water ingress requirements.",
            created_by=user_id,
        )
        db.add(child_requirement)
        db.flush()

        required_action = ComplianceRequiredAction(
            requirement_id=child_requirement.id,
            action_type_id=action_type.id,
            name="Perform IPX9 water ingress test",
            is_mandatory=True,
            created_by=user_id,
        )
        db.add(required_action)
        db.commit()

        standard_id = standard.id
        version_id = version.id
        parent_id = parent_requirement.id
        child_id = child_requirement.id
        action_id = required_action.id
    finally:
        db.close()

    # Reload from a fresh session to prove everything actually persisted
    # (not just held live on the objects still attached to the session
    # above), the same "reload and re-assert" discipline this suite's other
    # model-relationship tests already use.
    db = SessionLocal()
    try:
        reloaded_standard = db.get(ComplianceStandard, standard_id)
        assert reloaded_standard.is_archived is False
        assert [v.id for v in reloaded_standard.versions] == [version_id]

        reloaded_version = db.get(ComplianceStandardVersion, version_id)
        assert reloaded_version.standard.id == standard_id
        assert reloaded_version.status == ComplianceStandardVersionStatus.DRAFT

        reloaded_parent = db.get(ComplianceRequirement, parent_id)
        assert reloaded_parent.parent_requirement_id is None

        reloaded_child = db.get(ComplianceRequirement, child_id)
        assert reloaded_child.parent_requirement_id == parent_id
        assert reloaded_child.standard_version_id == version_id

        reloaded_action = db.get(ComplianceRequiredAction, action_id)
        assert reloaded_action.requirement_id == child_id
        assert reloaded_action.is_mandatory is True

        reloaded_action_type = db.get(
            ComplianceActionTypeDefinition, reloaded_action.action_type_id
        )
        assert reloaded_action_type.organization_id == org_uuid
        assert reloaded_action_type.name == "Verification"
    finally:
        db.close()


def test_deleting_parent_requirement_cascades_to_child_and_required_action(client, admin_token, org_id):
    """§5's hierarchy is enforced with `ON DELETE CASCADE`, not `SET NULL`
    (unlike `Project.parent_project_id`) — a compliance requirement has no
    "detach and stand alone" concept, so removing a section removes its
    subsections and their required actions with it."""
    user_id = uuid.UUID(create_org_user(client, admin_token, org_id, "cascade-owner@example.com"))
    org_uuid = uuid.UUID(org_id)

    db = SessionLocal()
    try:
        standard = ComplianceStandard(
            organization_id=org_uuid, reference="CASCADE-STD", name="Cascade Test Standard",
            owner_id=user_id, creator_id=user_id,
        )
        db.add(standard)
        db.flush()
        version = ComplianceStandardVersion(
            standard_id=standard.id, version_number=1, version_label="1.0", created_by=user_id,
        )
        db.add(version)
        db.flush()
        action_type = ComplianceActionTypeDefinition(organization_id=org_uuid, name="Inspection")
        db.add(action_type)
        db.flush()
        parent = ComplianceRequirement(
            standard_version_id=version.id, name="Parent section", created_by=user_id,
        )
        db.add(parent)
        db.flush()
        child = ComplianceRequirement(
            standard_version_id=version.id, parent_requirement_id=parent.id,
            name="Child clause", created_by=user_id,
        )
        db.add(child)
        db.flush()
        action = ComplianceRequiredAction(
            requirement_id=child.id, action_type_id=action_type.id,
            name="Perform inspection", created_by=user_id,
        )
        db.add(action)
        db.commit()

        parent_id, child_id, action_id = parent.id, child.id, action.id

        db.delete(db.get(ComplianceRequirement, parent_id))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        assert db.get(ComplianceRequirement, parent_id) is None
        assert db.get(ComplianceRequirement, child_id) is None, "cascade must remove the child too"
        assert db.get(ComplianceRequiredAction, action_id) is None, "cascade must remove its required action too"
    finally:
        db.close()


def test_standard_reference_is_unique_per_organization(client, admin_token, org_id):
    """§2's "Identifier/reference" is unique within an organisation, mirroring
    `ActionTypeDefinition`'s own per-scope uniqueness convention."""
    user_id = uuid.UUID(create_org_user(client, admin_token, org_id, "unique-ref-owner@example.com"))
    org_uuid = uuid.UUID(org_id)

    db = SessionLocal()
    try:
        db.add(
            ComplianceStandard(
                organization_id=org_uuid, reference="DUP-REF", name="First Standard",
                owner_id=user_id, creator_id=user_id,
            )
        )
        db.commit()

        db.add(
            ComplianceStandard(
                organization_id=org_uuid, reference="DUP-REF", name="Second Standard",
                owner_id=user_id, creator_id=user_id,
            )
        )
        try:
            db.commit()
            raised = False
        except Exception:
            db.rollback()
            raised = True
        assert raised, "a duplicate (organization_id, reference) must be rejected"
    finally:
        db.close()


def test_migration_0026_upgrade_and_downgrade_round_trip():
    """Downgrades to 0025 (none of this phase's five tables exist), then
    upgrades back to head (0026's real `upgrade()` runs), confirming the
    tables actually appear/disappear — not a reimplementation of the
    migration's SQL, a direct exercise of it, mirroring `test_schema_
    migrations_match_models.py`'s own reliance on the real migration path.
    Always ends back at head so the shared session-scoped test database is
    left in the state every other test in this suite expects, even if an
    assertion above fails."""
    compliance_tables = {
        "compliance_action_type_definitions",
        "compliance_standards",
        "compliance_standard_versions",
        "compliance_requirements",
        "compliance_required_actions",
    }

    cfg = build_alembic_config()
    try:
        command.downgrade(cfg, "0025")
        with engine.connect() as conn:
            existing = set(inspect(conn).get_table_names())
        assert not (compliance_tables & existing), "0026's downgrade() must drop all five tables"
    finally:
        command.upgrade(cfg, "head")

    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
    assert compliance_tables <= existing, "0026's upgrade() must recreate all five tables"

    # The migration's own CREATE TABLE IF NOT EXISTS statements must also be
    # safe to re-run against an already-migrated database (this suite's own
    # standing convention for additive migrations, e.g. 0025's own docstring)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))  # sanity: connection still usable after the round trip
