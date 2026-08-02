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


def test_csv_report_neutralizes_formula_injection(client, admin_token, org_id):
    """Security regression: a requirement name/reasoning starting with =/+/-/@
    would be interpreted as a formula by Excel/LibreOffice on open (classic
    CSV/DDE injection) — this export exists specifically for spreadsheet
    review (R-F-02), so user-controlled fields must be neutralized."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": '=HYPERLINK("https://evil.example","x")', "reasoning": "+cmd|' /C calc'!A1",
            "component_id": component_id, "category_id": category_id,
        },
        headers=auth_headers(admin_token),
    )
    resp = client.post(f"/api/v1/projects/{project['id']}/reports/csv", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 200
    text = resp.content.decode("utf-8")
    # CSV-quoted (the values contain commas/quotes), so check the
    # neutralizing prefix survives rather than matching a raw substring.
    assert "'=HYPERLINK(" in text
    assert "'+cmd|" in text
    # And the formula characters are never the first character of a cell.
    assert '"=HYPERLINK(' not in text
    assert ",+cmd|" not in text


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


def test_report_config_persists_and_is_used_as_pdf_default(client, admin_token, org_id):
    project = _seed_requirement(client, admin_token, org_id)

    empty = client.get(f"/api/v1/projects/{project['id']}/report-config", headers=auth_headers(admin_token)).json()
    assert empty == {"intro": "", "chapters": [], "appendices": []}

    saved = client.put(
        f"/api/v1/projects/{project['id']}/report-config",
        json={
            "intro": "Welcome to the report.",
            "chapters": [{"title": "Scope", "body": "What this covers."}],
            "appendices": [{"title": "Glossary", "body": "Terms used."}],
        },
        headers=auth_headers(admin_token),
    )
    assert saved.status_code == 200
    assert saved.json()["intro"] == "Welcome to the report."

    reread = client.get(f"/api/v1/projects/{project['id']}/report-config", headers=auth_headers(admin_token)).json()
    assert reread["chapters"] == [{"title": "Scope", "body": "What this covers."}]

    # Generating without ad-hoc pre/post markdown should fall back to the
    # persisted config rather than producing a bare report.
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf", json={}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
