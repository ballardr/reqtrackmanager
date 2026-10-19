"""A requirement can be created with every field the edit form edits.

The create dialog sends clarification, review date, reminder lead time, owner and reviewer along
with the basics; this pins that the create endpoint persists each of them (and the same values
come back from a read), so the create and edit forms cannot drift apart again.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project


def test_create_persists_clarification_review_fields_owner_and_reviewer(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    owner = create_org_user(client, admin_token, org_id, "req_create_owner@example.com")
    reviewer = create_org_user(client, admin_token, org_id, "req_create_reviewer@example.com")

    created = client.post(
        f"/api/v1/projects/{pid}/requirements",
        json={
            "name": "Boot fast", "reasoning": "Because", "clarification": "Applies to field staff",
            "description": "Under five seconds", "component_id": component_id, "category_id": category_id,
            "level": "recommended", "review_date": "2031-03-01", "review_lead_days": 14,
            "owner": {"type": "user", "id": owner}, "reviewer": {"type": "user", "id": reviewer},
        },
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text

    body = client.get(f"/api/v1/projects/{pid}/requirements/{created.json()['id']}", headers=auth_headers(admin_token)).json()
    assert body["clarification"] == "Applies to field staff"
    assert body["level"] == "recommended"
    assert body["review_date"] == "2031-03-01" and body["review_lead_days"] == 14
    assert body["owner"]["id"] == owner and body["reviewer"]["id"] == reviewer
