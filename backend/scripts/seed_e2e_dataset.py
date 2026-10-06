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
    role_inheritance_filter_role: str | None = None, can_be_parent: bool = False,
) -> dict:
    payload: dict = {"organization_id": org_id, "name": name, "summary": summary}
    if parent_project_id is not None:
        payload["parent_project_id"] = parent_project_id
    if role_inheritance_mode is not None:
        payload["role_inheritance_mode"] = role_inheritance_mode
    if role_inheritance_filter_role is not None:
        payload["role_inheritance_filter_role"] = role_inheritance_filter_role
    if can_be_parent:
        payload["can_be_parent"] = True
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


def create_compliance_standard(headers: dict, org_id: str, *, reference: str, name: str) -> dict:
    """Creates a `ComplianceStandard` together with its mandatory first
    version (§2/§4) — mirrors `backend/scripts/seed_demo_data.py`'s own
    `create_compliance_standard` helper, trimmed to only the fields this
    file's own single seeded standard needs (see FGAC_STANDARD_NAME's own
    comment below for why this file needs one at all)."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards",
        json={"reference": reference, "name": name, "initial_version_label": "1.0"},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


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

# A real, standing compliance standard for Alpha — Fine-Grained Access
# Control Phase 6 (`docs/plans/core-fine-grained-access-control-plan.md`)
# needs one real registered `"standard"` entity-scope entity for role-
# management.spec.ts's entity-picker coverage to select (Phase 5 built the
# picker generically; this module's own compliance standard is its first
# real thing to pick). This module previously had no seeded data in this
# script at all.
FGAC_STANDARD_REFERENCE = "FGAC-1"
FGAC_STANDARD_NAME = "FGAC Demo Standard"

# Platform review 2026-09, Phase 8: a project dedicated solely to the
# require-change-request-for-links Playwright coverage, per this file's own
# established "dedicated project, not a shared one" convention (see
# TERMINOLOGY_PROJECT_NAME's own comment just above, and GAMMA3_NAME/
# GAMMA4_NAME below) — Alpha-1's own already-fixed links/actions (below)
# make it unsuitable for a project-level setting change, and Delta-1 is
# explicitly reserved for terminology-override coverage alone.
LINK_LOCK_PROJECT_NAME = "Epsilon-1 Link Lock Demo"

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


def upload_requirement_attachment(headers: dict, project_id: str, requirement_id: str, filename: str, content: bytes) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/files",
        files={"file": (filename, content, "text/plain")}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload_action_attachment(headers: dict, project_id: str, action_id: str, filename: str, content: bytes) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/actions/{action_id}/files",
        files={"file": (filename, content, "application/pdf")}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def add_comment(headers: dict, project_id: str, requirement_id: str, body: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/comments",
        json={"body": body}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload_comment_attachment(headers: dict, project_id: str, requirement_id: str, comment_id: str, filename: str, content: bytes) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/comments/{comment_id}/files",
        files={"file": (filename, content, "text/plain")}, headers=headers, timeout=30,
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


# Stakeholders & Personas (docs/plans/module-02-stakeholders-and-personas-plan.md
# Phase 1.1). The module is default-off, so it is enabled for Gamma only —
# Alpha/Beta keep the nav and module list the existing specs were written
# against. Fixed names the persona specs may rely on; the persona Playwright
# spec itself builds its own disposable org rather than depending on these.
PERSONA_ORG_WEIGHTED_NAME = "E2E Field Inspector"
PERSONA_ORG_UNWEIGHTED_NAME = "E2E Compliance Auditor"
PERSONA_PROJECT_NAME = "E2E Hierarchy Operator"


def enable_module(headers: dict, org_id: str, module_key: str) -> None:
    r = httpx.put(f"{BASE}/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=headers, timeout=30)
    r.raise_for_status()


def create_persona(headers: dict, *, org_id: str | None = None, project_id: str | None = None, activate: bool = False, **fields) -> dict:
    """Creates an org- or project-scoped Persona (exactly one of `org_id`/`project_id`), optionally activating it."""
    base = f"{BASE}/orgs/{org_id}/modules/stakeholders" if org_id else f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.post(f"{base}/personas", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    persona = r.json()
    if activate:
        r = httpx.post(f"{base}/personas/{persona['id']}/activate", json={}, headers=headers, timeout=30)
        r.raise_for_status()
        persona = r.json()
    return persona


# Per-persona Pain Point scoring (docs/plans/module-01-context-and-strategy-plan.md Phase 11). Context &
# Strategy is default-off, so it is enabled for Gamma only. Fixed titles a spec may rely on; the scoring
# Playwright spec itself builds its own disposable org rather than depending on these.
PAIN_POINT_MULTI_PERSONA_NAME = "E2E Scored Across Personas"
PAIN_POINT_ALL_PERSONAS_NAME = "E2E Scored For All Personas"
PAIN_POINT_INTENTIONAL_NAME = "E2E Intentional Limitation"
PAIN_POINT_UNSCORED_NAME = "E2E Unscored Pain Point"


def create_pain_point(headers: dict, project_id: str, type_id: str, title: str, **fields) -> dict:
    """Creates a Pain Point in `project_id` (Submitted)."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points",
        json={"pain_point_type_id": type_id, "title": title, **fields}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_pain_point_scores(headers: dict, project_id: str, pain_point_id: str, scores: list[dict]) -> dict:
    """Replaces a Pain Point's scores; each entry's levels are given by name via `score_entry`."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/scores",
        json={"scores": scores}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def pain_point_levels(headers: dict, project_id: str) -> dict[str, dict[str, str]]:
    """The org's Pain Point scoring levels as `{axis_key: {level_name: level_id}}`."""
    r = httpx.get(f"{BASE}/projects/{project_id}/scoring-schemes/pain_point", headers=headers, timeout=30)
    r.raise_for_status()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in r.json()["axes"]}


