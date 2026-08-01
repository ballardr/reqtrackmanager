"""Tests for report generation: PDF (R-F-01) and CSV (R-F-02) exports."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _seed_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot fast", "reasoning": "UX matters", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    return project


def test_pdf_report_generates_valid_pdf(client, admin_token, org_id):
    project = _seed_requirement(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": "# Introduction\nSome context.", "post_markdown": "# Appendix\n- item one"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"
    assert len(resp.content) > 500


def test_csv_report_contains_requirement_row(client, admin_token, org_id):
    project = _seed_requirement(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/csv", json={}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8")
    assert "SW-PERF-001" in text
    assert "Boot fast" in text
