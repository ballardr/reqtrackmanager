"""A project created from a template receives the template's Risk types and its Risks as fresh drafts.

A starter Risk is newly identified, with no review history or review date, is numbered afresh and keeps its
evidence and its treatments (links to requirements, which keep their codes in a clone); an archived Risk is not copied.
"""

from __future__ import annotations

from app.modules.risk_management.tests._helpers import project_base, setup
from app.modules.risk_management.tests.test_risk_export_import import _build_rich_project, _risks
from tests.conftest import auth_headers


def test_a_template_clone_copies_risk_types_and_risks_as_fresh_drafts(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Template Co")
    h = auth_headers(token)
    built = _build_rich_project(client, token, org, project)
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=h).status_code == 200

    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Risk From Template", "summary": "", "template_project_id": project["id"]},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    new_id = resp.json()["id"]

    copied = _risks(client, token, new_id, include_archived=True)
    assert {r["title"] for r in copied.values()} == {"Flight controller fails", "Stale verdict"}  # the archived one is left out
    main = next(r for r in copied.values() if r["title"] == "Flight controller fails")
    assert main["status"] == "identified" and main["review_date"] is None and main["risk_type_name"] == "Project-only"
    assert main["treatment_strategy"] == "mitigate" and main["acceptance_criteria"] == "Redundant architecture certified."
    assert not main["is_archived"] and main["effective_treatment_count"] == 1

    base = project_base(new_id)
    assert client.get(f"{base}/risks/{main['id']}/reviews", headers=h).json() == []
    assert [t["status"] for t in client.get(f"{base}/risks/{main['id']}/treatments", headers=h).json()["items"]] == ["effective"]
    assert [f["filename"] for f in client.get(f"{base}/risks/{main['id']}/files", headers=h).json()] == ["evidence.txt"]
    # The template keeps its own state.
    original = _risks(client, token, project["id"], include_archived=True)
    assert original[built["main"]["unique_code"]]["status"] == "treatment_in_progress"