def score_entry(levels: dict[str, dict[str, str]], target_id: str | None = None, **chosen: str) -> dict:
    """One score row from level names (`severity="Major"`, ...); `target_id=None` = all personas."""
    return {
        "target_id": target_id,
        **{f"{axis}_level_id": levels[axis][chosen[axis]] if axis in chosen else None
           for axis in ("severity", "frequency", "confidence")},
    }


def set_persona_weight_override(headers: dict, project_id: str, persona_id: str, weight: float) -> dict:
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/stakeholders/personas/{persona_id}/weight",
        json={"weight": weight}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# Stakeholders (Phase 1.2) — enabled with the rest of the module on Gamma only.
# Fixed names a spec may rely on; the stakeholder Playwright spec itself builds
# its own disposable org rather than depending on these.
STAKEHOLDER_ORG_NAME = "E2E Safety Regulator"
STAKEHOLDER_PROJECT_NAME = "E2E Plant Manager"
# Phase 3b — an org stakeholder hidden from Gamma-3 (and so from its child Gamma-4).
STAKEHOLDER_HIDDEN_NAME = "E2E Hidden Stakeholder"
PERSONA_HIDDEN_NAME = "E2E Hidden Persona"
# Stakeholder Needs (Phase 2) — one on the Gamma-3 hierarchy parent, held by the
# project stakeholder; the need Playwright spec builds its own disposable data.
NEED_PROJECT_NAME = "E2E Keep the line running"


