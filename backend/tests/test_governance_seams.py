"""Tests for the module registration points the governance engine seams read (`modules.seams`,
`services.governance_seams`): policy resolvers, baseline check providers, review adapters and record sub-type
resolvers, including the rule that a registration applies only while its module (and named sub-component) is in effect
and the `ModuleDefinition` validation of what a registration names.

Uses a fake module with a sub-component pair, so the suite does not depend on the Traceability module's content."""

import uuid as uuid_lib
from datetime import date

import pytest

from app.database import SessionLocal
from app.models.module import OrganizationModuleSubComponentDefault
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleSubComponentDefinition,
    build_registry,
    get_record_subtype_resolvers,
    resolve_record_subtypes,
)
from app.modules.seams import (
    BaselineCheckContext,
    BaselineCheckFailure,
    BaselineCheckProvider,
    DueReview,
    GovernanceSeam,
    PolicyResolver,
    ReviewAdapter,
)
from app.services import governance_seams
from tests.conftest import auth_headers, create_project

KEY = "fake_seams_test_module"
RECORD_ID = uuid_lib.UUID("00000000-0000-0000-0000-0000000000aa")


def _lifecycle_policy(db, project_id, artefact_type):
    return {"seam": "lifecycle", "type": artefact_type} if artefact_type == "decision" else None


def _approval_policy(db, project_id, artefact_type):
    return "approval-policy"


def _check(db, context, record_ids):
    return [
        BaselineCheckFailure(artefact_type=t, artefact_id=i, check_key="fake_check", message="Missing a link.")
        for t, ids in record_ids.items() for i in ids
    ]


def _due(db, project_id, as_of):
    return [DueReview(artefact_id=RECORD_ID, due_on=as_of)]


def _subtypes(db, project_id, record_ids):
    return {record_id: "Verification" for record_id in record_ids}


def _definition(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=KEY, name="Fake Seams Module", description="Fixture for the seam tests.", version="0.0.1",
        default_enabled=True, implemented=False, get_router=lambda: None,
        sub_components=(
            ModuleSubComponentDefinition(key="policies", name="Policies"),
            ModuleSubComponentDefinition(key="checks", name="Checks"),
        ),
        policy_resolvers=(
            PolicyResolver(seam=GovernanceSeam.LIFECYCLE, resolve=_lifecycle_policy, sub_component="policies"),
            PolicyResolver(seam=GovernanceSeam.APPROVAL, resolve=_approval_policy),
        ),
        baseline_check_providers=(
            BaselineCheckProvider(key="fake_check", name="Fake check", artefact_types=("decision",), check=_check, sub_component="checks"),
        ),
        review_adapters={"decision": ReviewAdapter(schedule="review_record", due_reviews=_due)},
        record_subtypes={"decision": _subtypes},
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    module_registry.INSTALLED_MODULES.append(_definition())
    build_registry(force=True)
    yield KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != KEY]
    build_registry(force=True)


# --- declaration validation ------------------------------------------------------------


def test_a_registration_cannot_name_an_undeclared_sub_component():
    with pytest.raises(ValueError, match="undeclared sub-component"):
        _definition(policy_resolvers=(PolicyResolver(seam=GovernanceSeam.REVIEW, resolve=_approval_policy, sub_component="nope"),))
    with pytest.raises(ValueError, match="undeclared sub-component"):
        _definition(
            baseline_check_providers=(
                BaselineCheckProvider(key="x", name="X", artefact_types=("decision",), check=_check, sub_component="nope"),
            )
        )


def test_duplicate_baseline_check_keys_are_rejected():
    provider = BaselineCheckProvider(key="dup", name="Dup", artefact_types=("decision",), check=_check)
    with pytest.raises(ValueError, match="duplicate baseline check"):
        _definition(baseline_check_providers=(provider, provider))


# --- policy resolution -----------------------------------------------------------------


def test_policy_resolution_asks_only_resolvers_in_effect(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Policy Project")["id"])
    db = SessionLocal()
    try:
        # The resolver bound to `policies` answers for the type it knows and defers (`None`) for the rest.
        policy = governance_seams.resolve_policy(db, project_id, GovernanceSeam.LIFECYCLE, "decision")
        assert policy == {"seam": "lifecycle", "type": "decision"}
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.LIFECYCLE, "risk") is None
        # A seam with a resolver bound to the whole module answers while the module is on.
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.APPROVAL, "decision") == "approval-policy"
        # No resolver registered for the seam: the built-in default applies.
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.BASELINE, "decision") is None
    finally:
        db.close()


