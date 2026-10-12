"""Tests for groups as Compliance standard owners, review owners and required-action assignees
(users and groups on parity, Phase 5 — docs/plans/users-and-groups-parity-plan.md).

Covers: each principal kind on the three fields (create, update, clear, list, a response reused as
a request); validation (a foreign organisation's group or user, another project's group, a project
group on an organisation-scoped standard or standard-level review); a recurring review keeping its
group owner; the due-date sweeps notifying every member of a group; deleting a group that owns
records (usage counts, a mandatory standard owner needing a replacement, reassign, clear, audit
events naming the record); project, organisation and single-standard bundles carrying the
principal by name (and falling back when the group is missing); organisation deletion with a
required action and a mapping; and the migration backfilling existing rows to `user`.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, timedelta

from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.modules.compliance.models import ComplianceReview, ComplianceStandard
from app.modules.compliance.scheduler import send_required_action_due_notifications, send_review_due_notifications
from app.modules.compliance.tests.test_compliance_evidence_api import _setup_project_with_assessment
from app.modules.compliance.tests.test_compliance_mapping_and_version_impact import (
    _create_mapping,
    _create_relationship_type,
)
from app.modules.compliance.tests.test_compliance_reviews_and_notifications import _notifications_for, _run_sweep
from app.modules.compliance.tests.test_compliance_standard_export_import import (
    _build_standard_with_tree,
    _export,
    _import,
)
from app.modules.compliance.tests.test_compliance_standards_api import _base, _create_standard
from app.modules.compliance.tests.test_project_compliance_api import _project_base, _setup_published_standard_with_tree
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
    login,
)

TODAY = date.today()
PASSWORD = "Password123!"


def _user(user_id) -> dict:
    return {"type": "user", "id": str(user_id)}


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def _assessment_url(project_id, assignment_id, pcr_id, assessment_id) -> str:
    return (
        f"{_project_base(project_id)}/project-compliance/{assignment_id}/requirements/{pcr_id}/"
        f"required-action-assessments/{assessment_id}"
    )


def _patch_assessment(client, token, url, **extra):
    return client.patch(url, json={"due_date": None, "notes": "", **extra}, headers=auth_headers(token))


def _schedule_project_review(client, token, project_id, assignment_id, **extra):
    return client.post(
        f"{_project_base(project_id)}/project-compliance/{assignment_id}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY + timedelta(days=90)).isoformat(), **extra},
        headers=auth_headers(token),
    )


def _schedule_standard_review(client, token, org_id, standard_id, **extra):
    return client.post(
        f"{_base(org_id)}/standards/{standard_id}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY + timedelta(days=90)).isoformat(), **extra},
        headers=auth_headers(token),
    )


# --- Standard owner --------------------------------------------------------------------------------------


def test_standard_owner_defaults_to_the_creator_and_takes_ancreate_org_group(client, admin_token, org_id):
    me = _me(client, admin_token)
    member = create_org_user(client, admin_token, org_id, "std-owner-member@example.com")
    team = create_org_group(client, admin_token, org_id, "Standards Board", users=[member])
    h = auth_headers(admin_token)

    default = _create_standard(client, admin_token, org_id, reference="OWN-DEFAULT")
    assert default["owner"]["type"] == "user" and default["owner"]["id"] == me

    owned = _create_standard(client, admin_token, org_id, reference="OWN-GROUP", owner={"type": "org_group", "id": team})
    assert owned["owner"] == {"type": "org_group", "id": team, "label": "Standards Board", "member_count": 1, "exists": True}
    assert client.get(f"{_base(org_id)}/standards/{owned['id']}", headers=h).json()["owner"]["label"] == "Standards Board"
    listed = {s["reference"]: s for s in client.get(f"{_base(org_id)}/standards", headers=h).json()}
    assert listed["OWN-GROUP"]["owner"]["type"] == "org_group" and listed["OWN-DEFAULT"]["owner"]["id"] == me

    # A response is a valid request body for an update (the owner comes back as a resolved principal, the
    # request wants a bare reference), and the owner can move between a group and a user.
    body = {"name": owned["name"], "description": "", "issuing_organisation": None, "owner": _user(member)}
    moved = client.patch(f"{_base(org_id)}/standards/{owned['id']}", json=body, headers=h)
    assert moved.status_code == 200, moved.text
    assert moved.json()["owner"]["id"] == member
    back = client.patch(f"{_base(org_id)}/standards/{owned['id']}", json={**body, "owner": {"type": "org_group", "id": team}}, headers=h)
    assert back.json()["owner"]["label"] == "Standards Board"


def test_standard_owner_is_mandatory_and_must_belong_to_the_organisation(client, admin_token, org_id):
    other_org, other_token = create_org_admin_in(client, admin_token, "Std Owner Foreign Org")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Group")
    foreign_user = _me(client, other_token)
    project = create_project(client, admin_token, org_id, name="Std Owner Project")
    project_group = create_project_group(client, admin_token, project["id"], "Project Squad")
    standard = _create_standard(client, admin_token, org_id, reference="OWN-RULES")
    h = auth_headers(admin_token)
    url = f"{_base(org_id)}/standards/{standard['id']}"
    body = {"name": "Renamed", "description": "", "issuing_organisation": None}

    for bad in (
        {"type": "org_group", "id": foreign_group},
        _user(foreign_user),
        {"type": "project_group", "id": project_group},  # a standard is organisation-scoped
        {"type": "org_group", "id": str(uuid.uuid4())},
    ):
        assert client.patch(url, json={**body, "owner": bad}, headers=h).status_code == 400, bad
        assert (
            client.post(
                f"{_base(org_id)}/standards",
                json={"reference": f"BAD-{uuid.uuid4().hex[:6]}", "name": "x", "initial_version_label": "1", "owner": bad},
                headers=h,
            ).status_code
            == 400
        ), bad
    # The owner is required on update; a null is rejected by the schema.
    assert client.patch(url, json={**body, "owner": None}, headers=h).status_code == 422
    assert client.patch(url, json=body, headers=h).status_code == 422


# --- Required action assignee ------------------------------------------------------------------------------


def test_required_action_assignee_takes_each_kind_and_is_cleared(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    member = create_org_user(client, admin_token, org_id, "assignee-kinds@example.com")
    team = create_org_group(client, admin_token, org_id, "Test Engineers", users=[member])
    squad = create_project_group(client, admin_token, project["id"], "Release Squad", users=[member])
    url = _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id)
    h = auth_headers(admin_token)

    assert client.get(url, headers=h).json()["assignee"] is None
    for ref, label, kind in (
        ({"type": "org_group", "id": team}, "Test Engineers", "org_group"),
        ({"type": "project_group", "id": squad}, "Release Squad", "project_group"),
        (_user(member), None, "user"),
    ):
        resp = _patch_assessment(client, admin_token, url, assignee=ref)
        assert resp.status_code == 200, resp.text
        assignee = resp.json()["assignee"]
        assert assignee["type"] == kind and assignee["id"] == ref["id"]
        if label:
            assert assignee["label"] == label and assignee["member_count"] == 1

    group = _patch_assessment(client, admin_token, url, assignee={"type": "project_group", "id": squad})
    listed = client.get(url.rsplit("/", 1)[0], headers=h).json()
    assert next(a for a in listed if a["id"] == assessment_id)["assignee"]["label"] == "Release Squad"
    # The outstanding list (and so the org dashboard) resolves the assignee too.
    outstanding = client.get(f"{_project_base(project['id'])}/outstanding-required-actions", headers=h).json()
    assert [o["assignee"]["label"] for o in outstanding if o["required_action_assessment_id"] == assessment_id] == ["Release Squad"]
    # Editing the due date with the response's own assignee keeps it.
    echoed = group.json()["assignee"]
    kept = _patch_assessment(client, admin_token, url, assignee={"type": echoed["type"], "id": echoed["id"]}, due_date="2030-01-01")
    assert kept.json()["assignee"]["label"] == "Release Squad" and kept.json()["due_date"] == "2030-01-01"

    cleared = _patch_assessment(client, admin_token, url, assignee=None)
    assert cleared.status_code == 200 and cleared.json()["assignee"] is None


def test_required_action_assignee_rejects_foreign_and_other_project_principals(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    other_org, other_token = create_org_admin_in(client, admin_token, "Assignee Foreign Org")
    other_project = create_project(client, admin_token, org_id, name="Other Assignee Project")
    url = _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id)

    for bad in (
        {"type": "org_group", "id": create_org_group(client, other_token, other_org["id"], "Foreign")},
        _user(_me(client, other_token)),
        {"type": "project_group", "id": create_project_group(client, admin_token, other_project["id"], "Elsewhere")},
        {"type": "project_group", "id": str(uuid.uuid4())},
    ):
        assert _patch_assessment(client, admin_token, url, assignee=bad).status_code == 400, bad
    assert client.get(url, headers=auth_headers(admin_token)).json()["assignee"] is None


# --- Review owner ----------------------------------------------------------------------------------------------


def test_project_review_owner_takes_each_kind_and_recurrence_keeps_it(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    member = create_org_user(client, admin_token, org_id, "review-kinds@example.com")
    team = create_org_group(client, admin_token, org_id, "Review Office", users=[member])
    squad = create_project_group(client, admin_token, project["id"], "Review Squad", users=[member])
    h = auth_headers(admin_token)

    created = _schedule_project_review(
        client, admin_token, project["id"], assignment["id"], recurrence_days=30, owner={"type": "project_group", "id": squad},
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["owner"] == {"type": "project_group", "id": squad, "label": "Review Squad", "member_count": 1, "exists": True}

    updated = client.patch(
        f"{_project_base(project['id'])}/reviews/{review['id']}",
        json={
            "frequency_label": "Annual", "recurrence_days": 30, "next_due_date": review["next_due_date"],
            "owner": {"type": "org_group", "id": team},
        },
        headers=h,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["owner"]["label"] == "Review Office"

    completed = client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete", json={"outcome": "satisfactory", "notes": ""}, headers=h,
    )
    assert completed.status_code == 200, completed.text
    listed = client.get(f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=h).json()
    scheduled = [r for r in listed if r["status"] == "scheduled"]
    assert len(scheduled) == 1 and scheduled[0]["owner"]["label"] == "Review Office", "the next cycle keeps the owner"

    cleared = client.patch(
        f"{_project_base(project['id'])}/reviews/{scheduled[0]['id']}",
        json={"frequency_label": "Annual", "next_due_date": scheduled[0]["next_due_date"], "owner": None}, headers=h,
    )
    assert cleared.json()["owner"] is None
    due = client.get(f"{_project_base(project['id'])}/reviews-due", headers=h)
    assert due.status_code == 200


def test_standard_level_review_owner_cannot_be_acreate_project_group(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Std Review Project")
    squad = create_project_group(client, admin_token, project["id"], "Std Review Squad")
    team = create_org_group(client, admin_token, org_id, "Std Review Office")
    other_org, other_token = create_org_admin_in(client, admin_token, "Std Review Foreign Org")
    standard = _create_standard(client, admin_token, org_id, reference="REV-OWN")

    assert _schedule_standard_review(client, admin_token, org_id, standard["id"], owner={"type": "project_group", "id": squad}).status_code == 400
    foreign = create_org_group(client, other_token, other_org["id"], "Foreign")
    assert _schedule_standard_review(
        client, admin_token, org_id, standard["id"], owner={"type": "org_group", "id": foreign},
    ).status_code == 400
    created = _schedule_standard_review(client, admin_token, org_id, standard["id"], owner={"type": "org_group", "id": team})
    assert created.status_code == 201, created.text
    assert created.json()["owner"]["label"] == "Std Review Office"
    url = f"{_base(org_id)}/standards/{standard['id']}/reviews/{created.json()['id']}"
    body = {"frequency_label": "Annual", "next_due_date": created.json()["next_due_date"]}
    assert client.patch(url, json={**body, "owner": {"type": "project_group", "id": squad}}, headers=auth_headers(admin_token)).status_code == 400
    listed = client.get(f"{_base(org_id)}/standards/{standard['id']}/reviews", headers=auth_headers(admin_token)).json()
    assert [r["owner"]["label"] for r in listed] == ["Std Review Office"]


# --- Notifications -------------------------------------------------------------------------------------------------


def test_review_and_required_action_sweeps_notify_every_member_of_a_group(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    alice = create_org_user(client, admin_token, org_id, "sweep-alice@example.com")
    bob = create_org_user(client, admin_token, org_id, "sweep-bob@example.com")
    carol = create_org_user(client, admin_token, org_id, "sweep-carol@example.com")
    team = create_org_group(client, admin_token, org_id, "Sweep Office", users=[alice, bob])
    squad = create_project_group(client, admin_token, project["id"], "Sweep Squad", users=[bob, carol])
    tokens = {n: login(client, f"sweep-{n}@example.com", PASSWORD) for n in ("alice", "bob", "carol")}
    yesterday = (TODAY - timedelta(days=1)).isoformat()

    assert _schedule_project_review(
        client, admin_token, project["id"], assignment["id"], next_due_date=yesterday, owner={"type": "org_group", "id": team},
    ).status_code == 201
    url = _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id)
    assert _patch_assessment(client, admin_token, url, assignee={"type": "project_group", "id": squad}, due_date=yesterday).status_code == 200

    _run_sweep(send_review_due_notifications)
    _run_sweep(send_review_due_notifications)
    _run_sweep(send_required_action_due_notifications)
    _run_sweep(send_required_action_due_notifications)

    def kinds(name: str) -> list[str]:
        return sorted(n["type"] for n in _notifications_for(client, tokens[name]) if n["type"].startswith("compliance_"))

    assert kinds("alice") == ["compliance_review_overdue"]
    assert kinds("bob") == ["compliance_required_action_overdue", "compliance_review_overdue"], "in both groups, told once for each"
    assert kinds("carol") == ["compliance_required_action_overdue"]


# --- Deleting a group that owns records ----------------------------------------------------------------------------


def test_deleting_an_org_group_that_owns_a_standard_needs_a_replacement(client, admin_token, org_id):
    me = _me(client, admin_token)
    team = create_org_group(client, admin_token, org_id, "Doomed Board")
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    standard = _create_standard(client, admin_token, org_id, reference="DOOMED", owner={"type": "org_group", "id": team})
    review = _schedule_standard_review(client, admin_token, org_id, standard["id"], owner={"type": "org_group", "id": team}).json()
    assessment_url = _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id)
    assert _patch_assessment(client, admin_token, assessment_url, assignee={"type": "org_group", "id": team}).status_code == 200
    h = auth_headers(admin_token)
    group_url = f"/api/v1/orgs/{org_id}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("compliance standard owners", 1, True), ("compliance review owners", 1, False), ("required action assignees", 1, False),
    }
    assert usage["mandatory_total"] == 1

    assert client.delete(group_url, headers=h).status_code == 409
    assert client.delete(group_url, params={"clear_optional": "true"}, headers=h).status_code == 409, "the owner is required"
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    assert client.get(f"{_base(org_id)}/standards/{standard['id']}", headers=h).json()["owner"]["id"] == me
    reviews = client.get(f"{_base(org_id)}/standards/{standard['id']}/reviews", headers=h).json()
    assert reviews[0]["id"] == review["id"] and reviews[0]["owner"]["id"] == me
    assert client.get(assessment_url, headers=h).json()["assignee"]["id"] == me
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        by_type = {e.entity_type: str(e.entity_id) for e in events}
        assert by_type["compliance_standard"] == standard["id"]
        assert by_type["compliance_review"] == review["id"]
        assert by_type["compliance_required_action_assessment"] == assessment_id


def test_deleting_a_project_group_can_clear_optional_assignees_and_owners(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    squad = create_project_group(client, admin_token, project["id"], "Doomed Squad")
    h = auth_headers(admin_token)
    assessment_url = _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id)
    assert _patch_assessment(client, admin_token, assessment_url, assignee={"type": "project_group", "id": squad}).status_code == 200
    review = _schedule_project_review(client, admin_token, project["id"], assignment["id"], owner={"type": "project_group", "id": squad}).json()
    url = f"/api/v1/projects/{project['id']}/groups/{squad}"

    usage = client.get(f"{url}/usage", headers=h).json()
    assert usage["total"] == 2 and usage["mandatory_total"] == 0
    assert client.delete(url, headers=h).status_code == 409
    assert client.delete(url, params={"clear_optional": "true"}, headers=h).status_code == 204

    assert client.get(assessment_url, headers=h).json()["assignee"] is None
    reviews = client.get(f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=h).json()
    assert [r["owner"] for r in reviews if r["id"] == review["id"]] == [None]


# --- Bundles --------------------------------------------------------------------------------------------------------


def _project_bundle_round_trip(client, token, org_id, project_id, name):
    exported = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert exported.status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    return json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json")), imported.json()


def test_project_bundle_carries_group_assignees_and_review_owners_by_name(client, admin_token, org_id):
    standard, version, _parent, child, _pa, child_action = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Compliance Principal Bundle Source")
    team = create_org_group(client, admin_token, org_id, "Bundle Office")
    squad = create_project_group(client, admin_token, project["id"], "Bundle Squad")
    h = auth_headers(admin_token)
    assignment = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]}, headers=h,
    ).json()
    pcrs = client.get(f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements", headers=h).json()
    pcr = next(p for p in pcrs if p["requirement_id"] == child["id"])
    assessments = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr['id']}/required-action-assessments", headers=h,
    ).json()
    assessment = next(a for a in assessments if a["required_action_id"] == child_action["id"])
    url = _assessment_url(project["id"], assignment["id"], pcr["id"], assessment["id"])
    assert _patch_assessment(client, admin_token, url, assignee={"type": "project_group", "id": squad}).status_code == 200
    assert _schedule_project_review(client, admin_token, project["id"], assignment["id"], owner={"type": "org_group", "id": team}).status_code == 201

    bundle, result = _project_bundle_round_trip(client, admin_token, org_id, project["id"], "Compliance Principal Bundle Copy")
    exported_action = bundle["compliance_project_compliances"][0]["requirements"]
    exported_actions = [a for r in exported_action for a in r["required_actions"] if a["assignee"]]
    assert exported_actions[0]["assignee"] == {"type": "project_group", "name": "Bundle Squad"}
    assert bundle["compliance_project_compliances"][0]["reviews"][0]["owner"] == {"type": "org_group", "name": "Bundle Office"}
    assert result["warnings"] == []

    new_project = result["project"]
    new_squad = next(
        g["id"] for g in client.get(f"/api/v1/projects/{new_project['id']}/groups", headers=h).json() if g["name"] == "Bundle Squad"
    )
    new_assignment = client.get(f"{_project_base(new_project['id'])}/project-compliance", headers=h).json()[0]
    new_pcrs = client.get(f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/requirements", headers=h).json()
    new_pcr = next(p for p in new_pcrs if p["requirement_id"] == child["id"])
    new_assessments = client.get(
        f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/requirements/{new_pcr['id']}/required-action-assessments",
        headers=h,
    ).json()
    restored = next(a for a in new_assessments if a["required_action_id"] == child_action["id"])
    assert restored["assignee"]["type"] == "project_group" and restored["assignee"]["id"] == new_squad
    new_reviews = client.get(f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/reviews", headers=h).json()
    assert new_reviews[0]["owner"]["id"] == team and new_reviews[0]["owner"]["type"] == "org_group"


def test_project_bundle_leaves_an_unmatched_assignee_and_owner_empty_with_a_warning(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    squad = create_project_group(client, admin_token, project["id"], "Vanishing Squad")
    team = create_org_group(client, admin_token, org_id, "Vanishing Office")
    assert _patch_assessment(
        client, admin_token, _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id),
        assignee={"type": "project_group", "id": squad},
    ).status_code == 200
    assert _schedule_project_review(client, admin_token, project["id"], assignment["id"], owner={"type": "org_group", "id": team}).status_code == 201
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content

    # Rewrite the bundle so it names groups the importing organisation does not have.
    source = zipfile.ZipFile(io.BytesIO(exported))
    rewritten = io.BytesIO()
    with zipfile.ZipFile(rewritten, "w") as out:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "project.json":  # rename only the compliance references; the project's own groups still travel
                document = json.loads(data)
                for pc in document["compliance_project_compliances"]:
                    for requirement in pc["requirements"]:
                        for action in requirement["required_actions"]:
                            if action["assignee"]:
                                action["assignee"]["name"] = "Missing Squad"
                    for review in pc["reviews"]:
                        review["owner"]["name"] = "Missing Office"
                data = json.dumps(document).encode()
            out.writestr(item, data)
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Compliance Missing Groups Copy"},
        files={"file": ("bundle.zip", rewritten.getvalue(), "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    warnings = imported.json()["warnings"]
    assert any("Missing Squad" in w for w in warnings) and any("Missing Office" in w for w in warnings)
    new_project = imported.json()["project"]
    h = auth_headers(admin_token)
    new_assignment = client.get(f"{_project_base(new_project['id'])}/project-compliance", headers=h).json()[0]
    new_reviews = client.get(f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/reviews", headers=h).json()
    assert new_reviews[0]["owner"] is None


def test_standard_export_carries_an_org_group_owner_by_name_and_falls_back_when_missing(client, admin_token, org_id):
    team = create_org_group(client, admin_token, org_id, "Exported Board")
    standard, *_ = _build_standard_with_tree(client, admin_token, org_id, reference="EXP-OWN")
    h = auth_headers(admin_token)
    assert client.patch(
        f"{_base(org_id)}/standards/{standard['id']}",
        json={"name": standard["name"], "description": "", "issuing_organisation": None, "owner": {"type": "org_group", "id": team}},
        headers=h,
    ).status_code == 200
    document = _export(client, admin_token, org_id, standard["id"])
    assert document["standard"]["owner"] == {"type": "org_group", "name": "Exported Board"}

    # A target organisation with a same-named group gets it as owner, with no warning about the owner.
    matching_org, matching_token = create_org_admin_in(client, admin_token, "Std Owner Matching Target")
    matching_team = create_org_group(client, matching_token, matching_org["id"], "Exported Board")
    matched = _import(client, matching_token, matching_org["id"], document)
    assert matched.status_code == 201, matched.text
    assert matched.json()["standard"]["owner"]["id"] == matching_team
    assert not [w for w in matched.json()["warnings"] if "owner" in w]

    # One without it attributes the standard to the importing user, with a warning.
    bare_org, bare_token = create_org_admin_in(client, admin_token, "Std Owner Bare Target")
    fallback = _import(client, bare_token, bare_org["id"], document)
    assert fallback.status_code == 201, fallback.text
    owner = fallback.json()["standard"]["owner"]
    assert owner["type"] == "user" and owner["id"] == _me(client, bare_token)
    assert any("Exported Board" in w and "importing user" in w for w in fallback.json()["warnings"])

    # A document written before groups existed (owner_email) still imports.
    legacy = json.loads(json.dumps(document))
    legacy["standard"].pop("owner")
    legacy["standard"]["owner_email"] = "admin@example.com"
    old = _import(client, bare_token, bare_org["id"], {**legacy, "standard": {**legacy["standard"], "reference": "EXP-OWN-OLD"}})
    assert old.status_code == 201, old.text


def test_org_bundle_carries_a_group_owner_into_a_new_organisation(client, admin_token, org_id):
    team = create_org_group(client, admin_token, org_id, "Org Bundle Board")
    _create_standard(client, admin_token, org_id, reference="ORG-BUNDLE-OWN", owner={"type": "org_group", "id": team})
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert exported.status_code == 200
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Org Bundle Principal Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = imported.json()["organization"]
    standards = client.get(f"{_base(new_org['id'])}/standards", headers=auth_headers(admin_token)).json()
    owned = next(s for s in standards if s["reference"] == "ORG-BUNDLE-OWN")
    assert owned["owner"]["type"] == "org_group" and owned["owner"]["label"] == "Org Bundle Board"
    assert owned["owner"]["id"] != team, "the copy points at the new organisation's own group"


# --- Organisation deletion --------------------------------------------------------------------------------------------


def test_deleting_an_organisation_with_required_actions_and_mappings_succeeds(client, admin_token):
    """The foreign keys from a required action to its action type and from a mapping to its relationship
    type are deferred, so the organisation's cascade does not trip over whichever branch runs first."""
    org, token = create_org_admin_in(client, admin_token, "Compliance Deletion Org")
    standard, version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, token, org["id"])
    relationship = _create_relationship_type(client, token, org["id"])
    _create_mapping(client, token, org["id"], from_id=parent["id"], to_id=child["id"], relationship_type_id=relationship["id"])

    resp = client.request("DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text


# --- Migration backfill ------------------------------------------------------------------------------------------------


def test_migration_backfills_existing_rows_to_user(client, admin_token, org_id):
    """Runs the real 0079 migration: a standard, review and assessment written in the pre-migration shape
    (no `*_type` column) end up with `user` for their principal, and an unassigned one stays empty."""
    me = _me(client, admin_token)
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    standard = _create_standard(client, admin_token, org_id, reference="MIGRATE-OWN")
    unowned = _schedule_project_review(client, admin_token, project["id"], assignment["id"]).json()
    legacy_review = uuid.uuid4()
    with engine.begin() as conn:  # the backfill labels every owner a user, so leave no other test's group owner behind
        conn.execute(text("UPDATE compliance_reviews SET owner_id = NULL, owner_type = NULL WHERE owner_type <> 'user'"))
        conn.execute(text("UPDATE compliance_required_action_assessments SET assignee_id = NULL, assignee_type = NULL WHERE assignee_type <> 'user'"))
        conn.execute(text("UPDATE compliance_standards SET owner_id = :me, owner_type = 'user' WHERE owner_type <> 'user'"), {"me": me})
    command.downgrade(build_alembic_config(), "0078")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO compliance_reviews (id, project_compliance_id, frequency_label, next_due_date, owner_id, status, "
                    "notes, created_by, created_at, updated_at) VALUES (:id, :pc, 'Legacy', :due, :me, 'scheduled', '', :me, now(), now())"
                ),
                {"id": legacy_review, "pc": assignment["id"], "due": TODAY, "me": me},
            )
            conn.execute(
                text("UPDATE compliance_required_action_assessments SET assignee_id = :me WHERE id = :id"),
                {"me": me, "id": assessment_id},
            )
    finally:
        command.upgrade(build_alembic_config(), "head")

    with SessionLocal() as db:
        review = db.get(ComplianceReview, legacy_review)
        assert (review.owner_type, str(review.owner_id)) == ("user", me)
        other = db.get(ComplianceReview, uuid.UUID(unowned["id"]))
        assert other.owner_type is None and other.owner_id is None
        owned_standard = db.get(ComplianceStandard, uuid.UUID(standard["id"]))
        assert owned_standard.owner_type == "user" and str(owned_standard.owner_id) == me
    resp = client.get(
        _assessment_url(project["id"], assignment["id"], pcr_id, assessment_id), headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200 and resp.json()["assignee"]["id"] == me