def create_stakeholder(
    headers: dict, *, org_id: str | None = None, project_id: str | None = None, activate: bool = False,
    represents: tuple[str, ...] = (), **fields,
) -> dict:
    """Creates an org- or project-scoped Stakeholder (exactly one of `org_id`/`project_id`), optionally activating it
    and linking it to the given Persona ids."""
    base = f"{BASE}/orgs/{org_id}/modules/stakeholders" if org_id else f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.post(f"{base}/stakeholders", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    stakeholder = r.json()
    if activate:
        r = httpx.post(f"{base}/stakeholders/{stakeholder['id']}/activate", json={}, headers=headers, timeout=30)
        r.raise_for_status()
        stakeholder = r.json()
    for persona_id in represents:
        r = httpx.post(
            f"{base}/stakeholders/{stakeholder['id']}/personas", json={"persona_id": persona_id}, headers=headers, timeout=30,
        )
        r.raise_for_status()
    return stakeholder


def set_persona_visibility(headers: dict, project_id: str, persona_id: str, hidden: bool) -> dict:
    """Hides an org Persona from a project (`hidden=True`), or shows it again where a parent project hides it."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/stakeholders/personas/{persona_id}/visibility",
        json={"hidden": hidden}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_stakeholder_visibility(headers: dict, project_id: str, stakeholder_id: str, hidden: bool) -> dict:
    """Hides an org Stakeholder from a project (`hidden=True`), or shows it again where a parent project hides it."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/stakeholders/stakeholders/{stakeholder_id}/visibility",
        json={"hidden": hidden}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_need(
    headers: dict, project_id: str, *, activate: bool = False, holders: tuple[tuple[str, str], ...] = (),
    requirement_ids: tuple[str, ...] = (), **fields,
) -> dict:
    """Creates a project Stakeholder Need, optionally activating it, linking the given `(kind, id)` Stakeholder/Persona
    holders ("has need") and the given Requirement ids ("gives rise to")."""
    base = f"{BASE}/projects/{project_id}/modules/stakeholders/needs"
    r = httpx.post(base, json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    need = r.json()
    if activate:
        r = httpx.post(f"{base}/{need['id']}/activate", json={}, headers=headers, timeout=30)
        r.raise_for_status()
        need = r.json()
    for kind, holder_id in holders:
        r = httpx.post(f"{base}/{need['id']}/holders", json={"kind": kind, "id": holder_id}, headers=headers, timeout=30)
        r.raise_for_status()
    for requirement_id in requirement_ids:
        r = httpx.post(f"{base}/{need['id']}/requirements", json={"requirement_id": requirement_id}, headers=headers, timeout=30)
        r.raise_for_status()
    return need


def add_stakeholder_relationship(
    headers: dict, project_id: str, holder_kind: str, holder_id: str, kind: str, target_type: str, target_id: str,
) -> dict:
    """Adds a §10.5 relationship (Phase 3) from a Stakeholder/Persona (`holder_kind` `"stakeholder"`/`"persona"`) to a
    record of `project_id`."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/stakeholders/{holder_kind}s/{holder_id}/relationships",
        json={"kind": kind, "target_type": target_type, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_stakeholder_levels(headers: dict, org_id: str) -> dict[str, dict[str, str]]:
    """`{axis: {level name: level id}}` of the org's `stakeholder` scoring scheme."""
    r = httpx.get(f"{BASE}/orgs/{org_id}/scoring-schemes/stakeholder", headers=headers, timeout=30)
    r.raise_for_status()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in r.json()["axes"]}


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
    gamma1 = create_project(
        h_g, gamma["id"], "Gamma-1 Lab Instrument Suite", "E2E seed project.",
        # Eligible to be a parent (docs/decisions.md): project-hierarchy.spec.ts's
        # relaxed-creation-path test creates a sub-project of Gamma-1 live.
        can_be_parent=True,
    )
    gamma2 = create_project(h_g, gamma["id"], "Gamma-2 Data Pipeline", "E2E seed project.")

    print(f"Creating {GAMMA3_NAME!r} / {GAMMA4_NAME!r} (fixed project-hierarchy fixture for project-hierarchy.spec.ts)...")
    gamma3 = create_project(
        h_g, gamma["id"], GAMMA3_NAME, "E2E seed project — hierarchy parent fixture.", can_be_parent=True,
    )
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

    print(f"Creating {LINK_LOCK_PROJECT_NAME!r} (link-lock fixture for link-and-action-change-request-locking"
          ".spec.ts, Platform review 2026-09 Phase 8) — its own dedicated project, per this file's existing"
          " convention (PROJECT_NAMES.delta1/gamma3/gamma4) of a project no other spec may depend on rather than"
          " repurposing a shared one. Given components/categories only (no requirements of its own) — that spec"
          " creates, links, and approves its own throwaway requirements dynamically each run (the same fix"
          " `requirement-actions.spec.ts` already applied after discovering a *fixed* seeded link/action here"
          " would make the spec non-idempotent: unlinking/removing/approving is one-way, so a second run against"
          " the same database would find the seeded fixture already consumed).")
    epsilon1 = create_project(
        h_ab, alpha["id"], LINK_LOCK_PROJECT_NAME,
        "E2E seed project dedicated to the link-lock (require-change-request-for-links) Playwright coverage.",
    )
    r = httpx.patch(
        f"{BASE}/projects/{epsilon1['id']}", json={"require_change_request_for_approved_links": True},
        headers=h_ab, timeout=30,
    )
    r.raise_for_status()
    seed_project_content(h_ab, epsilon1, 0)

    print(f"Creating {FGAC_STANDARD_NAME!r} (compliance standard for Alpha, role-management.spec.ts's entity-picker fixture)...")
    fgac_standard = create_compliance_standard(h_ab, alpha["id"], reference=FGAC_STANDARD_REFERENCE, name=FGAC_STANDARD_NAME)

    print("Seeding Stakeholders & Personas on Gamma (module enabled for Gamma only): two org personas (one weighted,"
          " one not), a project persona on the Gamma-3 hierarchy parent, and a weight override there that"
          " Gamma-4 inherits...")
    enable_module(h_g, gamma["id"], "stakeholders")
    field_inspector = create_persona(
        h_g, org_id=gamma["id"], activate=True, name=PERSONA_ORG_WEIGHTED_NAME, role_title="Field inspector",
        goals="Finish each inspection in one visit.", needs="Offline access to instrument manuals.",
        behaviours="Works in short bursts between sites.", context_environment="Outdoors, gloves on.",
        skills_proficiency="Expert with the instruments, novice with software.", frequency_of_use="Daily",
        constraints="No reliable network.", weight=3.0,
    )
    create_persona(
        h_g, org_id=gamma["id"], name=PERSONA_ORG_UNWEIGHTED_NAME, role_title="Compliance auditor",
        goals="Verify evidence without chasing the team.",
    )
    line_operator = create_persona(
        h_g, project_id=gamma3["id"], activate=True, name=PERSONA_PROJECT_NAME, role_title="Line operator",
        goals="Keep the pipeline running.", weight=1.5,
    )
    set_persona_weight_override(h_g, gamma3["id"], field_inspector["id"], 5.0)
    hidden_persona = create_persona(
        h_g, org_id=gamma["id"], activate=True, name=PERSONA_HIDDEN_NAME, role_title="Out-of-scope archetype",
    )
    set_persona_visibility(h_g, gamma3["id"], hidden_persona["id"], True)

    print("Seeding per-persona Pain Point scoring on Gamma-3 (Context & Strategy enabled for Gamma only): one Pain"
          " Point scored across two weighted personas, one scored for all personas, one intentional, one unscored...")
    enable_module(h_g, gamma["id"], "context_strategy")
    pp_types = httpx.get(
        f"{BASE}/projects/{gamma3['id']}/modules/context_strategy/pain-point-types", headers=h_g, timeout=30,
    ).json()
    pp_type_id = next(t["id"] for t in pp_types if t["name"] == "Operator")
    pp_levels = pain_point_levels(h_g, gamma3["id"])
    multi = create_pain_point(
        h_g, gamma3["id"], pp_type_id, PAIN_POINT_MULTI_PERSONA_NAME, description="Hits personas differently.",
        priority="high", date_identified="2026-09-01",
    )
    set_pain_point_scores(h_g, gamma3["id"], multi["id"], [
        score_entry(pp_levels, field_inspector["id"], severity="Major", frequency="Constant", confidence="High"),
        score_entry(pp_levels, line_operator["id"], severity="Blocker", frequency="Rare", confidence="Medium"),
    ])
    everyone = create_pain_point(
        h_g, gamma3["id"], pp_type_id, PAIN_POINT_ALL_PERSONAS_NAME, priority="medium", date_identified="2026-09-02",
    )
    set_pain_point_scores(h_g, gamma3["id"], everyone["id"], [
        score_entry(pp_levels, None, severity="Moderate", frequency="Frequent", confidence="Medium"),
    ])
    intentional = create_pain_point(
        h_g, gamma3["id"], pp_type_id, PAIN_POINT_INTENTIONAL_NAME, priority="low", date_identified="2026-09-03",
        is_intentional=True,
    )
    set_pain_point_scores(h_g, gamma3["id"], intentional["id"], [
        score_entry(pp_levels, line_operator["id"], severity="Major", frequency="Constant", confidence="High"),
    ])
    create_pain_point(h_g, gamma3["id"], pp_type_id, PAIN_POINT_UNSCORED_NAME, priority="medium", date_identified="2026-09-04")

    print("Seeding Stakeholders on Gamma: an org Stakeholder (rated, with a cadence, representing the org Field"
          " Inspector persona) and a project Stakeholder on the Gamma-3 hierarchy parent...")
    levels = get_stakeholder_levels(h_g, gamma["id"])
    org_regulator = create_stakeholder(
        h_g, org_id=gamma["id"], activate=True, represents=(field_inspector["id"],), name=STAKEHOLDER_ORG_NAME,
        role="Safety regulator", organisation_group="National Safety Board", interests="Compliance evidence.",
        contact_info="regulator@e2e.example.com", target_cadence="quarterly",
        influence_level_id=levels["influence"]["High"], interest_level_id=levels["interest"]["Medium"],
    )
    hidden_stakeholder = create_stakeholder(
        h_g, org_id=gamma["id"], activate=True, name=STAKEHOLDER_HIDDEN_NAME, role="Out-of-scope supplier contact",
    )
    set_stakeholder_visibility(h_g, gamma3["id"], hidden_stakeholder["id"], True)
    plant_manager = create_stakeholder(
        h_g, project_id=gamma3["id"], activate=True, name=STAKEHOLDER_PROJECT_NAME, role="Plant manager",
        goals_needs="Keep the line running.", target_cadence="monthly",
        influence_level_id=levels["influence"]["Medium"], interest_level_id=levels["interest"]["High"],
    )

    print("Seeding a Stakeholder Need on Gamma-3, held by the project Stakeholder and the org Field Inspector persona...")
    create_need(
        h_g, gamma3["id"], activate=True, holders=(("stakeholder", plant_manager["id"]), ("persona", field_inspector["id"])),
        name=NEED_PROJECT_NAME, description="Unplanned stoppages must be diagnosed within minutes.",
        rationale="Each stoppage costs an hour of line output.",
    )

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
    print("Seeding Stakeholder/Persona relationships on Gamma-1 (Phase 3): the org regulator reviews, and the org Field"
          " Inspector persona is affected by, its first requirement...")
    add_stakeholder_relationship(
        h_g, gamma1["id"], "stakeholder", org_regulator["id"], "reviews", "requirement", gamma1_reqs[0]["id"],
    )
    add_stakeholder_relationship(
        h_g, gamma1["id"], "persona", field_inspector["id"], "affected_by_requirement", "requirement", gamma1_reqs[0]["id"],
    )
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

    print("Seeding files on Alpha-1 across all three project-files origins (project-files.spec.ts)...")
    upload_requirement_attachment(
        h_ab, alpha1["id"], alpha1_reqs[4]["id"], "e2e-direct-attachment.txt", b"E2E direct requirement attachment.",
    )
    upload_action_attachment(
        h_ab, alpha1["id"], e2e_review_action["id"], "e2e-action-attachment.pdf", b"%PDF-fake E2E action attachment.",
    )
    files_comment = add_comment(h_ab, alpha1["id"], alpha1_reqs[5]["id"], "E2E: comment with an attachment.")
    upload_comment_attachment(
        h_ab, alpha1["id"], alpha1_reqs[5]["id"], files_comment["id"], "e2e-comment-attachment.txt", b"E2E comment attachment.",
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
    print(f"Files on Alpha-1 ({alpha1['id']}): direct attachment on {alpha1_reqs[4]['unique_code']}, action attachment on "
          f"'E2E Review Action', comment attachment on {alpha1_reqs[5]['unique_code']} — one of each project-files origin.")
    print(f"Compliance standard {FGAC_STANDARD_NAME!r} (id {fgac_standard['id']}) on Alpha — Role Management page's"
          " entity-scope picker fixture.")
    print(f"Personas on Gamma (Stakeholders & Personas enabled for Gamma only): org personas {PERSONA_ORG_WEIGHTED_NAME!r}"
          f" (Active, weight 3) and {PERSONA_ORG_UNWEIGHTED_NAME!r} (Draft, unweighted); project persona"
          f" {PERSONA_PROJECT_NAME!r} on {GAMMA3_NAME!r}; Gamma-3's weight override of 5 on {PERSONA_ORG_WEIGHTED_NAME!r}"
          f" is inherited by {GAMMA4_NAME!r}; org {PERSONA_HIDDEN_NAME!r} is hidden from {GAMMA3_NAME!r} (and so {GAMMA4_NAME!r}).")
    print(f"Pain Points on {GAMMA3_NAME!r} (Context & Strategy enabled for Gamma only): {PAIN_POINT_MULTI_PERSONA_NAME!r}"
          f" (scored by {PERSONA_ORG_WEIGHTED_NAME!r} and {PERSONA_PROJECT_NAME!r}, a Blocker for the latter),"
          f" {PAIN_POINT_ALL_PERSONAS_NAME!r} (all personas), {PAIN_POINT_INTENTIONAL_NAME!r} (intentional) and"
          f" {PAIN_POINT_UNSCORED_NAME!r} (unscored).")
    print(f"Stakeholders on Gamma: org {STAKEHOLDER_ORG_NAME!r} (Active, High/Medium, quarterly, represents"
          f" {PERSONA_ORG_WEIGHTED_NAME!r}) and project {STAKEHOLDER_PROJECT_NAME!r} on {GAMMA3_NAME!r} (Active, monthly);"
          f" org {STAKEHOLDER_HIDDEN_NAME!r} is hidden from {GAMMA3_NAME!r} (and so {GAMMA4_NAME!r}).")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Seed failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