def test_switching_a_sub_component_off_removes_its_registrations(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Off Project")["id"])
    db = SessionLocal()
    try:
        assert [k for k, _ in governance_seams.baseline_checks_for_project(db, project_id)] == [f"{KEY}:fake_check"]
        for sub in ("policies", "checks"):
            db.add(
                OrganizationModuleSubComponentDefault(
                    organization_id=uuid_lib.UUID(org_id), module_key=KEY, subcomponent_key=sub, enabled=False,
                    default_project_enabled=False,
                )
            )
        db.commit()
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.LIFECYCLE, "decision") is None
        assert governance_seams.baseline_checks_for_project(db, project_id) == []
        # A registration bound to the whole module is unaffected by a sub-component switch.
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.APPROVAL, "decision") == "approval-policy"
    finally:
        db.close()


def test_whole_module_off_removes_every_registration(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Module Off Project")["id"])
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{KEY}", json={"enabled": False, "default_project_enabled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    db = SessionLocal()
    try:
        assert governance_seams.resolve_policy(db, project_id, GovernanceSeam.APPROVAL, "decision") is None
        assert governance_seams.baseline_checks_for_project(db, project_id) == []
        assert governance_seams.review_adapter_for_project(db, project_id, "decision") is None
        assert resolve_record_subtypes(db, project_id, "decision", [RECORD_ID]) == {}
    finally:
        db.close()


# --- checks, adapters and sub-types ----------------------------------------------------


def test_baseline_check_lists_every_failure(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Check Project")["id"])
    db = SessionLocal()
    try:
        (_, provider), = governance_seams.baseline_checks_for_project(db, project_id)
        context = BaselineCheckContext(project_id=project_id, kind="stage", actor_id=None)
        ids = [uuid_lib.uuid4(), uuid_lib.uuid4()]
        failures = provider.check(db, context, {"decision": ids})
        assert [f.artefact_id for f in failures] == ids
        assert {f.check_key for f in failures} == {"fake_check"}
    finally:
        db.close()


def test_review_adapter_is_returned_for_a_type_of_an_enabled_module(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Review Project")["id"])
    db = SessionLocal()
    try:
        adapter = governance_seams.review_adapter_for_project(db, project_id, "decision")
        assert adapter is not None and adapter.schedule == "review_record"
        assert list(adapter.due_reviews(db, project_id, date(2026, 1, 1))) == [DueReview(RECORD_ID, date(2026, 1, 1))]
        assert governance_seams.review_adapter_for_project(db, project_id, "risk") is None
    finally:
        db.close()


def test_module_record_subtype_resolver_applies_while_its_module_is_on(client, admin_token, org_id, fake_module):
    project_id = uuid_lib.UUID(create_project(client, admin_token, org_id, "Seam Subtype Project")["id"])
    db = SessionLocal()
    try:
        assert resolve_record_subtypes(db, project_id, "decision", [RECORD_ID]) == {RECORD_ID: "Verification"}
        assert resolve_record_subtypes(db, project_id, "decision", []) == {}
        assert resolve_record_subtypes(db, project_id, "risk", [RECORD_ID]) == {}
    finally:
        db.close()


def test_core_action_subtype_is_the_action_type_name(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    project_id = create_project(client, admin_token, org_id, "Seam Action Subtype Project")["id"]
    action_types = client.get(f"/api/v1/projects/{project_id}/action-types", headers=headers).json()
    created = []
    for index, action_type in enumerate(action_types):
        resp = client.post(
            f"/api/v1/projects/{project_id}/actions", json={"title": f"Action {index}", "action_type_id": action_type["id"]},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        created.append((uuid_lib.UUID(resp.json()["id"]), action_type["name"]))
    other_project_id = create_project(client, admin_token, org_id, "Seam Other Project")["id"]

    assert "requirement_action" in get_record_subtype_resolvers()
    db = SessionLocal()
    try:
        ids = [action_id for action_id, _ in created]
        assert resolve_record_subtypes(db, uuid_lib.UUID(project_id), "requirement_action", ids) == dict(created)
        # Records of another project are never resolved through this one.
        assert resolve_record_subtypes(db, uuid_lib.UUID(other_project_id), "requirement_action", ids) == {}
    finally:
        db.close()
