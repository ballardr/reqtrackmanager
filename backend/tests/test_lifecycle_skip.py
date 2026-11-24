"""
Tests for skipping steps on one record (`services.lifecycles.skip_moves`, `check_move`, `deps.capture_lifecycle_skip`,
the skip settings in `routers.lifecycles`): the pure rule, the project and organisation switches with exempt
projects, enforcement through a record's own move endpoint, the per-step entry checks, the audit event and the
bundles.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from urllib.parse import quote

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.modules.registry import get_lifecycles
from app.services.lifecycles import skip_moves
from tests.conftest import SessionLocal, auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "context_strategy"
SKIP_HEADER = "X-Lifecycle-Skip-Reason"
_PAIN_POINT_FIELDS = {
    "title": "Slow export", "description": "The export takes minutes.", "priority": "medium",
    "business_impact": "Delays reporting.",
}
_OPEN_QUESTION_FIELDS = {
    "question": "Should the fleet standardise on one battery vendor?", "context": "Two vendors qualify today.",
    "evidence": "A six-week lead-time gap.", "priority": "high", "due_date": "2026-10-15",
}


# --- the pure rule -----------------------------------------------------------------------------


def test_a_skip_reaches_later_steps_and_never_passes_a_gated_step():
    _, strategy = get_lifecycles()["strategy"]
    moves = skip_moves(strategy, (), (), "draft")
    assert moves == {"under_review": ("proposed",), "approved": ("proposed", "under_review")}
    assert "active" not in moves, "Approved is gated, so nothing beyond it may be reached by a skip"


def test_a_skip_never_passes_a_required_step():
    _, pain_point = get_lifecycles()["pain_point"]
    assert skip_moves(pain_point, (), (), "submitted") == {
        "accepted": ("triaged",), "addressed": ("triaged", "accepted"), "closed": ("triaged", "accepted", "addressed"),
    }
    required = skip_moves(pain_point, (), ("triaged",), "submitted")
    assert required == {}, "Triaged is required: it may be the next step but nothing beyond it is reachable"
    assert skip_moves(pain_point, (), (), "triaged")["addressed"] == ("accepted",)


def test_a_move_the_path_already_allows_is_not_a_skip():
    _, pain_point = get_lifecycles()["pain_point"]
    assert "triaged" not in skip_moves(pain_point, (), (), "submitted")
    off = skip_moves(pain_point, ("triaged",), (), "submitted")
    assert "accepted" not in off, "stepping over a turned-off state is an ordinary move"
    assert off["addressed"] == ("triaged", "accepted")


def test_an_off_path_state_has_no_skips():
    _, strategy = get_lifecycles()["strategy"]
    assert skip_moves(strategy, (), (), "retired") == {}


@pytest.mark.parametrize("artefact_type", sorted(get_lifecycles()))
def test_every_type_declares_how_to_check_a_step_it_passes_over(artefact_type):
    """A type without an entry check could never be skipped safely, so each registered type supplies one."""
    assert get_lifecycles()[artefact_type][1].entry_guard is not None


# --- helpers -------------------------------------------------------------------------------------


def _enable(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name: str, *, can_be_parent: bool = False):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"])
    project = create_project(client, token, org["id"], f"{name} project", can_be_parent=can_be_parent or None)
    return org, project, token


def _base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _put_skip(client, token, project_id, allowed):
    return client.put(
        f"/api/v1/projects/{project_id}/lifecycles/skip", json={"allowed": allowed}, headers=auth_headers(token)
    )


def _put_org_skip(client, token, org_id, forbidden):
    return client.put(f"/api/v1/orgs/{org_id}/lifecycles/skip", json={"forbidden": forbidden}, headers=auth_headers(token))


def _add_org_exemption(client, token, org_id, project_id, include_children=False):
    return client.post(
        f"/api/v1/orgs/{org_id}/lifecycles/skip/exemptions",
        json={"project_id": project_id, "include_children": include_children}, headers=auth_headers(token),
    )


def _get_lifecycles(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/lifecycles", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pain_point(client, token, project_id) -> str:
    types = client.get(f"{_base(project_id)}/pain-point-types", headers=auth_headers(token))
    assert types.status_code == 200, types.text
    resp = client.post(
        f"{_base(project_id)}/pain-points",
        json={**_PAIN_POINT_FIELDS, "pain_point_type_id": types.json()[0]["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _move(client, token, project_id, pain_point_id, action, reason=None, **body):
    headers = auth_headers(token)
    if reason is not None:
        headers[SKIP_HEADER] = quote(reason)
    return client.post(f"{_base(project_id)}/pain-points/{pain_point_id}/{action}", json=body, headers=headers)


def _events(record_id: str, action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == record_id, AuditEvent.action == action)
        ))
    finally:
        db.close()


# --- settings ------------------------------------------------------------------------------------


def test_skipping_is_off_by_default_and_a_project_administrator_turns_it_on(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Default Co")
    payload = _get_lifecycles(client, token, project["id"])
    assert payload["skip"] == {
        "allowed": False, "own": None, "chosen": False, "source": "default", "forbidden": False, "exempt": False,
    }
    assert all(entry["skip_transitions"] == {} for entry in payload["lifecycles"])

    resp = _put_skip(client, token, project["id"], True)
    assert resp.status_code == 200, resp.text
    skip = resp.json()["skip"]
    assert skip["allowed"] is True and skip["own"] is True and skip["source"] == "project"
    pain_point = next(x for x in resp.json()["lifecycles"] if x["artefact_type"] == "pain_point")
    assert pain_point["skip_transitions"]["submitted"]["accepted"] == ["triaged"]
    assert "triaged" not in pain_point["skip_transitions"]["submitted"]

    assert _put_skip(client, token, project["id"], None).json()["skip"]["chosen"] is False


def test_only_a_person_who_may_manage_lifecycles_changes_the_switch(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Permission Co")
    user_id = create_org_user(client, token, org["id"], "skip-viewer@example.com")
    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token)
    ).status_code == 204
    member = login(client, "skip-viewer@example.com", "Password123!")
    assert _put_skip(client, member, project["id"], True).status_code == 403
    assert _put_org_skip(client, member, org["id"], True).status_code == 403


def test_a_child_project_follows_its_parent_until_it_chooses(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Skip Nested Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _put_skip(client, token, parent["id"], True)
    inherited = _get_lifecycles(client, token, child["id"])["skip"]
    assert inherited["allowed"] is True and inherited["own"] is None and inherited["source"] == "parent_project"
    own = _put_skip(client, token, child["id"], False).json()["skip"]
    assert own["allowed"] is False and own["source"] == "project"


def test_an_organisation_ban_locks_the_project_and_an_exempt_project_is_not_bound(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Ban Co")
    assert _put_skip(client, token, project["id"], True).status_code == 200
    assert _put_org_skip(client, token, org["id"], True).status_code == 200

    locked = _get_lifecycles(client, token, project["id"])["skip"]
    assert locked["allowed"] is False and locked["chosen"] is True and locked["forbidden"] is True
    assert _put_skip(client, token, project["id"], True).status_code == 409

    exempt = _add_org_exemption(client, token, org["id"], project["id"])
    assert exempt.status_code == 200, exempt.text
    assert exempt.json()["exemptions"][0]["project_id"] == project["id"]
    free = _get_lifecycles(client, token, project["id"])["skip"]
    assert free["allowed"] is True and free["forbidden"] is False and free["exempt"] is True

    removed = client.delete(
        f"/api/v1/orgs/{org['id']}/lifecycles/skip/exemptions/{project['id']}", headers=auth_headers(token)
    )
    assert removed.status_code == 200 and removed.json()["exemptions"] == []
    assert _get_lifecycles(client, token, project["id"])["skip"]["allowed"] is False
    assert client.get(f"/api/v1/orgs/{org['id']}/lifecycles/skip", headers=auth_headers(token)).json()["forbidden"] is True


def test_an_exemption_may_cover_nested_projects(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Skip Exempt Nested Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _put_skip(client, token, parent["id"], True)
    _put_skip(client, token, child["id"], True)
    _put_org_skip(client, token, org["id"], True)
    _add_org_exemption(client, token, org["id"], parent["id"], include_children=False)
    assert _get_lifecycles(client, token, child["id"])["skip"]["allowed"] is False
    _add_org_exemption(client, token, org["id"], parent["id"], include_children=True)
    assert _get_lifecycles(client, token, child["id"])["skip"]["allowed"] is True


def test_settings_changes_are_audited_with_keys_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Audit Co")
    _put_skip(client, token, project["id"], True)
    _put_org_skip(client, token, org["id"], True)
    _add_org_exemption(client, token, org["id"], project["id"], include_children=True)
    assert [e.detail for e in _events(project["id"], "skip_updated")] == [{"skip_allowed": True, "inherits": False}]
    assert [e.detail for e in _events(org["id"], "skip_forbidden_updated")] == [{"forbidden": True}]
    assert [e.detail for e in _events(org["id"], "skip_exemption_added")] == [{"include_children": True}]


# --- skipping a record's steps -------------------------------------------------------------------


def test_a_skip_needs_the_project_to_allow_it(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Refused Co")
    pain_point = _pain_point(client, token, project["id"])
    resp = _move(client, token, project["id"], pain_point, "accept", reason="Urgent")
    assert resp.status_code == 409 and "Skipping steps is not allowed" in resp.json()["detail"]


def test_without_a_skip_request_the_path_is_unchanged(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Plain Co")
    _put_skip(client, token, project["id"], True)
    pain_point = _pain_point(client, token, project["id"])
    resp = _move(client, token, project["id"], pain_point, "accept")
    assert resp.status_code == 409 and "Allowed next states: 'Triaged'" in resp.json()["detail"]


def test_a_skip_moves_the_record_and_records_the_steps_passed_over(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Works Co")
    _put_skip(client, token, project["id"], True)
    pain_point = _pain_point(client, token, project["id"])
    resp = _move(client, token, project["id"], pain_point, "address", reason="Fixed in the hot patch ü")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "addressed"
    (event,) = _events(pain_point, "steps_skipped")
    assert event.detail == {
        "from": "submitted", "to": "addressed", "skipped": ["triaged", "accepted"],
        "skipped_labels": ["Triaged", "Accepted"], "reason": "Fixed in the hot patch ü",
    }
    assert len(_events(pain_point, "status_changed")) + len(_events(pain_point, "addressed")) >= 1


def test_a_skip_needs_a_reason_within_the_limit(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Reason Co")
    _put_skip(client, token, project["id"], True)
    pain_point = _pain_point(client, token, project["id"])
    assert _move(client, token, project["id"], pain_point, "accept", reason="   ").status_code == 400
    assert _move(client, token, project["id"], pain_point, "accept", reason="x" * 501).status_code == 400
    assert _move(client, token, project["id"], pain_point, "accept", reason="x" * 500).status_code == 200


def test_a_skip_never_passes_a_step_the_organisation_requires(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Required Co")
    _put_skip(client, token, project["id"], True)
    required = client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/pain_point", json={"required_states": ["triaged"]},
        headers=auth_headers(token),
    )
    assert required.status_code == 200, required.text
    pain_point = _pain_point(client, token, project["id"])
    resp = _move(client, token, project["id"], pain_point, "accept", reason="Urgent")
    assert resp.status_code == 409 and "Allowed next states: 'Triaged'" in resp.json()["detail"]
    assert _events(pain_point, "steps_skipped") == []


def test_an_organisation_ban_stops_a_skip_and_an_exemption_restores_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Ban Move Co")
    _put_skip(client, token, project["id"], True)
    _put_org_skip(client, token, org["id"], True)
    first = _pain_point(client, token, project["id"])
    assert _move(client, token, project["id"], first, "accept", reason="Urgent").status_code == 409
    _add_org_exemption(client, token, org["id"], project["id"])
    assert _move(client, token, project["id"], first, "accept", reason="Urgent").status_code == 200


def test_a_failed_skip_stores_no_audit_event(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Rollback Co")
    _put_skip(client, token, project["id"], True)
    pain_point = _pain_point(client, token, project["id"])
    assert _move(client, token, project["id"], pain_point, "reject", reason="Urgent", comment=" ").status_code == 400
    assert _events(pain_point, "steps_skipped") == []


def test_the_header_never_authenticates_by_itself(client, admin_token):
    _, project, token = _setup(client, admin_token, "Skip Auth Co")
    pain_point = _pain_point(client, token, project["id"])
    resp = client.post(
        f"{_base(project['id'])}/pain-points/{pain_point}/accept", json={}, headers={SKIP_HEADER: quote("Urgent")}
    )
    assert resp.status_code == 401


# --- the entry check of each step passed over ----------------------------------------------------


def _grant_module_role(client, token, project_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text


def _member(client, token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token)
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _open_question(client, token, project_id) -> str:
    resp = client.post(f"{_base(project_id)}/open-questions", json=_OPEN_QUESTION_FIELDS, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _resolve(client, token, project_id, open_question_id, reason):
    headers = auth_headers(token)
    headers[SKIP_HEADER] = quote(reason)
    return client.post(
        f"{_base(project_id)}/open-questions/{open_question_id}/resolve", json={}, headers=headers
    )


def test_a_person_must_be_able_to_enter_every_step_they_pass_over(client, admin_token):
    """Resolving needs the resolver role; the steps passed over (Investigating, Ready for decision) need the owner
    role. A resolver without it is refused, and the same person with both roles may skip."""
    org, project, token = _setup(client, admin_token, "Skip Entry Co")
    _put_skip(client, token, project["id"], True)
    user_id, member = _member(client, token, org["id"], project["id"], "skip-resolver@example.com")
    _grant_module_role(client, token, project["id"], user_id, "open_question_resolver")
    open_question = _open_question(client, token, project["id"])

    refused = _resolve(client, member, project["id"], open_question, "Decided in the meeting")
    assert refused.status_code == 403, refused.text
    assert _events(open_question, "steps_skipped") == []

    _grant_module_role(client, token, project["id"], user_id, "open_question_owner")
    allowed = _resolve(client, member, project["id"], open_question, "Decided in the meeting")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "resolved"
    (event,) = _events(open_question, "steps_skipped")
    assert event.detail["skipped"] == ["investigating", "ready_for_decision"]
    assert event.actor_id == uuid.UUID(user_id)


# --- bundles -------------------------------------------------------------------------------------


def _project_bundle(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))


def test_the_project_bundle_carries_the_choice(client, admin_token):
    org, project, token = _setup(client, admin_token, "Skip Bundle Co")
    assert _project_bundle(client, token, project["id"])["lifecycle_skip"] == {"allowed": None}
    _put_skip(client, token, project["id"], True)
    bundle = _project_bundle(client, token, project["id"])
    assert bundle["lifecycle_skip"] == {"allowed": True}


def test_a_template_copy_keeps_the_choice(client, admin_token):
    from app.models.project import Project
    from app.services import lifecycles

    org, project, token = _setup(client, admin_token, "Skip Template Co")
    _put_skip(client, token, project["id"], True)
    target = create_project(client, token, org["id"], "Skip Template copy")
    db = SessionLocal()
    try:
        source_row, target_row = db.get(Project, uuid.UUID(project["id"])), db.get(Project, uuid.UUID(target["id"]))
        lifecycles.copy_project(db, source_row, target_row, None)
        db.commit()
        assert lifecycles.export_project_skip(db, target_row) == {"allowed": True}
    finally:
        db.close()


def test_the_organisation_bundle_carries_the_ban_and_its_exemptions(client, admin_token):
    from app.models.organization import Organization
    from app.services import lifecycles

    org, project, token = _setup(client, admin_token, "Skip Org Bundle Co")
    _put_org_skip(client, token, org["id"], True)
    _add_org_exemption(client, token, org["id"], project["id"], include_children=True)
    other_org, other_project, other_token = _setup(client, admin_token, "Skip Org Bundle Target Co")
    actor = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(other_token)).json()["id"])
    db = SessionLocal()
    try:
        exported = lifecycles.export_org(db, db.get(Organization, uuid.UUID(org["id"])), {uuid.UUID(project["id"]): "P1"})
        assert exported["lifecycle_skip"] == {
            "forbidden": True, "exemptions": [{"project_ref": "P1", "include_children": True}],
        }
        warnings: list[str] = []
        lifecycles.import_org(
            db, db.get(Organization, uuid.UUID(other_org["id"])), exported, {"P1": uuid.UUID(other_project["id"])},
            actor, warnings.append,
        )
        db.commit()
        assert warnings == []
        assert lifecycles.organization_skip(db, db.get(Organization, uuid.UUID(other_org["id"]))) == {
            "forbidden": True, "exemptions": [(uuid.UUID(other_project["id"]), True)],
        }
    finally:
        db.close()
