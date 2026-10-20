"""Tests for project and organisation codes: policy validation, automatic and manual
assignment, uniqueness, qualified-code lookup and display data (link graph), and that a
policy change never rewrites an existing code."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.code_rules import CodePolicy, candidate_codes, code_error, default_code_for_name, policy_error
from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _put_policy(client, token, org_id, **overrides):
    body = {"kind": "alphanumeric", "min_length": 2, "max_length": 6, "assignment": "auto", "enforce_code_everywhere": False}
    body.update(overrides)
    return client.put(f"/api/v1/orgs/{org_id}/code-policy", json=body, headers=auth_headers(token))


@pytest.fixture
def admin_in_new_org(client, admin_token):
    """A fresh organisation and a genuine org admin in it (the server admin cannot act inside one)."""
    org, token = create_org_admin_in(client, admin_token, "Codes Org")
    return org, token


# --- Pure rules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Rail Signalling Upgrade", "RSU"), ("Apollo", "AP"), ("a", "AX"), ("  ", "XX"), ("Über Cool", "BC")],
)
def test_default_code_is_initials_padded_to_minimum(name, expected):
    assert default_code_for_name(name) == expected


def test_candidates_add_a_numeric_suffix_for_alphanumeric_and_letters_for_letters():
    first = [c for _, c in zip(range(4), candidate_codes("Rail Signalling Upgrade", CodePolicy()), strict=False)]
    assert first == ["RSU", "RSU2", "RSU3", "RSU4"]
    letters = [c for _, c in zip(range(3), candidate_codes("Rail Signalling Upgrade", CodePolicy(kind="letters")), strict=False)]
    assert letters == ["RSU", "RSUB", "RSUC"]


def test_candidates_respect_the_maximum_length():
    codes = [c for _, c in zip(range(3), candidate_codes("Alpha Beta Gamma Delta", CodePolicy(max_length=4)), strict=False)]
    assert codes == ["ABGD", "ABG2", "ABG3"]
    assert all(len(c) <= 4 for c in codes)


def test_digits_policy_counts_upwards_and_stops_at_the_maximum():
    assert list(candidate_codes("ignored", CodePolicy(kind="digits", min_length=2, max_length=2)))[:3] == ["01", "02", "03"]
    assert list(candidate_codes("x", CodePolicy(kind="digits", min_length=1, max_length=1))) == [str(n) for n in range(1, 10)]


@pytest.mark.parametrize(
    ("code", "kind", "ok"),
    [("ACME", "letters", True), ("AC1", "letters", False), ("12", "digits", True), ("A-B", "alphanumeric", False),
     ("A B", "alphanumeric", False), ("A", "alphanumeric", False), ("ABCDEFG", "alphanumeric", False), ("ab", "alphanumeric", False)],
)
def test_code_error_by_kind_and_length(code, kind, ok):
    assert (code_error(code, CodePolicy(kind=kind)) is None) is ok


def test_policy_error_rejects_inverted_or_oversized_lengths():
    assert policy_error(CodePolicy(min_length=5, max_length=3)) is not None
    assert policy_error(CodePolicy(max_length=11)) is not None
    assert policy_error(CodePolicy(kind="emoji")) is not None
    assert policy_error(CodePolicy()) is None


def test_migration_derivation_matches_the_runtime_rules():
    """The migration freezes a copy of the rules; the two must agree for the default policy."""
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0092_project_and_org_codes.py"
    spec = importlib.util.spec_from_file_location("migration_0092", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("Rail Signalling Upgrade", "Apollo", "a", "Alpha Beta Gamma Delta Epsilon Zeta Eta"):
        runtime = [c for _, c in zip(range(3), candidate_codes(name, CodePolicy()), strict=False)]
        frozen = [c for _, c in zip(range(3), module._candidates(name), strict=False)]
        assert runtime == frozen


# --- Automatic assignment ------------------------------------------------------


def test_auto_assigned_code_comes_from_the_name_and_is_unique(client, admin_in_new_org):
    org, token = admin_in_new_org
    first = create_project(client, token, org["id"], "Rail Signalling Upgrade")
    second = create_project(client, token, org["id"], "Rail Station Upgrade")
    assert first["code"] == "RSU"
    assert second["code"] == "RSU2"


def test_auto_assignment_rejects_a_supplied_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    resp = client.post(
        "/api/v1/projects", json={"organization_id": org["id"], "name": "Chosen", "code": "ZZ"}, headers=auth_headers(token)
    )
    assert resp.status_code == 400


def test_project_code_differs_from_organisation_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    assert org["code"] == "CO"
    project = create_project(client, token, org["id"], "Codes Org")
    assert project["code"] != org["code"]
    assert project["code"] == "CO2"


def test_same_code_may_exist_in_two_organisations(client, admin_token, admin_in_new_org):
    org, token = admin_in_new_org
    other_org, other_token = create_org_admin_in(client, admin_token, "Other Codes Org")
    a = create_project(client, token, org["id"], "Shared Name")
    b = create_project(client, other_token, other_org["id"], "Shared Name")
    assert a["code"] == b["code"] == "SN"


def test_template_clone_gets_a_fresh_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    template = create_project(client, token, org["id"], "Base Template")
    assert client.patch(
        f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(token)
    ).status_code == 200
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Base Template Copy", "template_project_id": template["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"] not in (template["code"], org["code"])


def test_project_import_gets_a_fresh_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    source = create_project(client, token, org["id"], "Export Source")
    bundle = client.get(f"/api/v1/projects/{source['id']}/export", headers=auth_headers(token))
    assert bundle.status_code == 200, bundle.text
    resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org["id"], "name": "Export Source"},
        files={"file": ("bundle.zip", bundle.content, "application/zip")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    imported = resp.json()["project"]
    assert imported["code"] != source["code"]


# --- Manual assignment and policy ----------------------------------------------


def test_manual_assignment_requires_a_valid_unique_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    assert _put_policy(client, token, org["id"], assignment="manual", kind="letters", min_length=2, max_length=4).status_code == 200

    def create(code):
        payload = {"organization_id": org["id"], "name": "Manual"}
        if code is not None:
            payload["code"] = code
        return client.post("/api/v1/projects", json=payload, headers=auth_headers(token))

    assert create(None).status_code == 400  # required
    assert create("A").status_code == 400  # too short
    assert create("ABCDE").status_code == 400  # too long
    assert create("AB1C").status_code == 400  # digit under letters
    assert create("AB-C").status_code == 400  # hyphen
    created = create("abc")
    assert created.status_code == 201
    assert created.json()["code"] == "ABC"  # normalised to upper case
    assert create("ABC").status_code == 409  # taken
    assert create("abc").status_code == 409  # taken, case-insensitively
    assert create(org["code"]).status_code == 409  # the organisation's own code


def test_code_may_be_changed_only_under_manual_assignment(client, admin_in_new_org):
    org, token = admin_in_new_org
    project = create_project(client, token, org["id"], "Editable")
    patch = lambda code: client.patch(  # noqa: E731
        f"/api/v1/projects/{project['id']}", json={"code": code}, headers=auth_headers(token)
    )
    assert patch("NEWC").status_code == 400  # automatic
    assert patch(project["code"]).status_code == 200  # unchanged is a no-op

    _put_policy(client, token, org["id"], assignment="manual")
    assert patch("NEWC").json()["code"] == "NEWC"
    assert patch("A-B").status_code == 400

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "code_changed")).all()
    assert [e.detail for e in events] == [{"from": project["code"], "to": "NEWC"}]


def test_changing_the_policy_never_rewrites_existing_codes(client, admin_in_new_org):
    org, token = admin_in_new_org
    project = create_project(client, token, org["id"], "Stable Name")
    assert _put_policy(client, token, org["id"], kind="letters", min_length=5, max_length=6).status_code == 200
    fetched = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert fetched["code"] == project["code"] == "SN"
    # An unchanged code is not re-validated against the stricter policy.
    _put_policy(client, token, org["id"], kind="letters", min_length=5, max_length=6, assignment="manual")
    resp = client.patch(f"/api/v1/projects/{project['id']}", json={"code": "SN"}, headers=auth_headers(token))
    assert resp.status_code == 200


def test_policy_is_validated_and_org_admin_only(client, admin_token, admin_in_new_org):
    org, token = admin_in_new_org
    assert _put_policy(client, token, org["id"], min_length=5, max_length=3).status_code == 400
    assert _put_policy(client, token, org["id"], max_length=11).status_code == 400
    assert _put_policy(client, token, org["id"], kind="emoji").status_code == 422
    create_org_user(client, admin_token, org["id"], "codes_member@example.com")
    member_token = login(client, "codes_member@example.com", "Password123!")
    assert _put_policy(client, member_token, org["id"]).status_code == 403


def test_policy_and_enforce_flag_are_readable_by_members(client, admin_token, admin_in_new_org):
    org, token = admin_in_new_org
    assert _put_policy(client, token, org["id"], max_length=8, enforce_code_everywhere=True).status_code == 200
    create_org_user(client, admin_token, org["id"], "codes_reader@example.com")
    member_token = login(client, "codes_reader@example.com", "Password123!")
    fetched = client.get(f"/api/v1/orgs/{org['id']}", headers=auth_headers(member_token)).json()
    assert fetched["code"] == org["code"]
    assert fetched["project_code_policy"] == {"kind": "alphanumeric", "min_length": 2, "max_length": 8, "assignment": "auto"}
    assert fetched["enforce_code_everywhere"] is True


def test_policy_change_is_audited(client, admin_in_new_org):
    org, token = admin_in_new_org
    _put_policy(client, token, org["id"], assignment="manual")
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "code_policy_updated")).all()
    assert len(events) == 1
    assert events[0].detail["assignment"] == "manual"


# --- Qualified lookup ----------------------------------------------------------


def _create_requirement(client, token, project_id):
    component_id, category_id = _component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Coded requirement", "reasoning": "r", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _component_and_category(client, token, project_id):
    from tests.conftest import create_component_and_category

    return create_component_and_category(client, token, project_id)


def test_lookup_by_qualified_code_finds_the_record(client, admin_in_new_org):
    org, token = admin_in_new_org
    project = create_project(client, token, org["id"], "Lookup Project")
    requirement = _create_requirement(client, token, project["id"])
    qualified = f"{project['code']}-{requirement['unique_code']}"
    resp = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{qualified.lower()}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artefact_type"] == "requirement"
    assert body["id"] == requirement["id"]
    assert body["project_id"] == project["id"]
    assert body["qualified_code"] == qualified


@pytest.mark.parametrize("code", ["", "NOHYPHEN", "-REQ-001", "ZZZ-REQ-001", "LP-REQ-999"])
def test_lookup_of_unknown_or_malformed_code_is_404(client, admin_in_new_org, code):
    org, token = admin_in_new_org
    create_project(client, token, org["id"], "Lookup Project")
    resp = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{code or 'x'}", headers=auth_headers(token))
    assert resp.status_code == 404


def test_lookup_hides_records_in_projects_the_caller_cannot_open(client, admin_token, admin_in_new_org):
    org, token = admin_in_new_org
    project = create_project(client, token, org["id"], "Private Project")
    requirement = _create_requirement(client, token, project["id"])
    create_org_user(client, admin_token, org["id"], "codes_outsider@example.com")
    outsider = login(client, "codes_outsider@example.com", "Password123!")
    qualified = f"{project['code']}-{requirement['unique_code']}"
    resp = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{qualified}", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_lookup_does_not_cross_organisations(client, admin_token, admin_in_new_org):
    org, token = admin_in_new_org
    other_org, other_token = create_org_admin_in(client, admin_token, "Foreign Codes Org")
    project = create_project(client, other_token, other_org["id"], "Foreign Project")
    requirement = _create_requirement(client, other_token, project["id"])
    qualified = f"{project['code']}-{requirement['unique_code']}"
    resp = client.get(f"/api/v1/orgs/{org['id']}/records/by-code/{qualified}", headers=auth_headers(token))
    assert resp.status_code == 404


# --- Link graph display data ---------------------------------------------------


def test_link_graph_nodes_carry_their_project_code(client, admin_in_new_org):
    org, token = admin_in_new_org
    project = create_project(client, token, org["id"], "Graph Project")
    requirement = _create_requirement(client, token, project["id"])
    resp = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/requirement/{requirement['id']}/link-graph",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    nodes = resp.json()["nodes"]
    assert nodes
    assert {n["project_code"] for n in nodes} == {project["code"]}
