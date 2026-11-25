"""
Module: scripts.seed_service_users

Gives a seeded organisation two service users: one with no token yet (so the empty state and the Issue token action can
be seen) and one with a token that was issued and then revoked (so the history of a revoked token can be seen).

Responsibilities:
- `seed_service_users`: creates them through the API as an organisation administrator, responsible principal included.

Design decisions:
- Never issues a token that stays live: a secret must not exist in a seeded dataset, and the revoked one is revoked in
  the same run, so the printed secret is already dead.
- Idempotent: a service user that already exists (HTTP 409 on its name) is left as it is.

External dependencies: `httpx`, the running API.
"""

from __future__ import annotations

import httpx


def seed_service_users(base: str, org_admin_headers: dict, organization_id: str, responsible_user_id: str) -> list[str]:
    """Creates the two service users.

    Args:
        base: The API root (`http://localhost:8000/api/v1`).
        org_admin_headers: Authorization headers of an administrator of the organisation.
        organization_id: The seeded organisation.
        responsible_user_id: A member of the organisation to name as the responsible principal of the first one; the
            second is left without one so the access review has a flagged example.

    Returns:
        The names of the service users that exist afterwards.
    """
    url = f"{base}/orgs/{organization_id}/service-users"
    names = []
    idle = httpx.post(
        url, headers=org_admin_headers, timeout=30,
        json={
            "name": "Idle integration agent", "description": "Reads requirements for a nightly report; no token issued yet.",
            "responsible": {"type": "user", "id": responsible_user_id},
        },
    )
    retired = httpx.post(
        url, headers=org_admin_headers, timeout=30,
        json={"name": "Retired build agent", "description": "Posted build results; its token has been revoked."},
    )
    for response, name in ((idle, "Idle integration agent"), (retired, "Retired build agent")):
        if response.status_code not in (201, 409):
            raise RuntimeError(f"Could not create service user {name!r}: {response.status_code} {response.text}")
        names.append(name)
    if retired.status_code == 201:
        user_id = retired.json()["user_id"]
        issued = httpx.post(
            f"{url}/{user_id}/pats", headers=org_admin_headers, timeout=30, json={"name": "build-token (revoked)"}
        )
        issued.raise_for_status()
        httpx.delete(f"{url}/{user_id}/pats/{issued.json()['id']}", headers=org_admin_headers, timeout=30).raise_for_status()
    return names
