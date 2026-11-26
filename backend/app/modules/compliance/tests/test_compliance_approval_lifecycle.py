"""The approval state of a compliance assessment as a registered lifecycle (`modules.compliance.lifecycles`): the path and
what is optional and gated, the project turning the submit step off (an assessed requirement is then approved or rejected
directly, still behind the approver and approval separation), the offered moves in the requirement's response, the
unconditional resets that no setting can hold back, and the registration itself. The workflow with every step on is tested
in `test_compliance_approval_workflow.py`."""

from __future__ import annotations

from app.modules.compliance.lifecycles import LIFECYCLES
from app.modules.compliance.models import ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT as TYPE
from app.modules.compliance.tests.test_compliance_approval_workflow import _pcr_path, _setup_assessed_pcr
from app.modules.registry import get_lifecycles, get_no_lifecycle_types
from app.services.lifecycles import validate_definition
from tests.conftest import auth_headers


def _turn_off_submit(client, token, project_id, off=True) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/lifecycles/{TYPE}",
        json={"disabled_states": ["pending_approval"] if off else []}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _requirement(client, token, project_id, assignment_id, pcr_id) -> dict:
    resp = client.get(_pcr_path(project_id, assignment_id, pcr_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_definition_is_valid_and_registered_instead_of_carrying_a_reason():
    assert validate_definition(LIFECYCLES[TYPE]) == []
    module_key, definition = get_lifecycles()[TYPE]
    assert module_key == "compliance"
    assert definition.path == ("not_assessed", "assessed", "pending_approval", "approved")
    assert (definition.optional, definition.gated) == (("pending_approval",), ("approved",))
    assert TYPE not in get_no_lifecycle_types()


def test_the_requirement_offers_the_next_approval_state(client, admin_token, org_id):
    project, assignment, pcr_id, _ = _setup_assessed_pcr(client, admin_token, org_id)
    path = (project["id"], assignment["id"], pcr_id)
    assert _requirement(client, admin_token, *path)["next_approval_states"] == ["pending_approval"]
    client.post(_pcr_path(*path, "/submit-for-approval"), headers=auth_headers(admin_token))
    assert _requirement(client, admin_token, *path)["next_approval_states"] == ["approved", "rejected"]


def test_with_the_submit_step_off_an_assessed_requirement_is_approved_directly(client, admin_token, org_id):
    project, assignment, pcr_id, _ = _setup_assessed_pcr(client, admin_token, org_id)
    path = (project["id"], assignment["id"], pcr_id)
    _turn_off_submit(client, admin_token, project["id"])
    assert _requirement(client, admin_token, *path)["next_approval_states"] == ["approved", "rejected"]

    submit = client.post(_pcr_path(*path, "/submit-for-approval"), headers=auth_headers(admin_token))
    assert submit.status_code == 409 and "turned off" in submit.text

    approved = client.post(
        _pcr_path(*path, "/approve"), json={"decision_note": "Signed off."}, headers=auth_headers(admin_token),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_state"] == "approved"
    history = client.get(_pcr_path(*path, "/history"), headers=auth_headers(admin_token)).json()
    assert [e["detail"]["previous_approval_state"] for e in history if e["action"] == "approved"] == ["assessed"]


def test_with_the_submit_step_off_a_rejection_still_needs_its_note_and_an_assessed_requirement_may_be_rejected(client, admin_token, org_id):
    project, assignment, pcr_id, _ = _setup_assessed_pcr(client, admin_token, org_id)
    path = (project["id"], assignment["id"], pcr_id)
    _turn_off_submit(client, admin_token, project["id"])
    assert client.post(_pcr_path(*path, "/reject"), json={"decision_note": ""}, headers=auth_headers(admin_token)).status_code == 400
    rejected = client.post(_pcr_path(*path, "/reject"), json={"decision_note": "Not evidenced."}, headers=auth_headers(admin_token))
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["approval_state"] == "rejected"


def test_turning_the_step_back_on_restores_the_ordering(client, admin_token, org_id):
    project, assignment, pcr_id, _ = _setup_assessed_pcr(client, admin_token, org_id)
    path = (project["id"], assignment["id"], pcr_id)
    _turn_off_submit(client, admin_token, project["id"])
    _turn_off_submit(client, admin_token, project["id"], off=False)
    assert client.post(_pcr_path(*path, "/approve"), json={}, headers=auth_headers(admin_token)).status_code == 409


def test_a_reassessment_still_returns_an_approved_requirement_to_assessed_whatever_a_project_turned_off(client, admin_token, org_id):
    project, assignment, pcr_id, _ = _setup_assessed_pcr(client, admin_token, org_id)
    path = (project["id"], assignment["id"], pcr_id)
    _turn_off_submit(client, admin_token, project["id"])
    client.post(_pcr_path(*path, "/approve"), json={}, headers=auth_headers(admin_token))
    assert _requirement(client, admin_token, *path)["approval_state"] == "approved"
    reassessed = client.patch(
        _pcr_path(*path, "/assessment"), json={"compliance_status": "in_progress", "justification": "", "notes": ""},
        headers=auth_headers(admin_token),
    )
    assert reassessed.status_code == 200, reassessed.text
    assert reassessed.json()["approval_state"] == "assessed"
