"""
Module: scripts.seed_e2e_dataset

Seeds a fixed, multi-org, multi-persona dataset used by the Playwright suite
under tests/playwright/tests/e2e-workflows/ (see docs/e2e-workflows.md for
the full persona/workflow catalogue this backs).

Design notes:
- Every org/user/project/requirement/change-request is created through the
  real HTTP API (not direct DB writes), including the zero-org server-admin
  persona's org departure — it calls DELETE /orgs/{id}/membership on itself,
  the same self-service "leave organisation" endpoint added specifically to
  close this gap (see docs/e2e-workflows.md).
- RBAC constraint that shapes the script's odd-looking ordering: creating a
  brand-new organisation grants the creator (a server admin) no role in it,
  and only `create_org_user` (creating a brand-new *user*) has a
  server-admin carve-out — `assign_org_role` always requires the caller to
  already be an org_admin of that specific org. So a persona who needs
  org_admin (or member) status in a *second* org can't get it directly from
  the server admin; a throwaway "bootstrap helper" user is created as that
  second org's first org_admin (via the create-user carve-out) purely so it
  can then grant the real persona a role there, exactly as a human admin
  handing off access would.

Run via (from tests/container):
    docker compose exec backend python scripts/seed_e2e_dataset.py

Idempotent: exits without changes if "E2E Alpha Robotics" already exists.
Intended primary usage is against a freshly migrated database.
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe123!"
PASSWORD = "E2ePass123!"

REQUIREMENT_NAMES = [
    "Must respond to input within 50ms",
    "Must support configuration via file",
    "Must log all state transitions",
    "Must recover automatically after a fault",
    "Must expose a health-check endpoint",
    "Must support role-based access control",
    "Must validate all external input",
    "Must run on the target hardware profile",
]


def login(email: str, password: str) -> str:
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_org(admin_headers: dict, name: str) -> dict:
    r = httpx.post(f"{BASE}/orgs", json={"name": name}, headers=admin_headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_org_user(admin_headers: dict, org_id: str, email: str, display_name: str, role: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/users",
        json={"email": email, "display_name": display_name, "password": PASSWORD, "role": role},
        headers=admin_headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def assign_org_role(org_admin_headers: dict, org_id: str, user_id: str, role: str) -> None:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/users/{user_id}/roles", json={"user_id": user_id, "role": role},
        headers=org_admin_headers, timeout=30,
    )
    r.raise_for_status()


def create_project(
    headers: dict, org_id: str, name: str, summary: str,
    *, parent_project_id: str | None = None, role_inheritance_mode: str | None = None,
    role_inheritance_filter_role: str | None = None,
) -> dict:
    payload: dict = {"organization_id": org_id, "name": name, "summary": summary}
    if parent_project_id is not None:
        payload["parent_project_id"] = parent_project_id
    if role_inheritance_mode is not None:
        payload["role_inheritance_mode"] = role_inheritance_mode
    if role_inheritance_filter_role is not None:
        payload["role_inheritance_filter_role"] = role_inheritance_filter_role
    r = httpx.post(f"{BASE}/projects", json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def add_member_source(headers: dict, project_id: str, source_project_id: str) -> None:
    """Adds `source_project_id` (a direct child of `project_id`) to
    `project_id`'s member-source list — the reverse (child -> parent) RBAC
    mechanism, authorized by managing the parent (`project_id`), per
    docs/decisions.md's "Hierarchical projects" entry."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/member-sources", json={"source_project_id": source_project_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def assign_project_role(headers: dict, project_id: str, user_id: str, role: str) -> None:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def set_project_terminology(headers: dict, project_id: str, terminology: dict[str, str]) -> dict:
    """Sets a project's per-project terminology overrides (C-C-03), the same
    `PUT /projects/{id}/terminology` endpoint Project Admin's Terminology tab
    uses. See TERMINOLOGY_PROJECT_NAME's docstring below for why this is a
    dedicated, 7th seeded project rather than applied to one of the 6
    projects every other spec already reuses."""
    r = httpx.put(f"{BASE}/projects/{project_id}/terminology", json={"terminology": terminology}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


# Fixed, deliberate values the terminology-override Playwright spec asserts
# against verbatim (see docs/decisions.md's terminology entry) — a project
# dedicated solely to that spec, not one of the 6 "Alpha/Beta/Gamma-N"
# projects every other e2e-workflows spec already reuses for its own
# assertions (several of which check exact default-English button/nav text
# that a terminology override would otherwise break). No other spec may
# depend on this project's terminology staying at, or moving away from,
# these values.
TERMINOLOGY_PROJECT_NAME = "Delta-1 Terminology Demo"
TERMINOLOGY_OVERRIDE = {"stage": "Phase", "requirement": "Spec", "change_request": "ECR"}

# Fixed hierarchy fixture for project-hierarchy.spec.ts — Gamma-4 mirrors
# all roles from Gamma-3 (forward), and Gamma-3 also consumes members from
# Gamma-4 (reverse, member-source). See docs/decisions.md's "Hierarchical
# projects" entry. No other spec may depend on this pair's configuration.
GAMMA3_NAME = "Gamma-3 Hierarchy Parent"
GAMMA4_NAME = "Gamma-4 Hierarchy Child"


def create_component(headers: dict, project_id: str, name: str, prefix: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/components", json={"name": name, "prefix": prefix}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_category(headers: dict, project_id: str, component_id: str, name: str, prefix: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/categories",
        json={"name": name, "prefix": prefix, "component_id": component_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_requirement(headers: dict, project_id: str, name: str, reasoning: str, component_id: str, category_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements",
        json={"name": name, "reasoning": reasoning, "component_id": component_id, "category_id": category_id, "keywords": []},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_link_type(headers: dict, org_id: str, *, forward_name: str, reverse_name: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/link-types", json={"forward_name": forward_name, "reverse_name": reverse_name},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_requirement_link(headers: dict, project_id: str, requirement_id: str, target_requirement_id: str, link_type_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/links",
        json={"target_requirement_id": target_requirement_id, "link_type_id": link_type_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_and_link_action(headers: dict, project_id: str, requirement_id: str, *, title: str, action_type_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/actions/create-and-link",
        json={"title": title, "description": "E2E seed action.", "action_type_id": action_type_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_action_outcome(headers: dict, project_id: str, action: dict, outcome_status: str) -> dict:
    r = httpx.patch(
        f"{BASE}/projects/{project_id}/actions/{action['id']}",
        json={
            "title": action["title"], "description": action["description"], "action_type_id": action["action_type_id"],
            "outcome_status": outcome_status,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def seed_project_content(headers: dict, project: dict, req_count: int) -> list[dict]:
    """Adds two components, two categories, and `req_count` requirements to a project."""
    hw = create_component(headers, project["id"], "Hardware", "HW")
    sw = create_component(headers, project["id"], "Software", "SW")
    fn = create_category(headers, project["id"], hw["id"], "Functional", "FN")
    perf = create_category(headers, project["id"], sw["id"], "Performance", "PERF")
    reqs = []
    for i in range(req_count):
        name = REQUIREMENT_NAMES[i % len(REQUIREMENT_NAMES)]
        if i >= len(REQUIREMENT_NAMES):
            name = f"{name} (variant {i // len(REQUIREMENT_NAMES) + 1})"
        component = hw if i % 2 == 0 else sw
        category = fn if i % 2 == 0 else perf
        reqs.append(create_requirement(headers, project["id"], name, f"Reasoning: {name.lower()}.", component["id"], category["id"]))
    return reqs


def main() -> None:
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    h_admin = h(admin_token)

    existing_orgs = httpx.get(f"{BASE}/orgs", headers=h_admin, timeout=30).json()
    if any(o["name"] == "E2E Alpha Robotics" for o in existing_orgs):
        print("E2E dataset already seeded (found 'E2E Alpha Robotics'). Exiting without changes.")
        return

    print("Creating organisations...")
    alpha = create_org(h_admin, "E2E Alpha Robotics")
    beta = create_org(h_admin, "E2E Beta Software")
    gamma = create_org(h_admin, "E2E Gamma Labs")

    print("Creating persona users...")
    serveradmin = create_org_user(h_admin, alpha["id"], "e2e-serveradmin@example.com", "E2E Server Admin Only", "member")
    orgadmin_ab = create_org_user(h_admin, alpha["id"], "e2e-orgadmin-ab@example.com", "E2E OrgAdmin AlphaBeta", "org_admin")
    create_org_user(h_admin, gamma["id"], "e2e-orgadmin-g@example.com", "E2E OrgAdmin Gamma", "org_admin")
    stakeholder_a = create_org_user(h_admin, alpha["id"], "e2e-stakeholder-a@example.com", "E2E Stakeholder AlphaOnly", "member")
    stakeholder_a2 = create_org_user(h_admin, alpha["id"], "e2e-stakeholder-a2@example.com", "E2E Stakeholder AlphaOnly Two", "member")
    member_ab = create_org_user(h_admin, alpha["id"], "e2e-member-ab@example.com", "E2E Member AlphaBeta", "member")
    create_org_user(h_admin, alpha["id"], "e2e-orphan@example.com", "E2E Orphan Candidate", "member")
    # No org-level role at all — deliberately, for project-hierarchy.spec.ts:
    # exercises the relaxed parent-manage-only child-creation path (decision
    # 11, docs/decisions.md), which must work for a plain project manager
    # with zero org-level standing, and the `parent_required` bypass-closure
    # block that keeps them from detaching what they create that way.
    projectmgr_g = create_org_user(h_admin, gamma["id"], "e2e-projectmgr-g@example.com", "E2E ProjectMgr Gamma Only", "member")

    # Bootstrap helper: no product endpoint lets a server admin grant a role
    # in an org they don't already belong to (assign_org_role requires a
    # genuine org_admin caller) — only creating a brand-new user has that
    # carve-out. So a throwaway user becomes Beta's first org_admin purely
    # to hand orgadmin_ab and member_ab their second-org roles, mirroring
    # how a real admin handoff would work. Not one of the documented
    # personas; never logged into by the Playwright suite.
    create_org_user(h_admin, beta["id"], "e2e-bootstrap-beta@example.com", "E2E Bootstrap Helper (Beta)", "org_admin")
    h_beta_bootstrap = h(login("e2e-bootstrap-beta@example.com", PASSWORD))
    assign_org_role(h_beta_bootstrap, beta["id"], orgadmin_ab["user_id"], "org_admin")
    assign_org_role(h_beta_bootstrap, beta["id"], member_ab["user_id"], "member")

    print("Granting server-admin to the zero-org persona...")
    r = httpx.put(
        f"{BASE}/system/users/{serveradmin['user_id']}/server-admin", json={"is_server_admin": True},
        headers=h_admin, timeout=30,
    )
    r.raise_for_status()

    print("Zero-org persona leaves Alpha through the self-service endpoint...")
    h_serveradmin = h(login("e2e-serveradmin@example.com", PASSWORD))
    r = httpx.delete(f"{BASE}/orgs/{alpha['id']}/membership", headers=h_serveradmin, timeout=30)
    r.raise_for_status()

    print("Orphan candidate leaves Alpha through the same self-service endpoint, for the user-directory/ban workflow...")
    h_orphan = h(login("e2e-orphan@example.com", PASSWORD))
    r = httpx.delete(f"{BASE}/orgs/{alpha['id']}/membership", headers=h_orphan, timeout=30)
    r.raise_for_status()

    h_ab = h(login("e2e-orgadmin-ab@example.com", PASSWORD))
    h_g = h(login("e2e-orgadmin-g@example.com", PASSWORD))

    print("Setting Alpha's outgoing-email branding (org-level footer override)...")
    r = httpx.put(
        f"{BASE}/orgs/{alpha['id']}/branding",
        json={
            "accent_color_hex": None, "header_title": None,
            "email_footer_company_name": "E2E Alpha Robotics",
            "email_footer_website": "https://alpha-robotics.example.com",
            "email_footer_address": "1 Test Fixture Way\nAlpha City, AC 00001",
        },
        headers=h_ab, timeout=30,
    )
    r.raise_for_status()

    print("Creating projects (2 per org)...")
    alpha1 = create_project(h_ab, alpha["id"], "Alpha-1 Robotic Arm Controller", "E2E seed project.")
    alpha2 = create_project(h_ab, alpha["id"], "Alpha-2 Sensor Fusion Platform", "E2E seed project.")
    beta1 = create_project(h_ab, beta["id"], "Beta-1 Billing Engine", "E2E seed project.")
    beta2 = create_project(h_ab, beta["id"], "Beta-2 Customer Portal", "E2E seed project.")
    gamma1 = create_project(h_g, gamma["id"], "Gamma-1 Lab Instrument Suite", "E2E seed project.")
    gamma2 = create_project(h_g, gamma["id"], "Gamma-2 Data Pipeline", "E2E seed project.")

    print(f"Creating {GAMMA3_NAME!r} / {GAMMA4_NAME!r} (fixed project-hierarchy fixture for project-hierarchy.spec.ts)...")
    gamma3 = create_project(h_g, gamma["id"], GAMMA3_NAME, "E2E seed project — hierarchy parent fixture.")
    gamma4 = create_project(
        h_g, gamma["id"], GAMMA4_NAME, "E2E seed project — hierarchy child fixture.",
        parent_project_id=gamma3["id"], role_inheritance_mode="mirror_all",
    )
    # Reverse direction (child -> parent), authorized by managing the
    # parent: Gamma-3 consumes members from Gamma-4 too, so the same fixed
    # pair demonstrates both RBAC-cascade mechanisms at once.
    add_member_source(h_g, gamma3["id"], gamma4["id"])

    print(f"Creating {TERMINOLOGY_PROJECT_NAME!r} and setting its terminology override (C-C-03)...")
    delta1 = create_project(
        h_ab, alpha["id"], TERMINOLOGY_PROJECT_NAME,
        "E2E seed project dedicated to the terminology-override Playwright spec.",
    )
    set_project_terminology(h_ab, delta1["id"], TERMINOLOGY_OVERRIDE)

    print("Assigning project-scoped roles...")
    assign_project_role(h_ab, alpha1["id"], stakeholder_a["user_id"], "stakeholder")
    assign_project_role(h_ab, alpha1["id"], stakeholder_a2["user_id"], "stakeholder")
    assign_project_role(h_ab, alpha1["id"], member_ab["user_id"], "member")
    assign_project_role(h_ab, beta1["id"], member_ab["user_id"], "member")
    assign_project_role(h_g, gamma1["id"], projectmgr_g["user_id"], "project_manager")
    # A direct (non-inherited) role on Gamma-3 only, so it shows up on
    # Gamma-4 as forward-inherited (mirror_all) — orgAdminGamma is a direct
    # PM on both Gamma-3 and Gamma-4 already (project-creation seeding), so
    # they can't demonstrate the "inherited, not direct" provenance case.
    assign_project_role(h_g, gamma3["id"], projectmgr_g["user_id"], "stakeholder")

    print("Seeding requirements (6-8 per project)...")
    alpha1_reqs = seed_project_content(h_ab, alpha1, 8)
    seed_project_content(h_ab, alpha2, 6)
    beta1_reqs = seed_project_content(h_ab, beta1, 7)
    seed_project_content(h_ab, beta2, 6)
    gamma1_reqs = seed_project_content(h_g, gamma1, 7)
    seed_project_content(h_g, gamma2, 6)
    delta1_reqs = seed_project_content(h_ab, delta1, 3)

    print("Locking Delta-1's first requirement so terminology-coverage.spec.ts can reach its 'Make {changeRequest}' link"
          " (only rendered once a requirement is locked, 2026-08 UX audit roadmap 'No requirement approval action')...")
    r = httpx.post(f"{BASE}/projects/{delta1['id']}/requirements/{delta1_reqs[0]['id']}/approve", headers=h_ab, timeout=30)
    r.raise_for_status()

    print("Locking one Alpha-1 requirement (approves it directly) for the CR-approval and bypass-attempt workflows...")
    locked_req = alpha1_reqs[0]
    r = httpx.put(
        f"{BASE}/projects/{alpha1['id']}/requirements/{locked_req['id']}",
        json={
            "name": locked_req["name"], "reasoning": locked_req["reasoning"], "clarification": "",
            "component_id": locked_req["component_id"], "category_id": locked_req["category_id"],
            "owner_id": locked_req["owner_id"], "status": "approved", "keywords": [],
            "change_note": "E2E seed: locking for change-request workflow testing.",
        },
        headers=h_ab, timeout=30,
    )
    r.raise_for_status()

    print("Seeding a couple of pre-existing change requests for volume...")
    for headers, project, reqs in [(h_ab, beta1, beta1_reqs), (h_g, gamma1, gamma1_reqs)]:
        target = reqs[1]
        # A modify change request can only target an already-locked
        # requirement (2026-08 UX audit roadmap, "No requirement approval
        # action; change requests can target draft requirements") — approve
        # it directly first.
        r = httpx.post(f"{BASE}/projects/{project['id']}/requirements/{target['id']}/approve", headers=headers, timeout=30)
        r.raise_for_status()
        r = httpx.post(
            f"{BASE}/projects/{project['id']}/change-requests",
            json={
                "kind": "modify_requirement", "requirement_id": target["id"],
                "changed_fields": ["name", "reasoning"],
                "proposed_name": target["name"], "proposed_reasoning": target["reasoning"],
                "reason": "E2E seed: pre-existing change request for volume.",
            },
            headers=headers, timeout=30,
        )
        r.raise_for_status()

    print("Adding a custom link type and fixed requirement links/actions on Alpha-1, for the requirement-links "
          "and requirement-actions E2E specs...")
    e2e_link_type = create_link_type(h_ab, alpha["id"], forward_name="E2E Supersedes", reverse_name="E2E Is superseded by")
    create_requirement_link(h_ab, alpha1["id"], alpha1_reqs[1]["id"], alpha1_reqs[0]["id"], e2e_link_type["id"])
    alpha1_action_types = {t["name"]: t for t in httpx.get(f"{BASE}/projects/{alpha1['id']}/action-types", headers=h_ab, timeout=30).json()}
    e2e_review_action = create_and_link_action(
        h_ab, alpha1["id"], alpha1_reqs[2]["id"], title="E2E Review Action", action_type_id=alpha1_action_types["Review"]["id"],
    )
    set_action_outcome(h_ab, alpha1["id"], e2e_review_action, "completed")
    create_and_link_action(
        h_ab, alpha1["id"], alpha1_reqs[3]["id"], title="E2E Test Action", action_type_id=alpha1_action_types["Test"]["id"],
    )

    print("\nDone. Personas (all password: E2ePass123!):")
    print("  e2e-serveradmin@example.com   - server admin, zero org memberships")
    print("  e2e-orgadmin-ab@example.com   - org_admin of Alpha + Beta; PM on all 4 of those projects")
    print("  e2e-orgadmin-g@example.com    - org_admin of Gamma only; PM on both Gamma projects")
    print("  e2e-stakeholder-a@example.com - stakeholder on Alpha-1 only")
    print("  e2e-stakeholder-a2@example.com - second stakeholder on Alpha-1 only (for vote-tally coverage)")
    print("  e2e-member-ab@example.com     - member on Alpha-1 and Beta-1; no org-admin/project-creator rights anywhere")
    print("  e2e-orphan@example.com        - zero org memberships (left Alpha via self-service); for user-directory/ban workflow")
    print("  e2e-projectmgr-g@example.com  - Gamma member only (no org-admin/project-creator); PM on Gamma-1,"
          " stakeholder on Gamma-3 (direct, shows up as forward-inherited on Gamma-4)")
    print(f"\n{GAMMA3_NAME!r} (id {gamma3['id']}) mirror-all-inherits into {GAMMA4_NAME!r} (id {gamma4['id']});"
          f" {GAMMA3_NAME!r} also consumes members from {GAMMA4_NAME!r} (member-source) — fixed project-hierarchy.spec.ts fixture.")
    print(f"\nLocked requirement for CR workflow: {locked_req['unique_code']} ({locked_req['name']}) in Alpha-1 ({alpha1['id']})")
    print(f"Custom link type 'E2E Supersedes' on Alpha, requirement link {alpha1_reqs[1]['unique_code']} -> {alpha1_reqs[0]['unique_code']}")
    print("Requirement actions: 'E2E Review Action' (completed) and 'E2E Test Action' (pending) on Alpha-1")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Seed failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
