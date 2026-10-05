"""Tests for Context & Strategy's Phase 6 backend API (docs/plans/
module-01-context-and-strategy-plan.md Phase 6 — Cross-artefact
relationships) — the real HTTP endpoints this phase added to both
`project_router.py` (all five source artefact types) and `router.py`
(Strategy/Future State/Guiding Principle's org-scoped halves), through the
`client` fixture, mirroring every sibling artefact-type test file's own
"go through the real API" convention. A new sibling file, matching
Phase 2-5's own precedent (one file per concern).

Covers: typed relationship creation (Pain Point -> drives -> Strategy,
Strategy -> drives -> Requirement, Strategy -> defines -> Future State,
Guiding Principle -> informs -> Requirement), an untyped "related to"
association (Future State -> Pain Point), duplicate-link rejection (409),
cross-organisation rejection (409), plain-member-cannot-create (403) vs.
manager-can-create, org-scoped Strategy relationship creation (`router.py`),
Strategy supersession (the deferred `ArtefactLink` side effect Phase 1
promised this phase would add — creates the typed link *and* transitions
the old Strategy to `Superseded`), and the MCP AI-approvals gate on
`approve_strategy` (one of Phase 6's five gated tools) as a representative
case, mirroring `test_decisions_ai_approvals_via_mcp.py`'s own pattern.

No `RequirementLinkTypeDefinition` reuse-across-relationship-shape claims
are asserted for every single kind — `test_context_strategy_relationships_
api.py`'s own scope is proving the *mechanism* (generic dispatcher, typed
vs. untyped, RBAC, cross-org rejection, supersession) works correctly, not
exhaustively re-testing all fifteen or so relationship kinds one by one
(each is a one-line dict entry in `service.py`, not independent logic).
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)
from tests.test_ai_approvals_via_mcp import _mcp_headers, _set_org_ai_approvals, _set_project_ai_approvals

MODULE_KEY = "context_strategy"


# --- Small API helpers -------------------------------------------------------


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/context_strategy"


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/context_strategy"


def _enable_module(client, org_admin_token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, org_name: str):
    """Creates an org (with a real org_admin), a project (the org_admin
    becomes its `PROJECT_MANAGER`), and enables Context & Strategy.
    Returns (org, project, org_admin_token)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    _enable_module(client, org_admin_token, org["id"])
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    return org, project, org_admin_token


