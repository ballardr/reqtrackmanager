"""Tests for Context & Strategy's registration into the generic
scoring-matrix core (docs/plans/module-01-context-and-strategy-plan.md
Phase 10): the `pain_point` scheme's seeded levels/models/bands, its
`pain_point_type_admin` gate on org-level configuration, and module
enablement gating. The core mechanism itself is covered by
`tests/test_scoring_matrix.py`.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "context_strategy"


def _base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/scoring-schemes/pain_point"


def _enable(client, token, org_id, enabled=True) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": enabled},
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_pain_point_scheme_defaults(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "PP Scoring Defaults Co")
    _enable(client, token, org["id"])
    project = create_project(client, token, org["id"], "PP Scoring Project")
    resp = client.get(f"/api/v1/projects/{project['id']}/scoring-schemes/pain_point", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    config = resp.json()

    axes = {a["key"]: [lvl["name"] for lvl in a["levels"]] for a in config["axes"]}
    assert axes["severity"] == ["Cosmetic", "Minor", "Moderate", "Major", "Blocker"]  # Blocker = top level
    assert axes["frequency"] == ["Rare", "Occasional", "Frequent", "Constant"]
    assert axes["confidence"] == ["Low", "Medium", "High"]
    assert {m["key"]: m["axis_keys"] for m in config["models"]} == {
        "sxf": ["severity", "frequency"], "sxc": ["severity", "confidence"],
        "sxfxc": ["severity", "frequency", "confidence"],
    }
    assert (config["default_model_key"], config["default_model_source"]) == ("sxfxc", "system")
    for model in config["models"]:
        assert [b["label"] for b in model["bands"]] == ["Low", "Medium", "High", "Critical"]
        assert model["bands_source"] == "system"


def test_pain_point_type_admin_can_configure_but_plain_member_cannot(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "PP Scoring Gate Co")
    _enable(client, token, org["id"])
    admin_id = create_org_user(client, token, org["id"], "pp_scoring_admin@example.com")
    create_org_user(client, token, org["id"], "pp_scoring_member@example.com")
    resp = client.post(f"/api/v1/orgs/{org['id']}/users/{admin_id}/module-roles",
                       json={"module_key": MODULE_KEY, "role_key": "pain_point_type_admin"},
                       headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    type_admin = login(client, "pp_scoring_admin@example.com", "Password123!")
    member = login(client, "pp_scoring_member@example.com", "Password123!")

    body = {"name": "Catastrophic", "weight": 6}
    resp = client.post(f"{_base(org['id'])}/axes/severity/levels", json=body, headers=auth_headers(member))
    assert resp.status_code == 403
    resp = client.post(f"{_base(org['id'])}/axes/severity/levels", json=body, headers=auth_headers(type_admin))
    assert resp.status_code == 201, resp.text
    resp = client.put(f"{_base(org['id'])}/default-model", json={"model": "sxf"}, headers=auth_headers(type_admin))
    assert resp.status_code == 200 and resp.json()["default_model_source"] == "org"


def test_pain_point_scheme_hidden_when_module_disabled(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "PP Scoring Disabled Co")
    _enable(client, token, org["id"], enabled=False)
    assert client.get(_base(org["id"]), headers=auth_headers(token)).status_code == 404
    listed = client.get(f"/api/v1/orgs/{org['id']}/scoring-schemes", headers=auth_headers(token)).json()
    assert "pain_point" not in {s["key"] for s in listed}
