"""Tests for the Compliance Module's `on_org_created` seeding. `app.modules.compliance.module._seed_org_defaults` seeds a
new organisation's default compliance action types, called by `app.modules.registry.run_on_org_created_hooks` from
`routers.orgs.create_organization` and `services.bootstrap.run_bootstrap`. The generic dispatch is tested in
`test_module_registry.py::test_run_on_org_created_hooks_calls_every_registered_hook`, which proves only that a hook runs;
these tests pin that this module's seeding happens end to end through `POST /orgs`.
"""

from __future__ import annotations

from app.modules.compliance.service import DEFAULT_COMPLIANCE_ACTION_TYPES
from tests.conftest import auth_headers


def test_creating_an_org_seeds_default_compliance_action_types(client, admin_token):
    resp = client.post("/api/v1/orgs", json={"name": "Org Creation Seeding Test Co"}, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    # `POST /orgs` is server-admin-only and grants no membership, so join as admin first; otherwise the module-gated
    # listing endpoint would 404 as "not a member", indistinguishable from a seeding failure.
    join = client.post(f"/api/v1/orgs/{org_id}/join-as-admin", headers=auth_headers(admin_token))
    assert join.status_code == 204, join.text

    listed = client.get(
        f"/api/v1/orgs/{org_id}/modules/compliance/action-types", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200, listed.text
    names = {a["name"] for a in listed.json()}
    assert names == set(DEFAULT_COMPLIANCE_ACTION_TYPES)
