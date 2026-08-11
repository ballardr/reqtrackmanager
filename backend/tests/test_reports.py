"""Tests for report generation: PDF (R-F-01) and CSV (R-F-02) exports."""

from app.models.organization import Organization
from app.models.project import Project
from app.services.reports import (
    ReportRequirementRow,
    _group_rows_by_component_and_category,
    default_chapters_per_component,
    resolve_report_config,
)
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _seed_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot fast", "reasoning": "UX matters", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    return project


def _row(unique_code, component_name, component_sort_order, category_name, category_sort_order) -> ReportRequirementRow:
    return ReportRequirementRow(
        unique_code=unique_code, name=f"Name for {unique_code}", reasoning="Because.", clarification="",
        status="draft", component_name=component_name, category_name=category_name,
        component_sort_order=component_sort_order, category_sort_order=category_sort_order,
    )


def test_group_rows_orders_chapters_and_sections_by_sort_order_not_name(client, admin_token, org_id):
    """Deliberately picks names whose alphabetical order is the *reverse*
    of their sort_order, so a test that accidentally grouped/ordered by
    name instead of sort_order (matching the component/category tree UI's
    own ordering) would fail rather than pass by coincidence."""
    rows = [
        _row("A-1-001", "Zeta Component", 1, "Zulu Category", 1),
        _row("A-2-001", "Zeta Component", 1, "Alpha Category", 0),
        _row("B-1-001", "Alpha Component", 0, "Solo Category", 0),
    ]
    chapters = _group_rows_by_component_and_category(rows)
    assert [name for name, _ in chapters] == ["Alpha Component", "Zeta Component"]

    alpha_component_sections = chapters[0][1]
    assert [name for name, _ in alpha_component_sections] == ["Solo Category"]

    zeta_component_sections = chapters[1][1]
    assert [name for name, _ in zeta_component_sections] == ["Alpha Category", "Zulu Category"]


def test_group_rows_orders_requirements_within_a_category_by_unique_code():
    rows = [
        _row("SW-PERF-002", "Software", 0, "Performance", 0),
        _row("SW-PERF-001", "Software", 0, "Performance", 0),
    ]
    chapters = _group_rows_by_component_and_category(rows)
    codes = [r.unique_code for r in chapters[0][1][0][1]]
    assert codes == ["SW-PERF-001", "SW-PERF-002"]


def test_group_rows_keeps_components_separate_even_with_the_same_name():
    """Component names aren't guaranteed unique (only (project_id, prefix)
    is) — two same-named components at different sort positions must stay
    as two distinct chapters, not merge into one."""
    rows = [
        _row("A-1-001", "Shared Name", 0, "Cat A", 0),
        _row("B-1-001", "Shared Name", 1, "Cat B", 0),
    ]
    chapters = _group_rows_by_component_and_category(rows)
    assert len(chapters) == 2


