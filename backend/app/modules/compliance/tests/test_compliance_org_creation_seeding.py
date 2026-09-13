"""Tests for the Compliance Module's `on_org_created` seeding behaviour
(module boundary cleanup, 2026-09-08 — see `docs/decisions.md`'s "Module
system follow-up: on_org_created / project_nav_visible hooks" entry).

`app.modules.compliance.module._seed_org_defaults` (this module's
`ModuleDefinition.on_org_created` hook) is what actually seeds a brand-new
organisation's default compliance action types, called generically by
`app.modules.registry.run_on_org_created_hooks` from both
`routers.orgs.create_organization` and `services.bootstrap.run_bootstrap`
rather than either of those core files importing this module directly. This
behaviour existed before the cleanup (as a direct import in each caller) but
had no test of its own pinning it against regression — added here, not just
moved, since the generic-dispatch mechanism itself (`test_module_registry
.py::test_run_on_org_created_hooks_calls_every_registered_hook`) proves only
that *a* hook gets called, not that *this* module's specific seeding still
happens end-to-end through the real `POST /orgs` endpoint.
"""

from __future__ import annotations

from app.modules.compliance.service import DEFAULT_COMPLIANCE_ACTION_TYPES
from tests.conftest import auth_headers


def test_creating_an_org_seeds_default_compliance_action_types(client, admin_token):
    resp = client.post("/api/v1/orgs", json={"name": "Org Creation Seeding Test Co"}, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    # `POST /orgs` is server-admin-only and grants no org membership of its
    # own (a server admin isn't automatically a member of every org) — join
    # as admin first so the module's own `require_org_module_enabled`-gated
    # listing endpoint doesn't 404 for "not a member of this org at all",
    # which would be indistinguishable from a real seeding failure here.
    join = client.post(f"/api/v1/orgs/{org_id}/join-as-admin", headers=auth_headers(admin_token))
    assert join.status_code == 204, join.text

    listed = client.get(
        f"/api/v1/orgs/{org_id}/modules/compliance/action-types", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200, listed.text
    names = {a["name"] for a in listed.json()}
    assert names == set(DEFAULT_COMPLIANCE_ACTION_TYPES)
