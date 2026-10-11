"""Tests for Compliance's `ArtefactSummaryProvider`s
(`modules.compliance.summaries`) through the real core link-graph endpoint:
evidence created with links to a project compliance requirement and a
required-action assessment (which Compliance stores as `ArtefactLink` rows)
shows all three artefact types, labelled, from either end; and another
project's records are never shown.
"""

from __future__ import annotations

from app.modules.compliance.tests.test_compliance_evidence_api import _create_evidence, _setup_project_with_assessment
from app.modules.compliance.tests.test_project_compliance_api import _setup_published_standard_with_tree
from tests.conftest import auth_headers


def _graph(client, token, project_id, artefact_type, artefact_id):
    resp = client.get(
        f"/api/v1/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/link-graph",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_evidence_graph_shows_requirement_and_action_assessment(client, admin_token, org_id):
    project, _assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(
        client, admin_token, project["id"], project_compliance_requirement_ids=[pcr_id],
        required_action_assessment_ids=[assessment_id],
    )

    graph = _graph(client, admin_token, project["id"], "compliance_evidence", evidence["id"])

    nodes = {n["type"]: n for n in graph["nodes"]}
    assert set(nodes) == {
        "compliance_evidence", "project_compliance_requirement", "compliance_required_action_assessment"
    }
    assert nodes["compliance_evidence"]["label"] == "IPX9 Test Certificate"
    assert nodes["project_compliance_requirement"]["id"] == pcr_id
    assert nodes["project_compliance_requirement"]["type_label"] == "Compliance requirement"
    assert nodes["project_compliance_requirement"]["status"]
    assert nodes["compliance_required_action_assessment"]["id"] == assessment_id
    assert nodes["compliance_required_action_assessment"]["status"] == "open"
    assert graph["hidden_count"] == 0 and graph["unavailable_count"] == 0

    from_requirement = _graph(client, admin_token, project["id"], "project_compliance_requirement", pcr_id)
    assert evidence["id"] in {n["id"] for n in from_requirement["nodes"]}


def test_other_projects_compliance_records_are_hidden(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    project, _a, pcr_id, _assessment = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Graph Project A", tree=tree
    )
    other, _b, other_pcr_id, _other_assessment = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Graph Project B", tree=tree
    )
    evidence = _create_evidence(client, admin_token, project["id"], project_compliance_requirement_ids=[pcr_id])

    assert _graph(client, admin_token, project["id"], "compliance_evidence", evidence["id"])["hidden_count"] == 0
    resp = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/project_compliance_requirement/{other_pcr_id}/link-graph",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404
    assert other["id"] != project["id"]