def test_pdf_report_generates_valid_pdf_across_multiple_components_and_categories(client, admin_token, org_id):
    """Router-level smoke test for the chapter-per-component/section-per-
    category structure — the exact ordering is covered directly (and much
    more cheaply) by the _group_rows_by_component_and_category unit tests
    above, since parsing PDF text back out would need a dependency this
    project's test suite deliberately doesn't add (see test_report_images.py)."""
    project = create_project(client, admin_token, org_id)
    sw_id, perf_id = create_component_and_category(client, admin_token, project["id"])
    hw_component = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(admin_token),
    ).json()
    hw_category = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Reliability", "prefix": "REL", "component_id": hw_component["id"]},
        headers=auth_headers(admin_token),
    ).json()
    for component_id, category_id, name in [
        (sw_id, perf_id, "Boot fast"), (hw_component["id"], hw_category["id"], "Survive a drop"),
    ]:
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "reasoning": "x", "component_id": component_id, "category_id": category_id},
            headers=auth_headers(admin_token),
        )
    resp = client.post(f"/api/v1/projects/{project['id']}/reports/pdf", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


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
    assert empty == {
        "intro": "", "chapters": [], "appendices": [],
        "intro_is_organisation_default": False,
        "chapters_is_organisation_default": False,
        "appendices_is_organisation_default": False,
        "default_report_template_id": None,
    }

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


def test_report_config_is_readable_by_a_plain_stakeholder_not_just_a_manager(client, admin_token, org_id):
    """Regression: GET report-config was gated to require_project_manage,
    even though it's read-only content stakeholders/members need to
    generate reports (C-U-03) — ReportsPage.tsx and ProjectAdminPage.tsx's
    single Promise.all reload both fetch it, so this silently 403'd (and,
    for ProjectAdminPage, hung the whole page on its loading spinner) for
    any project role below manager/administrator. PUT stays manage-only."""
    project = _seed_requirement(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "stakeholder_report@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    stakeholder_token = login(client, "stakeholder_report@example.com", "Password123!")

    resp = client.get(f"/api/v1/projects/{project['id']}/report-config", headers=auth_headers(stakeholder_token))
    assert resp.status_code == 200

    denied = client.put(
        f"/api/v1/projects/{project['id']}/report-config",
        json={"intro": "Should not be allowed."},
        headers=auth_headers(stakeholder_token),
    )
    assert denied.status_code == 403


def test_project_falls_back_to_organisation_report_defaults(client, admin_token, org_id):
    """A project with no report content of its own (R-G-01/R-G-02) should
    use the organisation's defaults field-by-field, and the response should
    say so via the `*_is_organisation_default` flags — the same "narrower
    scope overrides a broader default" shape used for branding."""
    project = _seed_requirement(client, admin_token, org_id)

    defaults = client.put(
        f"/api/v1/orgs/{org_id}/report-defaults",
        json={
            "intro": "Org-wide introduction.",
            "chapters": [{"title": "Standard scope", "body": "Applies to every project."}],
            "appendices": [],
        },
        headers=auth_headers(admin_token),
    )
    assert defaults.status_code == 200
    assert defaults.json()["intro"] == "Org-wide introduction."

    fetched = client.get(f"/api/v1/orgs/{org_id}/report-defaults", headers=auth_headers(admin_token)).json()
    assert fetched["chapters"] == [{"title": "Standard scope", "body": "Applies to every project."}]

    config = client.get(f"/api/v1/projects/{project['id']}/report-config", headers=auth_headers(admin_token)).json()
    assert config["intro"] == "Org-wide introduction."
    assert config["intro_is_organisation_default"] is True
    assert config["chapters_is_organisation_default"] is True
    # Appendices default is empty, so there's nothing to "use" — not organisation-default.
    assert config["appendices_is_organisation_default"] is False

    # The project's own intro, once set, takes priority over the org default.
    client.put(
        f"/api/v1/projects/{project['id']}/report-config",
        json={"intro": "Project-specific introduction.", "chapters": [], "appendices": []},
        headers=auth_headers(admin_token),
    )
    overridden = client.get(f"/api/v1/projects/{project['id']}/report-config", headers=auth_headers(admin_token)).json()
    assert overridden["intro"] == "Project-specific introduction."
    assert overridden["intro_is_organisation_default"] is False
    # Chapters weren't set on the project (still []), so the org default still applies there.
    assert overridden["chapters"] == [{"title": "Standard scope", "body": "Applies to every project."}]
    assert overridden["chapters_is_organisation_default"] is True

    resp = client.post(f"/api/v1/projects/{project['id']}/reports/pdf", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


def test_resolve_report_config_falls_back_to_project_summary_then_org_default_for_intro():
    """Precedence for intro specifically: project.report_intro (explicit
    override) > project.summary (project description) > org default >
    blank. Chapters/appendices have no summary-equivalent fallback."""
    org = Organization(default_report_intro="org default intro")

    # No report_intro set at all: falls back to the project's description.
    project = Project(report_intro="", summary="A drone inspection platform.")
    resolved = resolve_report_config(project, org)
    assert resolved.intro == "A drone inspection platform."
    assert resolved.intro_is_organisation_default is False

    # An explicit report_intro still wins over the description.
    project = Project(report_intro="Explicit intro.", summary="A drone inspection platform.")
    resolved = resolve_report_config(project, org)
    assert resolved.intro == "Explicit intro."

    # Neither report_intro nor summary set: falls all the way to the org default.
    project = Project(report_intro="", summary="")
    resolved = resolve_report_config(project, org)
    assert resolved.intro == "org default intro"
    assert resolved.intro_is_organisation_default is True


def test_default_chapters_per_component_heuristic():
    """Chaptered unless some component in scope has fewer than three
    requirements — see default_chapters_per_component's docstring."""
    assert default_chapters_per_component([]) is True  # nothing to chapter

    all_healthy = [
        _row("A-1-001", "Airframe", 0, "Functional", 0),
        _row("A-1-002", "Airframe", 0, "Functional", 0),
        _row("A-1-003", "Airframe", 0, "Functional", 0),
        _row("B-1-001", "Avionics", 1, "Safety", 0),
        _row("B-1-002", "Avionics", 1, "Safety", 0),
        _row("B-1-003", "Avionics", 1, "Safety", 0),
    ]
    assert default_chapters_per_component(all_healthy) is True

    one_sparse = [
        *all_healthy,
        _row("C-1-001", "Firmware", 2, "Regulatory", 0),  # only 1 requirement in this component
    ]
    assert default_chapters_per_component(one_sparse) is False


def test_chapters_per_component_precedence_payload_beats_template_beats_heuristic(client, admin_token, org_id):
    """Router-level: an explicit payload choice wins over the selected
    template's setting, which wins over the sparse-component heuristic."""
    project = create_project(client, admin_token, org_id)
    sw_id, perf_id = create_component_and_category(client, admin_token, project["id"])
    # Only one requirement in this component -> heuristic alone would pick continuous.
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Solo requirement", "reasoning": "x", "component_id": sw_id, "category_id": perf_id},
        headers=auth_headers(admin_token),
    )

    heuristic_resp = client.post(f"/api/v1/projects/{project['id']}/reports/pdf", json={}, headers=auth_headers(admin_token))
    assert heuristic_resp.status_code == 200

    template_forces_chapters = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "Always Chaptered", "chapters_per_component": True}, headers=auth_headers(admin_token),
    ).json()
    template_resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"report_template_id": template_forces_chapters["id"]}, headers=auth_headers(admin_token),
    )
    assert template_resp.status_code == 200
    # The template forces chaptered (with its page break + heading) despite
    # the sparse component the heuristic alone would have gone continuous for.
    assert len(template_resp.content) > len(heuristic_resp.content)

    payload_overrides_template = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"report_template_id": template_forces_chapters["id"], "chapters_per_component": False},
        headers=auth_headers(admin_token),
    )
    assert payload_overrides_template.status_code == 200
    # Explicit payload choice (continuous) wins over the template's chaptered setting.
    assert len(payload_overrides_template.content) < len(template_resp.content)