def _add_plain_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _create_strategy(client, token, project_id, **extra) -> dict:
    payload = {"title": "Lead the market", "objective": "Become #1 in the segment", **extra}
    resp = client.post(_project_base(project_id) + "/strategies", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_org_strategy(client, token, org_id, **extra) -> dict:
    payload = {"title": "Org strategy", "objective": "Grow the portfolio", **extra}
    resp = client.post(_org_base(org_id) + "/strategies", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_future_state(client, token, project_id, **extra) -> dict:
    payload = {"title": "Fully automated inspections", **extra}
    resp = client.post(_project_base(project_id) + "/future-states", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_org_future_state(client, token, org_id, **extra) -> dict:
    payload = {"title": "Org future state", **extra}
    resp = client.post(_org_base(org_id) + "/future-states", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _market_pain_point_type_id(client, token, project_id) -> str:
    resp = client.get(_project_base(project_id) + "/pain-point-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return next(t for t in resp.json() if t["name"] == "Market")["id"]


def _create_pain_point(client, token, project_id, **extra) -> dict:
    payload = {
        "pain_point_type_id": _market_pain_point_type_id(client, token, project_id),
        "title": "Report delays", "description": "Reports are late.",
        **extra,
    }
    resp = client.post(_project_base(project_id) + "/pain-points", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_guiding_principle(client, token, project_id, **extra) -> dict:
    payload = {"name": "Safety first", "principle_statement": "Never compromise on operator safety.", **extra}
    resp = client.post(_project_base(project_id) + "/guiding-principles", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_open_question(client, token, project_id, **extra) -> dict:
    payload = {"question": "Which battery vendor should we standardise on?", **extra}
    resp = client.post(_project_base(project_id) + "/open-questions", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_requirement(client, token, project_id, component_id, category_id, name="Req") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_strategy_to_active(client, token, project_id, strategy_id) -> None:
    base = f"{_project_base(project_id)}/strategies/{strategy_id}"
    for action in ("propose", "submit-for-review", "approve", "activate"):
        resp = client.post(f"{base}/{action}", json={}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text


# --- Typed relationships -------------------------------------------------------


def test_pain_point_drives_strategy_relationship(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships PP Drives Strategy Co")
    strategy = _create_strategy(client, token, project["id"])
    pain_point = _create_pain_point(client, token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships",
        json={"kind": "drives_strategy", "target_id": strategy["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_type"] == "pain_point"
    assert body["target_type"] == "strategy"
    assert body["direction"] == "outgoing"
    assert body["display_name"] == "Drives"
    assert body["other_display_name"] == "Lead the market"

    resp = client.get(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    # Same relationship visible from the Strategy's own side, incoming.
    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/relationships", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    [link] = resp.json()
    assert link["direction"] == "incoming"
    assert link["display_name"] == "Is driven by"


def test_duplicate_relationship_is_rejected(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships Duplicate Co")
    strategy = _create_strategy(client, token, project["id"])
    pain_point = _create_pain_point(client, token, project["id"])
    payload = {"kind": "drives_strategy", "target_id": strategy["id"]}

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships", json=payload,
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships", json=payload,
        headers=auth_headers(token),
    )
    assert resp.status_code == 409, resp.text


def test_strategy_drives_requirement_relationship_reuses_pain_point_link_type(client, admin_token):
    """`Strategy -> drives -> Requirement` deliberately reuses the same org
    `"Drives"` link type `PainPoint -> drives -> Strategy` uses — see
    `service.StrategyLinkKind`'s own docstring."""
    org, project, token = _setup(client, admin_token, "Relationships Strategy Drives Requirement Co")
    strategy = _create_strategy(client, token, project["id"])
    pain_point = _create_pain_point(client, token, project["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id, "Access control")

    client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships",
        json={"kind": "drives_strategy", "target_id": strategy["id"]}, headers=auth_headers(token),
    )
    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/relationships",
        json={"kind": "drives_requirement", "target_id": requirement["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["target_type"] == "requirement"
    assert resp.json()["other_display_code"] == requirement["unique_code"]

    db = SessionLocal()
    try:
        drives_link_types = db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == "Drives",
        ).all()
    finally:
        db.close()
    assert len(drives_link_types) == 1, "Pain Point->Strategy and Strategy->Requirement should share one 'Drives' link type."


def test_guiding_principle_informs_requirement_relationship(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships GP Informs Requirement Co")
    guiding_principle = _create_guiding_principle(client, token, project["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id, "Latency budget")

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/relationships",
        json={"kind": "informs_requirement", "target_id": requirement["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["display_name"] == "Informs"


def test_future_state_related_to_pain_point_is_untyped(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships FS Related PP Co")
    future_state = _create_future_state(client, token, project["id"])
    pain_point = _create_pain_point(client, token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/relationships",
        json={"kind": "related_to_pain_point", "target_id": pain_point["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["link_type_id"] is None
    assert body["display_name"] == "Related to"


def test_strategy_defines_future_state_relationship(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships Strategy Defines FS Co")
    strategy = _create_strategy(client, token, project["id"])
    future_state = _create_future_state(client, token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/relationships",
        json={"kind": "defines_future_state", "target_id": future_state["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["display_name"] == "Defines"


def test_org_scoped_strategy_defines_org_scoped_future_state(client, admin_token):
    """The retrofit case this phase's own brief calls out: an org-scoped
    Strategy and an org-scoped Future State, linked via `router.py`'s
    org-scoped relationship endpoint."""
    org, project, org_admin_token = _setup(client, admin_token, "Relationships Org Strategy Defines Org FS Co")
    strategy = _create_org_strategy(client, org_admin_token, org["id"])
    future_state = _create_org_future_state(client, org_admin_token, org["id"])

    resp = client.post(
        f"{_org_base(org['id'])}/strategies/{strategy['id']}/relationships",
        json={"kind": "defines_future_state", "target_id": future_state["id"]}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(
        f"{_org_base(org['id'])}/strategies/{strategy['id']}/relationships", headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


def test_cross_organisation_relationship_is_rejected(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Relationships Cross Org A")
    org_b, project_b, token_b = _setup(client, admin_token, "Relationships Cross Org B")
    strategy_a = _create_strategy(client, token_a, project_a["id"])
    pain_point_b = _create_pain_point(client, token_b, project_b["id"])

    resp = client.post(
        f"{_project_base(project_b['id'])}/pain-points/{pain_point_b['id']}/relationships",
        json={"kind": "drives_strategy", "target_id": strategy_a["id"]}, headers=auth_headers(token_b),
    )
    assert resp.status_code == 409, resp.text


def test_plain_member_cannot_create_relationship(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Relationships RBAC Co")
    strategy = _create_strategy(client, org_admin_token, project["id"])
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "relationships_member@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships",
        json={"kind": "drives_strategy", "target_id": strategy["id"]}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


# --- Supersession ----------------------------------------------------------


def test_strategy_supersession_creates_link_and_supersedes_old_strategy(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships Supersession Co")
    old_strategy = _create_strategy(client, token, project["id"], title="Falcon-2 era strategy")
    _advance_strategy_to_active(client, token, project["id"], old_strategy["id"])
    new_strategy = _create_strategy(client, token, project["id"], title="Falcon-3 era strategy")

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{new_strategy['id']}/supersessions",
        json={"old_strategy_id": old_strategy["id"], "comment": "Falcon-3 supersedes the Falcon-2 strategy."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_id"] == new_strategy["id"]
    assert body["target_id"] == old_strategy["id"]
    assert body["display_name"] == "Supersedes"

    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{old_strategy['id']}", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "superseded"


def test_strategy_supersession_of_non_active_strategy_is_409(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships Supersession Illegal Co")
    old_strategy = _create_strategy(client, token, project["id"], title="Still-draft strategy")
    new_strategy = _create_strategy(client, token, project["id"], title="New strategy")

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{new_strategy['id']}/supersessions",
        json={"old_strategy_id": old_strategy["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 409, resp.text


# --- MCP AI-approvals gate (representative case) ----------------------------


def test_approve_strategy_via_mcp_requires_ai_approvals_enabled(client, admin_token):
    """One of Phase 6's five `require_ai_approvals_enabled`-gated MCP
    tools (`approve_strategy`) — representative coverage, mirroring
    `test_decisions_ai_approvals_via_mcp.py`'s own pattern rather than
    repeating it for all five gated tools (the gate itself is generic,
    already covered end-to-end by that module's own test suite)."""
    org, project, token = _setup(client, admin_token, "Relationships MCP Approve Co")
    strategy = _create_strategy(client, token, project["id"])
    base = f"{_project_base(project['id'])}/strategies/{strategy['id']}"
    client.post(f"{base}/propose", json={}, headers=auth_headers(token))
    client.post(f"{base}/submit-for-review", json={}, headers=auth_headers(token))

    # MCP-originated, neither flag enabled yet: rejected.
    resp = client.post(f"{base}/approve", json={}, headers=_mcp_headers(token))
    assert resp.status_code == 403, resp.text

    # A plain UI/API call is unaffected by the flags either way.
    resp = client.post(f"{base}/approve", json={}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_approve_strategy_via_mcp_succeeds_once_both_flags_enabled(client, admin_token):
    org, project, token = _setup(client, admin_token, "Relationships MCP Approve Enabled Co")
    strategy = _create_strategy(client, token, project["id"])
    base = f"{_project_base(project['id'])}/strategies/{strategy['id']}"
    client.post(f"{base}/propose", json={}, headers=auth_headers(token))
    client.post(f"{base}/submit-for-review", json={}, headers=auth_headers(token))

    _set_org_ai_approvals(client, token, org["id"], True)
    _set_project_ai_approvals(client, token, project["id"], True)

    resp = client.post(f"{base}/approve", json={}, headers=_mcp_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_deleting_the_org_removes_its_artefact_links_and_type_overrides(client, admin_token):
    """Deleting an organisation that has linked Context & Strategy artefacts
    and a project pain-point type override succeeds and leaves no orphaned
    links (2026-10-05: it returned a 500 — links blocked its link types'
    deletion, and depending on cascade order an override's `SET NULL` FK
    broke its CHECK constraint; org deletion now removes projects first)."""
    from sqlalchemy import or_, select

    from app.models.relationship import ArtefactLink
    from app.modules.context_strategy.models import ProjectPainPointType

    org, project, token = _setup(client, admin_token, "Relationships Org Delete Co")
    strategy = _create_strategy(client, token, project["id"])
    org_strategy = _create_org_strategy(client, token, org["id"])
    pain_point = _create_pain_point(client, token, project["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/relationships",
        json={"kind": "drives_strategy", "target_id": strategy["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    market_id = _market_pain_point_type_id(client, token, project["id"])
    resp = client.put(f"{_project_base(project['id'])}/pain-point-types/{market_id}", json={"is_enabled": False},
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.text

    resp = client.request("DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]},
                          headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text

    ids = [uuid.UUID(x) for x in (strategy["id"], org_strategy["id"], pain_point["id"])]
    db = SessionLocal()
    try:
        assert db.scalars(select(ArtefactLink.id).where(
            or_(ArtefactLink.source_id.in_(ids), ArtefactLink.target_id.in_(ids))
        )).all() == []
        assert db.scalars(select(ProjectPainPointType.id).where(
            ProjectPainPointType.project_id == uuid.UUID(project["id"])
        )).all() == []
    finally:
        db.close()
