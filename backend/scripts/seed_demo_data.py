"""
Module: scripts.seed_demo_data

Seeds a realistic, presentable demo dataset — a fictional engineering
company ("Solstice Robotics") with three working projects (one a sub-project of
another, demonstrating hierarchical projects), two template projects and one
project created from a template, requirements at varied
lifecycle stages, an in-review and an approved change request, discussion
comments, custom fields, and a report look. Intended for
screenshots, demos, and (eventually) a public demo instance.

Design notes:
- Every object is created through the real HTTP API (not direct DB writes),
  same convention as scripts/seed_e2e_dataset.py, so this exercises the same
  code paths a real user would.
- Deliberately separate from seed_e2e_dataset.py: that dataset's org/persona
  names and content exist to give the Playwright suite fixed, predictable
  anchors (docs/e2e-workflows.md), not to look good in a screenshot. This
  one exists purely to look like a real, in-use product.
- Idempotent by skipping, same as the E2E seed: if "Solstice Robotics" already exists, exits without changes
  rather than creating a duplicate. It does not reset anything itself; `demo_setup.py` (run through
  `scripts/demo.sh`) removes the demonstration organisation through the organisation deletion route and seeds
  again, with the guards and the daily schedule described in docs/development.md.

Run via (from tests/container):
    docker compose exec backend python scripts/seed_demo_data.py

Login afterward as demo.admin@example.com / DemoDemo123! (org admin, project
manager on both projects) — see the printed summary at the end for every
persona and their role.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

BASE = os.environ.get("DEMO_API_BASE", "http://localhost:8000/api/v1")
ADMIN_EMAIL = os.environ.get("DEMO_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD") or os.environ.get("SERVER_ADMIN_PASSWORD", "ChangeMe123!")
# Shared by every demonstration account; `demo_setup.py` replaces it when it rotates the password.
PASSWORD = os.environ.get("DEMO_PASSWORD", "DemoDemo123!")

ORG_NAME = "Solstice Robotics"


def login(email: str, password: str) -> str:
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_org(headers: dict, name: str) -> dict:
    r = httpx.post(f"{BASE}/orgs", json={"name": name}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_org_user(headers: dict, org_id: str, email: str, display_name: str, role: str) -> dict:
    """Creates a demonstration account in the organisation, or re-joins one that outlived a reset.

    An organisation's removal never deletes accounts, so a second seed finds the account already there; it is
    then given its role in the new organisation instead.

    Args:
        headers: Server administrator headers.
        org_id: The organisation.
        email: Sign-in name.
        display_name: Shown name.
        role: Organisation role.

    Returns:
        The user, with at least `user_id`.

    Raises:
        httpx.HTTPStatusError: On any failure other than "email already in use".
    """
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/users",
        json={"email": email, "display_name": display_name, "password": PASSWORD, "role": role},
        headers=headers, timeout=30,
    )
    if r.status_code == httpx.codes.CONFLICT:
        found = httpx.get(f"{BASE}/system/users", params={"search": email}, headers=headers, timeout=30)
        found.raise_for_status()
        user = next(u for u in found.json() if u["email"].lower() == email.lower())
        joined = httpx.post(
            f"{BASE}/orgs/{org_id}/users/{user['user_id']}/roles",
            json={"user_id": user["user_id"], "role": role}, headers=headers, timeout=30,
        )
        joined.raise_for_status()
        return {"user_id": user["user_id"], "email": email, "display_name": user["display_name"], "roles": [role]}
    r.raise_for_status()
    return r.json()


def create_project(
    headers: dict, org_id: str, name: str, summary: str,
    *, parent_project_id: str | None = None, role_inheritance_mode: str | None = None, can_be_parent: bool = False,
    report_name: str | None = None, template_project_id: str | None = None, is_template: bool = False,
) -> dict:
    payload: dict = {"organization_id": org_id, "name": name, "summary": summary}
    if template_project_id is not None:
        payload["template_project_id"] = template_project_id
    if is_template:
        payload["is_template"] = True
    if report_name is not None:
        payload["report_name"] = report_name
    if parent_project_id is not None:
        payload["parent_project_id"] = parent_project_id
    if role_inheritance_mode is not None:
        payload["role_inheritance_mode"] = role_inheritance_mode
    if can_be_parent:
        payload["can_be_parent"] = True
    r = httpx.post(f"{BASE}/projects", json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def add_member_source(
    headers: dict, project_id: str, source_project_id: str,
    mirror_mode: str | None = None, mirror_filter_role: str | None = None,
) -> None:
    """See seed_e2e_dataset.py's identical helper — adds `source_project_id`
    to `project_id`'s member-source list. Generalized (docs/decisions.md):
    `source_project_id` no longer needs to be a direct child, just any
    project in the same organisation; `mirror_mode`/`mirror_filter_role`
    default to the original member_only/None behavior when omitted."""
    payload: dict = {"source_project_id": source_project_id}
    if mirror_mode is not None:
        payload["mirror_mode"] = mirror_mode
    if mirror_filter_role is not None:
        payload["mirror_filter_role"] = mirror_filter_role
    r = httpx.post(f"{BASE}/projects/{project_id}/member-sources", json=payload, headers=headers, timeout=30)
    r.raise_for_status()


def create_project_group(headers: dict, project_id: str, name: str, role: str) -> dict:
    """Creates a project group explicitly, then grants it `role`. Projects
    no longer auto-create any groups on creation (2026-08-31 removed the four "standard" default groups — see
    docs/decisions.md), so any group this script wants to demonstrate (e.g.
    a cross-project source reference below) has to be created as its own
    explicit step now, rather than reached by name via a pre-existing
    default.

    A group is created bare, with zero roles, and a role is a separate
    grant since the members/groups directory rework (docs/
    decisions.md) — mirroring how `create_org_group` already creates an org
    group bare. This helper still takes a single `role` (every group this
    demo dataset seeds only ever needs one) and grants it via the new
    per-group-role endpoint right after creation."""
    r = httpx.post(f"{BASE}/projects/{project_id}/groups", json={"name": name}, headers=headers, timeout=30)
    r.raise_for_status()
    group = r.json()
    r = httpx.post(
        f"{BASE}/projects/{project_id}/groups/{group['id']}/roles", json={"role": role}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    group["roles"] = [role]
    return group


def add_project_group_source_reference(headers: dict, project_id: str, group_id: str, source_project_id: str) -> None:
    """Adds "this group's members = source_project_id's own direct members"
    to a project group — the second, structurally simpler cross-project
    RBAC mechanism alongside `add_member_source` above (docs/decisions.md)."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/groups/{group_id}/members", json={"source_project_id": source_project_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def assign_project_role(headers: dict, project_id: str, user_id: str, role: str) -> None:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


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


# Shared category name/prefix vocabulary — reused across components within
# a project (component/category tree, C-G-07: prefix uniqueness is now
# per-component, so e.g. "Performance"/"PERF" can exist under more than one
# component in the same project).
CATEGORY_DEFS: dict[str, tuple[str, str]] = {
    "FN": ("Functional", "FN"),
    "PERF": ("Performance", "PERF"),
    "SAF": ("Safety", "SAF"),
    "REG": ("Regulatory", "REG"),
    "SEC": ("Security", "SEC"),
    "REL": ("Reliability", "REL"),
}


def create_categories_for_components(
    headers: dict, project_id: str, components: dict[str, dict], component_categories: dict[str, list[str]]
) -> dict[str, dict[str, dict]]:
    """Creates each component's own categories (tree, not a project-wide
    flat list) — `component_categories` maps a component key to the list of
    `CATEGORY_DEFS` keys that component actually uses."""
    return {
        comp_key: {
            cat_key: create_category(headers, project_id, components[comp_key]["id"], *CATEGORY_DEFS[cat_key])
            for cat_key in cat_keys
        }
        for comp_key, cat_keys in component_categories.items()
    }


def create_stage(headers: dict, project_id: str, name: str, workflow_id: str | None = None) -> dict:
    body = {"name": name, **({"workflow_id": workflow_id} if workflow_id else {})}
    r = httpx.post(f"{BASE}/projects/{project_id}/stages", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_org_workflow(headers: dict, org_id: str, name: str, phases: list[tuple[str, str]]) -> dict:
    """Creates an organisation stage workflow from `(phase name, kind)` pairs, in order."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/stage-workflows",
        json={"name": name, "phases": [{"name": phase, "kind": kind} for phase, kind in phases]},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def transition_stage(headers: dict, project_id: str, stage_id: str, phase_name: str) -> None:
    """Moves a stage to the phase called `phase_name` (case-insensitive) in its own workflow."""
    stage = next(
        st for st in httpx.get(f"{BASE}/projects/{project_id}/stages", headers=headers, timeout=30).json() if st["id"] == stage_id
    )
    workflow = next(
        w for w in httpx.get(f"{BASE}/projects/{project_id}/stage-workflows", headers=headers, timeout=30).json()
        if w["id"] == stage["workflow_id"]
    )
    phase = next(p for p in workflow["phases"] if p["name"].lower() == phase_name.lower())
    r = httpx.post(
        f"{BASE}/projects/{project_id}/stages/{stage_id}/transition",
        json={"phase_id": phase["id"], "cascade_to_requirements": False}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def enable_component_phases(headers: dict, project_id: str) -> None:
    """Turns component phases on, so each component follows its own workflow per stage."""
    r = httpx.put(f"{BASE}/projects/{project_id}/component-phases-settings", json={"mode": "on"}, headers=headers, timeout=30)
    r.raise_for_status()


def move_component_track(headers: dict, project_id: str, component_id: str, stage_id: str, phase_name: str) -> None:
    """Moves one component's track in a stage to the phase called `phase_name` in the track's own workflow."""
    tracks = httpx.get(f"{BASE}/projects/{project_id}/component-stages", headers=headers, timeout=30).json()["tracks"]
    track = next(t for t in tracks if t["component_id"] == component_id and t["stage_id"] == stage_id)
    workflow = next(
        w for w in httpx.get(f"{BASE}/projects/{project_id}/stage-workflows", headers=headers, timeout=30).json()
        if w["id"] == track["workflow_id"]
    )
    phase = next(p for p in workflow["phases"] if p["name"].lower() == phase_name.lower())
    r = httpx.post(
        f"{BASE}/projects/{project_id}/components/{component_id}/stages/{stage_id}/transition",
        json={"phase_id": phase["id"], "cascade_to_requirements": False}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def schedule_phase(
    headers: dict, project_id: str, stage_id: str, phase_name: str, start: date | None, end: date | None,
    component_id: str | None = None,
) -> None:
    """Sets the expected range of the phase called `phase_name` in the workflow that applies to the stage,
    or to the component's track within it."""
    stage = next(
        st for st in httpx.get(f"{BASE}/projects/{project_id}/stages", headers=headers, timeout=30).json() if st["id"] == stage_id
    )
    workflow_id = stage["workflow_id"]
    if component_id is not None:
        tracks = httpx.get(f"{BASE}/projects/{project_id}/component-stages", headers=headers, timeout=30).json()["tracks"]
        workflow_id = next(t for t in tracks if t["component_id"] == component_id and t["stage_id"] == stage_id)["workflow_id"]
    workflow = next(
        w for w in httpx.get(f"{BASE}/projects/{project_id}/stage-workflows", headers=headers, timeout=30).json() if w["id"] == workflow_id
    )
    phase = next(p for p in workflow["phases"] if p["name"].lower() == phase_name.lower())
    r = httpx.put(
        f"{BASE}/projects/{project_id}/stages/{stage_id}/phase-plan",
        json={
            "phase_id": phase["id"], "component_id": component_id,
            "expected_from": start.isoformat() if start else None, "expected_to": end.isoformat() if end else None,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def mark_component_track_not_applicable(headers: dict, project_id: str, component_id: str, stage_id: str) -> None:
    """Marks a stage as not applicable to one component."""
    r = httpx.patch(
        f"{BASE}/projects/{project_id}/components/{component_id}/stages/{stage_id}/track",
        json={"not_applicable": True}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def create_custom_field(headers: dict, project_id: str, entity_kind: str, name: str, field_type: str, options: list | None = None) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/custom-fields",
        json={"entity_kind": entity_kind, "name": name, "field_type": field_type, "options": options},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_requirement(
    headers: dict, project_id: str, *, name: str, reasoning: str, component_id: str, category_id: str,
    description: str = "", custom_fields: dict | None = None,
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements",
        json={
            "name": name, "reasoning": reasoning, "description": description, "component_id": component_id, "category_id": category_id,
            "keywords": [], "custom_fields": custom_fields or {},
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_requirement_status(
    headers: dict, project_id: str, requirement: dict, status_value: str,
    *, review_date: str | None = None, reviewer_id: str | None = None,
    owner: dict | None = None, reviewer: dict | None = None,
) -> dict:
    """Direct edit setting `status` (and optionally a review schedule) on a
    still-unlocked requirement — mirrors what a PM moving a requirement
    through draft -> reviewed -> approved would actually click through.
    `owner` / `reviewer` are `{"type": "user" | "org_group" | "project_group", "id": ...}`; `reviewer_id` is the
    shorthand for a user reviewer. The owner is carried over from the requirement when omitted."""
    body = {
        "name": requirement["name"], "reasoning": requirement["reasoning"], "description": requirement.get("description", ""),
        "clarification": requirement.get("clarification", ""),
        "component_id": requirement["component_id"], "category_id": requirement["category_id"],
        "owner": owner or requirement.get("owner") or {"type": "user", "id": requirement["creator_id"]},
        "status": status_value,
        "custom_fields": requirement.get("custom_fields", {}),
        "change_note": f"Marked {status_value} during scoping.",
    }
    if review_date is not None:
        body["review_date"] = review_date
    if reviewer_id is not None:
        body["reviewer"] = {"type": "user", "id": reviewer_id}
    if reviewer is not None:
        body["reviewer"] = reviewer
    r = httpx.put(f"{BASE}/projects/{project_id}/requirements/{requirement['id']}", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_tag(headers: dict, project_id: str, name: str, colour: str | None = None) -> dict:
    """Adds a tag to a project's own vocabulary."""
    r = httpx.post(f"{BASE}/projects/{project_id}/tags", json={"name": name, "colour": colour}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def tag_record(headers: dict, project_id: str, artefact_type: str, artefact_id: str, names: list[str]) -> dict:
    """Makes a record carry exactly `names` (any registered artefact type; new names are created in a free project)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/tags", json={"tags": names},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def place_record(
    headers: dict, project_id: str, artefact_type: str, artefact_id: str, places: list[tuple[dict, dict | None]],
) -> dict:
    """Places a record (any type but a requirement, which has its own component) in `(component, category)` pairs."""
    body = {"placements": [
        {"component_id": component["id"], "category_id": category["id"] if category else None} for component, category in places
    ]}
    r = httpx.put(
        f"{BASE}/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/placements", json=body, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def complete_requirement(headers: dict, project_id: str, requirement_id: str) -> dict:
    """Marks an already-approved requirement completed (C-G-11 overlay
    marker) — returns the updated requirement so callers can refresh their
    local copy's `is_completed`/`completed_at`/`completed_by` rather than
    hand-patching a stale `status` field, now that completing no longer
    changes `status` at all."""
    r = httpx.post(f"{BASE}/projects/{project_id}/requirements/{requirement_id}/complete", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def archive_requirement(headers: dict, project_id: str, requirement_id: str) -> None:
    """Archives a requirement (soft-delete, C-A-06). Left archived rather
    than restored in the demo dataset so a reviewer has a concrete example
    to click "Restore" on — see `POST .../unarchive`, added because archive was one-way for requirements, unlike
    projects."""
    r = httpx.delete(f"{BASE}/projects/{project_id}/requirements/{requirement_id}", headers=headers, timeout=30)
    r.raise_for_status()


def add_requirement_comment(headers: dict, project_id: str, requirement_id: str, body: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/requirements/{requirement_id}/comments", json={"body": body}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def upload_requirement_attachment(
    headers: dict, project_id: str, requirement_id: str, filename: str, content: bytes,
    content_type: str = "text/plain",
) -> dict:
    """Direct requirement attachment (C-M-02) — one of the three sources
    `GET /projects/{id}/files` (ProjectFilesPage) combines into a
    project-wide file list."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/files",
        files={"file": (filename, content, content_type)}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload_action_attachment(
    headers: dict, project_id: str, action_id: str, filename: str, content: bytes,
    content_type: str = "application/pdf",
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/actions/{action_id}/files",
        files={"file": (filename, content, content_type)}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload_comment_attachment(
    headers: dict, project_id: str, requirement_id: str, comment_id: str, filename: str,
    content: bytes, content_type: str = "text/plain",
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/comments/{comment_id}/files",
        files={"file": (filename, content, content_type)}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


#: Small bundled pictures the demo attaches to records (illustrations drawn for the demo, not photographs of real equipment).
DATA_DIR = Path(__file__).parent / "data"
TRIAL_SITE_PICTURE = (DATA_DIR / "test-site.png", "bvlos-trial-site.png", "image/png")
BENCH_RIG_PICTURE = (DATA_DIR / "gust-rig.jpg", "bench-test-rig.jpg", "image/jpeg")
ARCHITECTURE_DIAGRAM = (DATA_DIR / "flight-controller-architecture.svg", "flight-controller-architecture.svg", "image/svg+xml")


def attach_picture(headers: dict, project_id: str, record_path: str, picture: tuple[Path, str, str]) -> dict:
    """Attaches one of the bundled pictures to a record. `record_path` is the record's own route below `/projects/{id}`
    (`modules/context_strategy/pain-points/{record id}`); the record must still accept attachments (a Pain Point at a
    terminal outcome, or an approved requirement, does not)."""
    source, filename, content_type = picture
    r = httpx.post(
        f"{BASE}/projects/{project_id}/{record_path}/files", files={"file": (filename, source.read_bytes(), content_type)},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_change_request(
    headers: dict, project_id: str, *, kind: str, requirement_id: str | None, proposed_name: str,
    proposed_reasoning: str, reason: str, component_id: str | None = None, category_id: str | None = None,
    proposed_links: list[dict] | None = None,
) -> dict:
    """Creates a change request. `proposed_links` are links to create on approval, each
    `{"link_type_id", "direction", "other_type", "other_id"}` read from the requirement's side."""
    body = {
        "kind": kind, "requirement_id": requirement_id, "proposed_name": proposed_name,
        "proposed_reasoning": proposed_reasoning, "reason": reason,
    }
    if proposed_links:
        body["proposed_links"] = proposed_links
    if kind == "modify_requirement":
        # changed_fields is the explicit record of what a MODIFY_REQUIREMENT
        # change request actually proposes to change (see
        # docs/decisions.md's "Change request field-level tracking" entry) —
        # ignored entirely for NEW_REQUIREMENT, which has no existing
        # version to diff against.
        body["changed_fields"] = ["name", "reasoning"]
    if component_id:
        body["proposed_component_id"] = component_id
    if category_id:
        body["proposed_category_id"] = category_id
    r = httpx.post(f"{BASE}/projects/{project_id}/change-requests", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_add_action_change_request(
    headers: dict, project_id: str, requirement_id: str, *,
    action_title: str, action_description: str, action_type_id: str, reason: str, assignee: dict | None = None,
) -> dict:
    """An ADD_ACTION change request —
    only valid once `requirement_id` is already locked (status APPROVED,
    completed or not — C-G-11 completion no longer changes `status`); see
    `create_change_request`'s sibling helpers, which each already require
    the same, for a requirement to target with this."""
    body = {
        "kind": "add_action", "requirement_id": requirement_id, "reason": reason,
        "proposed_action_title": action_title, "proposed_action_description": action_description,
        "proposed_action_type_id": action_type_id, "proposed_action_assignee": assignee,
    }
    r = httpx.post(f"{BASE}/projects/{project_id}/change-requests", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def submit_change_request(headers: dict, project_id: str, cr_id: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/change-requests/{cr_id}/submit", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def decide_change_request(headers: dict, project_id: str, cr_id: str, approve: bool, note: str = "") -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/change-requests/{cr_id}/decide",
        json={"approve": approve, "note": note}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def add_cr_comment(headers: dict, project_id: str, cr_id: str, body: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/change-requests/{cr_id}/comments", json={"body": body}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def cast_vote(headers: dict, project_id: str, cr_id: str, vote: str, comment: str = "") -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/change-requests/{cr_id}/votes",
        json={"vote": vote, "comment": comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_cr_task(headers: dict, project_id: str, cr_id: str, description: str, assignee: dict | None = None, due_date: str | None = None) -> dict:
    """Adds a task to a change request; `assignee` is `{"type": "user" | "org_group" | "project_group", "id": ...}`."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/change-requests/{cr_id}/tasks",
        json={"description": description, "assignee": assignee, "due_date": due_date},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_project_status(headers: dict, project_id: str, status_id: str) -> dict:
    r = httpx.patch(f"{BASE}/projects/{project_id}", json={"status_id": status_id}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def set_project_terminology(headers: dict, project_id: str, terminology: dict[str, str]) -> dict:
    """Sets a project's per-project terminology overrides (C-C-03) via
    Project Admin's Terminology tab endpoint — demonstrates the feature in
    the manual-demo dataset the same way every other admin-settable field
    here does, rather than leaving every seeded project on the English
    defaults that would otherwise hide it entirely."""
    r = httpx.put(f"{BASE}/projects/{project_id}/terminology", json={"terminology": terminology}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def set_project_nav_labels(headers: dict, project_id: str, names: dict[str, str]) -> dict:
    """Sets a project's own navigation names (Project Admin's Navigation names panel), keyed by stable navigation
    key, so the manual-demo dataset shows a renamed entry in the navigation, page title and back link."""
    r = httpx.put(f"{BASE}/projects/{project_id}/nav-labels", json={"names": names}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def add_overview_widgets(headers: dict, project_id: str, widgets: list[dict]) -> dict:
    """Puts widgets ahead of the built-in overview layout (Customise overview), so the manual-demo dataset shows a
    configured gauge and a filtered record count beside the standard tiles and charts."""
    layout = httpx.get(f"{BASE}/projects/{project_id}/overview-layout", headers=headers, timeout=30)
    layout.raise_for_status()
    r = httpx.put(
        f"{BASE}/projects/{project_id}/overview-layout",
        json={"scope": layout.json()["scope"], "widgets": [*widgets, *layout.json()["widgets"]]}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_announcement(
    headers: dict, org_id: str, *, title: str, body: str, severity: str = "information", show_on_login: bool = False,
) -> dict:
    """Creates an organisation message (Organisation Admin's Messages group), so the manual-demo dataset shows the
    banner every member sees after signing in. Plain text only, with no web address."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/announcements",
        json={"title": title, "body": body, "severity": severity, "show_on_login": show_on_login},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def publish_org_policy(headers: dict, org_id: str, title: str, paragraphs: list[str]) -> None:
    """Writes and publishes an organisation policy (Organisation Admin's Policies group), so the manual-demo dataset shows
    the organisation's section on the Policies page to every member. No audience: every member reads it."""
    body = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs
    ]}
    created = httpx.post(f"{BASE}/orgs/{org_id}/policies", json={"title": title, "body": body}, headers=headers, timeout=30)
    created.raise_for_status()
    httpx.post(
        f"{BASE}/orgs/{org_id}/policies/{created.json()['id']}/publish", json={"change_note": "Demonstration text"}, headers=headers,
        timeout=30,
    ).raise_for_status()


def publish_server_policy(headers: dict, key: str, heading: str, paragraphs: list[str]) -> None:
    """Writes and publishes a built-in server policy (Server Management's Policies group), so the manual-demo dataset
    shows the Policies page and the login-page link. A policy that already exists is left as it is."""
    body = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": heading}]},
        *({"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs),
    ]}
    created = httpx.post(f"{BASE}/system/policies", json={"key": key, "body": body}, headers=headers, timeout=30)
    if created.status_code == 409:
        return
    created.raise_for_status()
    httpx.post(
        f"{BASE}/system/policies/{created.json()['id']}/publish", json={"change_note": "Demonstration text"}, headers=headers, timeout=30,
    ).raise_for_status()


def create_org_dashboard(
    headers: dict, org_id: str, name: str, widgets: list[dict], viewer_user_ids: list[str] | None = None,
) -> dict:
    """Adds an organisation dashboard page with the given widgets, optionally limited to some users (an organisation
    administrator always sees every page), so the manual-demo dataset shows a second page and a restricted one."""
    created = httpx.post(f"{BASE}/orgs/{org_id}/dashboards", json={"name": name}, headers=headers, timeout=30)
    created.raise_for_status()
    page_id = created.json()["dashboard"]["id"]
    saved = httpx.put(
        f"{BASE}/orgs/{org_id}/dashboards/{page_id}/layout", json={"scope": "this", "widgets": widgets}, headers=headers, timeout=30,
    )
    saved.raise_for_status()
    if viewer_user_ids:
        limited = httpx.put(
            f"{BASE}/orgs/{org_id}/dashboards/{page_id}",
            json={"viewers": [{"type": "user", "id": user_id} for user_id in viewer_user_ids]}, headers=headers, timeout=30,
        )
        limited.raise_for_status()
    return saved.json()


def create_link_type(
    headers: dict, org_id: str, *, forward_name: str, reverse_name: str, flow: str = "none",
    allowed_source_types: list[str] | None = None, allowed_target_types: list[str] | None = None,
) -> dict:
    """`flow` says where the link's target sits in a traceability chain: "forward_is_upstream",
    "forward_is_downstream" or "none" (see `models.enums.LinkFlow`). `allowed_source_types` /
    `allowed_target_types` restrict which artefact types the link may run from / to (`None` = any)."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/link-types",
        json={
            "forward_name": forward_name, "reverse_name": reverse_name, "flow": flow,
            "allowed_source_types": allowed_source_types, "allowed_target_types": allowed_target_types,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_artefact_link(
    headers: dict, project_id: str, artefact_type: str, artefact_id: str, *, link_type_id: str, other_type: str,
    other_id: str, direction: str = "outgoing", other_project_id: str | None = None,
) -> dict:
    """Links any two artefacts through the generic endpoint, read from `artefact_id`'s side
    (`direction` "outgoing" = it is the link's source). `other_project_id` is the other record's project when it
    is a parent or child of `project_id` (a cross-level link)."""
    body = {"link_type_id": link_type_id, "direction": direction, "other_type": other_type, "other_id": other_id}
    if other_project_id is not None:
        body["other_project_id"] = other_project_id
    r = httpx.post(
        f"{BASE}/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/links", json=body, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


REQUIREMENTS_BY_COMPONENT_AND_CATEGORY_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {
            "type": "group", "source": {"record_type": "requirement"}, "by": "component", "as": "comp",
            "children": [
                {
                    "type": "group", "source": {"group": "comp"}, "by": "category", "as": "cat",
                    "children": [
                        {"type": "heading", "level": 2, "text": "{{comp.value}} - {{cat.value}} ({{cat.count}})"},
                        {
                            "type": "table", "source": {"group": "cat", "sort": [{"field": "title"}]},
                            "columns": [{"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"}],
                        },
                    ],
                },
            ],
        },
    ],
}
"""Nested groups: a heading above each category's table that names both groups (`{{comp.value}} - {{cat.value}}`)."""


REQUIREMENTS_BY_COMPONENT_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {"type": "text", "text": "Requirements of **{{project_name}}** by component, generated {{generated_on}}."},
        {
            "type": "group", "source": {"record_type": "requirement"}, "by": "component", "as": "comp",
            "children": [
                {"type": "heading", "level": 2, "text": "{{comp.value}} ({{comp.count}})"},
                {
                    "type": "table", "source": {"group": "comp", "sort": [{"field": "title"}]},
                    "columns": [{"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"}],
                    "empty_text": "No requirements.",
                },
            ],
        },
    ],
}
"""A small custom report layout: the project's requirements grouped by component."""


REQUIREMENTS_HANDBOOK_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "header": {"left": "{{organisation}}", "right": "{{generated_on}}"},
    "footer": {"left": "{{report_title}}", "right": "Page {{page}} of {{pages}}"},
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {"type": "text", "text": "Requirements of **{{project_name}}** by component, generated {{generated_on}}."},
        {"type": "contents", "title": "Contents", "levels": 2, "new_page": True},
        {
            "type": "group", "source": {"record_type": "requirement"}, "by": "component", "as": "comp",
            "children": [
                {"type": "heading", "level": 2, "text": "{{comp.value}} ({{comp.count}})"},
                {
                    "type": "table", "source": {"group": "comp", "sort": [{"field": "title"}]},
                    "columns": [{"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"}],
                    "empty_text": "No requirements.",
                },
            ],
        },
    ],
}
"""A custom report layout with a table of contents (headings to level 2, on a page of its own) and a footer, which sits at the
foot of the page by default."""


REQUIREMENTS_BY_CATEGORY_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "variables": [
        {
            "name": "categories", "type": "enum", "multiple": True, "label": "Categories",
            "source": {"record_type": "requirement", "field": "category"},
        },
    ],
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {"type": "text", "text": "Requirements of **{{project_name}}** in the chosen categories: {{var.categories}}."},
        {
            "type": "table",
            "source": {
                "record_type": "requirement", "sort": [{"field": "title"}],
                "where": [{"field": "category", "op": "in", "value": {"var": "categories"}}],
            },
            "columns": [{"field": "code", "label": "Code"}, {"field": "category", "label": "Category"}, {"field": "title", "label": "Requirement"}],
            "empty_text": "No requirements in these categories.",
        },
    ],
}
"""A custom report layout with a run-time variable: the person chooses which categories to show when running it."""


CONTEXT_OVERVIEW_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "landscape",
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {"type": "text", "text": "Context & Strategy for **{{project_name}}**, built from report widgets."},
        {"type": "heading", "level": 2, "text": "Headline figures"},
        {"type": "widget", "key": "context_strategy.summary.figures", "params": {"stale_months": 12}},
        {"type": "heading", "level": 2, "text": "Pain Points by type and status"},
        {"type": "text", "text": "Open and closed Pain Points, as counted by the Pain Point coverage report."},
        {"type": "widget", "key": "context_strategy.pain-point-coverage.matrix", "empty_text": "No Pain Points yet."},
    ],
}
"""A custom report layout that embeds Context & Strategy report tables as widgets; its headings and prose are its own."""


DESIGN_FORMULAE_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {"type": "text", "text": "Design formulae for **{{project_name}}**. The stress \\(\\sigma = F / A\\) must stay below the yield strength."},
        {"type": "equation", "tex": "\\sigma = \\frac{F}{A}"},
        {"type": "text", "text": "Fatigue life follows $$N = \\left(\\frac{S_f}{\\sigma_a}\\right)^{1/b}$$"},
        {"type": "equation", "tex": "\\sum_{i=1}^{n} w_i x_i \\leq \\sqrt{\\frac{m}{k}}"},
    ],
}
"""A custom report layout with an equation block and equations written inside text, as the designer's Equation shortcut and text view produce."""


PAIN_POINTS_WITH_PICTURES_LAYOUT = {
    "schema_version": 1, "family": "document", "orientation": "portrait",
    "nodes": [
        {"type": "heading", "text": "{{report_title}}"},
        {
            "type": "table", "source": {"record_type": "pain_point", "sort": [{"field": "title"}]},
            "columns": [{"field": "code"}, {"field": "title"}, {"images": {"types": ["png", "jpg"], "max_count": 3}, "label": "Pictures"}],
            "empty_text": "No pain points.",
        },
    ],
}
"""A custom report layout with an images column: each Pain Point's attached pictures beside its code and title (a share of the column wide)."""


def evidence_nodes() -> list[dict]:
    """The blocks appended to the Business Requirements Document starter to make the demo version: every Pain Point,
    Decision and Risk with the pictures attached to it and the requirements it is linked to, so the document shows links, pictures
    and (through the requirement text in its own tables) equations. Each part sits in an `if` on its module, as the
    starters' module parts do."""
    def traced(record_type: str, alias: str, module_key: str, heading_text: str, requirement_empty: str) -> dict:
        return {
            "type": "if", "when": {"module": module_key}, "children": [
                {"type": "heading", "level": 2, "text": heading_text},
                {
                    "type": "each", "source": {"record_type": record_type, "sort": [{"field": "code"}]}, "as": alias,
                    "children": [
                        {"type": "heading", "level": 3, "text": "{{" + alias + ".code}} {{" + alias + ".title}}"},
                        {
                            "type": "record_images", "types": ["png", "jpg", "svg"], "max_count": 3, "width": 10, "width_unit": "cm",
                            "caption_source": "file_name", "numbering": "auto",
                        },
                        {
                            "type": "table", "source": {"record_type": "requirement", "linked_from": alias, "sort": [{"field": "code"}]},
                            "columns": [
                                {"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"},
                                {"field": "status", "label": "Status"},
                            ],
                            "empty_text": requirement_empty,
                        },
                    ],
                },
            ],
        }

    return [
        {"type": "heading", "text": "Evidence and traceability"},
        {"type": "text", "text": "The pictures and diagrams attached to each record, with the requirements it is linked to."},
        traced("pain_point", "pp", "context_strategy", "Pain Points", "No requirement is linked to this Pain Point."),
        traced("decision", "dc", "decisions", "Decisions", "No requirement is linked to this Decision."),
        traced("risk", "rk", "risk_management", "Risks", "No requirement is linked to this Risk."),
    ]


def illustrated_brd_tree(starter_tree: dict) -> dict:
    """The Business Requirements Document starter's tree with `evidence_nodes` after its own sections."""
    return {**starter_tree, "nodes": [*starter_tree["nodes"], *evidence_nodes()]}


def create_illustrated_brd(headers: dict, org_id: str) -> dict:
    """Creates the organisation layout 'Business Requirements Document (with evidence)': a copy of the starter Business
    Requirements Document with `evidence_nodes` after its own sections."""
    layouts = httpx.get(f"{BASE}/orgs/{org_id}/report-layouts", headers=headers, timeout=30)
    layouts.raise_for_status()
    starter = next(layout for layout in layouts.json() if layout["name"] == "Business Requirements Document")
    detail = httpx.get(f"{BASE}/orgs/{org_id}/report-layouts/{starter['id']}", headers=headers, timeout=30)
    detail.raise_for_status()
    return create_report_layout(
        headers, f"/orgs/{org_id}", "Business Requirements Document (with evidence)",
        "The Business Requirements Document with each Pain Point, Decision and Risk, its attached pictures and diagrams, and the "
        "requirements linked to it.",
        illustrated_brd_tree(detail.json()["current"]["tree"]), folder="Handover",
    )


def create_report_layout(headers: dict, path: str, name: str, description: str, tree: dict, folder: str = "") -> dict:
    """Creates a custom report layout at one tier: `/orgs/{id}` or `/projects/{id}` (followed by `/report-layouts`), filed
    under `folder` in the Reports picker (up to three levels, `A/B`)."""
    r = httpx.post(
        f"{BASE}{path}/report-layouts",
        json={"name": name, "description": description, "folder": folder, "family": "document", "tree": tree},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def save_report_layout_draft(headers: dict, path: str, layout: dict, tree: dict) -> None:
    """Leaves unpublished work on a layout: writes `tree` into its shared draft (based on the layout's current version), so the
    designer opens on the draft with its notice. `path` is `/orgs/{id}` or `/projects/{id}`."""
    r = httpx.put(
        f"{BASE}{path}/report-layouts/{layout['id']}/draft",
        json={"tree": tree, "base_version": layout["current_version"], "revision": 0}, headers=headers, timeout=30,
    )
    r.raise_for_status()


#: The product mark: white on transparent, so a report places it on a coloured shape. Kept beside this script (not read from the
#: repository root) so a container build, which copies only `backend/`, finds it.
LOGO_PATH = Path(__file__).parent / "data" / "logo.svg"


def upload_report_image(headers: dict, path: str, file_path: Path, content_type: str) -> dict:
    """Adds a picture to a report image library at one tier: `/orgs/{id}` or `/projects/{id}` (followed by `/report-images`)."""
    r = httpx.post(
        f"{BASE}{path}/report-images", files={"file": (file_path.name, file_path.read_bytes(), content_type)}, headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def project_overview_with_logo_layout(logo_file_id: str) -> dict:
    """A cover banner (the product logo, white on transparent, in front of a plate in the layout's own `plate` colour, a shade of
    the report accent) over the project name and a short requirements table. Both pictures are laid over the page beside the
    title, measured from the title's paragraph, so the title stays readable.

    It also shows the fonts and colours settings: its own colour scheme (`plate`, `highlight`; the organisation's `alert` and
    `success` stay available), a serif body, sans headings in the plate colour, an italic footer with the page numbers, and
    a header showing the cell settings: the organisation name in a fixed 30 % cell, the others fitting their content, all top
    aligned but the date at the bottom. Its table headings take the plate colour once, from the layout (`table_header_fill`), with the
    text colour left automatic.
    """
    return {
        "schema_version": 1, "family": "document", "orientation": "portrait",
        "palette": [{"name": "plate", "colour": "accent_dark"}, {"name": "highlight", "colour": "#b45309"}],
        "styles": {"body": {"font": "serif", "size": 11}, "headings": {"font": "sans", "colour": "plate"}},
        "table_header_fill": "plate",
        "header": {
            "left": "{{organisation}}", "centre": "{{report_title}}", "right": "{{generated_on}}",
            "left_width": "30%", "valign": "top", "right_valign": "bottom", "colour": "plate",
        },
        "footer": {"left": "*{{project_report_name}}*", "right": "*Page {{page}} of {{pages}}*", "colour": "plate"},
        "nodes": [
            {
                "type": "shape", "shape": "rounded", "fill": "plate", "width": 5, "height": 2.5, "alt": "",
                "placement": "behind", "anchor": "paragraph", "offset_x": 12, "offset_y": 0,
            },
            {
                "type": "image", "file": logo_file_id, "alt": "Solstice Robotics logo", "height": 1.75, "height_unit": "cm",
                "placement": "front", "anchor": "paragraph", "offset_x": 12.75, "offset_y": 0.375,
            },
            {"type": "heading", "text": "{{project_name}}"},
            {"type": "text", "text": "Requirements overview, generated {{generated_on}}."},
            {"type": "heading", "level": 2, "text": "Requirements"},
            {
                "type": "table", "source": {"record_type": "requirement", "sort": [{"field": "code"}]},
                "columns": [{"field": "code", "label": "Code"}, {"field": "title", "label": "Requirement"}, {"field": "status", "label": "Status"}],
                "empty_text": "No requirements.",
            },
        ],
    }


def with_snippets(headers: dict, path: str, tree: dict, snippets: list[tuple[str, int | None]]) -> dict:
    """The layout tree with built-in report snippets inserted, as the designer's Insert snippet does: each `(key, index)` goes at
    that position in the layout's blocks (`None`: the end). `path` is `/orgs/{id}` or `/projects/{id}`."""
    for key, index in snippets:
        target = {"container": "nodes"} | ({} if index is None else {"index": index})
        r = httpx.post(
            f"{BASE}{path}/report-layouts/snippets/{key}/apply", json={"tree": tree, "target": target}, headers=headers, timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if not body["ok"]:
            raise RuntimeError(f"Snippet {key} was refused: {body['errors']}")
        tree = body["tree"]
    return tree


def hide_report_layout(headers: dict, project_id: str, layout_id: str) -> None:
    """Hides an inherited report layout in one project."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/report-layouts/{layout_id}/visibility", json={"hidden": True}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def create_report_snippet(
    headers: dict, path: str, name: str, description: str, tree: dict, *, start: int, count: int = 1, category: str = "House style",
) -> dict:
    """Saves blocks `start` to `start + count` of a layout tree as a report snippet at one tier: `/orgs/{id}` or `/projects/{id}`
    (followed by `/report-snippets`)."""
    r = httpx.post(
        f"{BASE}{path}/report-snippets",
        json={
            "name": name, "description": description, "category": category, "tree": tree,
            "selection": {"container": "nodes", "start": start, "count": count},
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_report_pack(headers: dict, path: str, name: str, description: str, definition: dict, folder: str = "") -> dict:
    """Creates a report pack at one tier: `/orgs/{id}` or `/projects/{id}` (followed by `/report-packs`), filed under `folder`."""
    r = httpx.post(
        f"{BASE}{path}/report-packs", json={"name": name, "description": description, "folder": folder, "definition": definition},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_report_pack_set(headers: dict, path: str, pack_id: str, name: str, values: dict) -> dict:
    """Saves a variable set with a report pack (`/orgs/{id}` or `/projects/{id}` followed by `/report-packs/{id}/sets`)."""
    r = httpx.post(f"{BASE}{path}/report-packs/{pack_id}/sets", json={"name": name, "values": values}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_project_link_type(
    headers: dict, project_id: str, *, forward_name: str, reverse_name: str, flow: str = "none",
) -> dict:
    """A link type local to one project (usable there and in every sub-project)."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/link-types",
        json={"forward_name": forward_name, "reverse_name": reverse_name, "flow": flow}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_link_type_visibility(headers: dict, project_id: str, link_type_id: str, hidden: bool) -> dict:
    """Hides (or re-shows) a link type for a project and the sub-projects under it; links already using it keep showing."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/link-types/{link_type_id}/visibility", json={"hidden": hidden}, headers=headers, timeout=30,
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


def create_and_link_action(
    headers: dict, project_id: str, requirement_id: str, *, title: str, description: str, action_type_id: str,
    assignee: dict | None = None, due_date: str | None = None,
) -> dict:
    """Creates an action and links it to a requirement; `assignee` is a principal reference (user or group)."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/actions/create-and-link",
        json={
            "title": title, "description": description, "action_type_id": action_type_id,
            "assignee": assignee, "due_date": due_date,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def link_action(headers: dict, project_id: str, requirement_id: str, action_id: str) -> None:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/actions", json={"action_id": action_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def set_action_outcome(headers: dict, project_id: str, action: dict, outcome_status: str) -> dict:
    r = httpx.patch(
        f"{BASE}/projects/{project_id}/actions/{action['id']}",
        json={
            "title": action["title"], "description": action["description"], "action_type_id": action["action_type_id"],
            "assignee": action.get("assignee"), "due_date": action.get("due_date"),
            "outcome_status": outcome_status,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def add_action_comment(headers: dict, project_id: str, action_id: str, body: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/actions/{action_id}/comments", json={"body": body}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def archive_action(headers: dict, project_id: str, action_id: str) -> None:
    """Archives a requirement action. Left archived rather than restored in
    the demo dataset so a reviewer has a concrete example to click
    "Restore" on — see `POST .../unarchive`, added because archive was one-way for actions, unlike projects."""
    r = httpx.post(f"{BASE}/projects/{project_id}/actions/{action_id}/archive", headers=headers, timeout=30)
    r.raise_for_status()


def set_report_look(
    headers: dict, org_id: str, *, accent_color_hex: str, footer_text: str, include_cover_page: bool = True,
) -> None:
    """Sets the organisation's one report look: accent colour and logo (Branding), footer and cover page (Configuration).

    The advanced-settings endpoint replaces the settings it is given, so the current ones are read and sent back.
    """
    r = httpx.put(
        f"{BASE}/orgs/{org_id}/branding",
        json={
            "report_accent_color_hex": accent_color_hex, "report_include_logo": False,
            # The organisation's named report colours: layouts with no scheme of their own resolve a colour name by them.
            "report_colour_scheme": [{"name": "alert", "colour": "#B42318"}, {"name": "success", "colour": "#067647"}],
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    r = httpx.get(f"{BASE}/orgs/{org_id}/advanced-settings", headers=headers, timeout=30)
    r.raise_for_status()
    current = r.json()
    for read_only in ("report_output_default_retention_days", "report_output_max_retention_days"):
        current.pop(read_only, None)
    current.update(report_footer_text=footer_text, report_include_cover_page=include_cover_page)
    httpx.put(f"{BASE}/orgs/{org_id}/advanced-settings", json=current, headers=headers, timeout=30).raise_for_status()


# --- Compliance Module helpers -


def create_compliance_standard(
    headers: dict, org_id: str, *, reference: str, name: str, description: str = "",
    issuing_organisation: str | None = None, owner: dict | None = None,
    initial_version_label: str = "1.0", initial_version_effective_date: str | None = None,
    initial_version_change_note: str = "",
) -> dict:
    """Creates a standard together with its mandatory first version (§2/§4)
    in one request — the standard's `POST .../standards` endpoint now
    always creates version 1 alongside the standard itself, matching the
    combined create-standard-with-first-version frontend flow. Use
    `list_compliance_versions` to fetch that first version's id rather than
    a separate `create_compliance_version` call, which would create a
    redundant second version. `owner` is `{"type": "user" | "org_group", "id": ...}` (the creator when omitted)."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards",
        json={"reference": reference, "name": name, "description": description,
              "issuing_organisation": issuing_organisation, "owner": owner,
              "initial_version_label": initial_version_label,
              "initial_version_effective_date": initial_version_effective_date,
              "initial_version_change_note": initial_version_change_note},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_compliance_versions(headers: dict, org_id: str, standard_id: str) -> list[dict]:
    r = httpx.get(f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_compliance_version(headers: dict, org_id: str, standard_id: str, *, version_label: str = "1.0", change_note: str = "") -> dict:
    """Creates an additional (second, third, ...) version of an
    already-existing standard. Not used for a standard's first version —
    that one is created alongside the standard itself by
    `create_compliance_standard` (see its own docstring)."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions",
        json={"version_label": version_label, "change_note": change_note}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_compliance_requirement(
    headers: dict, org_id: str, standard_id: str, version_id: str, *, name: str, reference: str | None = None,
    description: str = "", reasoning: str = "", parent_requirement_id: str | None = None,
) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions/{version_id}/requirements",
        json={"name": name, "reference": reference, "description": description, "reasoning": reasoning,
              "parent_requirement_id": parent_requirement_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_compliance_required_action(
    headers: dict, org_id: str, standard_id: str, version_id: str, requirement_id: str, action_type_id: str, *,
    name: str, description: str = "", is_mandatory: bool = True,
) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions/{version_id}/requirements/"
        f"{requirement_id}/required-actions",
        json={"action_type_id": action_type_id, "name": name, "description": description, "is_mandatory": is_mandatory},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def publish_compliance_version(headers: dict, org_id: str, standard_id: str, version_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions/{version_id}/publish",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_compliance_version_summary(headers: dict, org_id: str, standard_id: str, version_id: str, summary: str) -> dict:
    """A version's own current-standing `summary` — editable at
    any lifecycle stage, `standards_manager`-or-override only once
    published/retired."""
    r = httpx.patch(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions/{version_id}",
        json={"summary": summary}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def clarify_compliance_requirement(
    headers: dict, org_id: str, standard_id: str, version_id: str, requirement_id: str, *,
    name: str, reference: str | None = None, description: str = "", reasoning: str = "", clarification_note: str,
) -> dict:
    """A non-substantive correction to a requirement already on a
    `PUBLISHED` version — `standards_manager`-or-override only."""
    r = httpx.patch(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/versions/{version_id}/requirements/"
        f"{requirement_id}/clarify",
        json={"name": name, "reference": reference, "description": description, "reasoning": reasoning,
              "clarification_note": clarification_note},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def assign_compliance_standard(headers: dict, org_id: str, project_id: str, standard_id: str, version_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/projects/{project_id}/project-compliance",
        json={"standard_id": standard_id, "standard_version_id": version_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def grant_custom_role(headers: dict, org_id: str, role_name: str, user_id: str, project_id: str) -> None:
    """Grants an organisation's project-scoped custom role (looked up by name, e.g. the seeded
    "Link editor" preset) to a user on one project."""
    roles = httpx.get(f"{BASE}/orgs/{org_id}/custom-roles", headers=headers, timeout=30)
    roles.raise_for_status()
    role = next(r for r in roles.json() if r["name"] == role_name)
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/custom-roles/{role['id']}/users/{user_id}", json={"project_id": project_id},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def grant_compliance_officer(headers: dict, project_id: str, user_id: str) -> None:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_officer"}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def grant_standard_role(headers: dict, org_id: str, standard_id: str, user_id: str, role_key: str) -> None:
    """Grants a direct, standard-scoped `standards_manager`/`standards_
    contributor` role — distinct from
    `grant_compliance_officer`'s project-scoped grant above; a demo user can
    hold both at once (a project's assessor and a specific standard's own
    working-group contributor are unrelated capabilities)."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/members/{user_id}/roles",
        json={"role_key": role_key}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def update_standard_applicability_default(headers: dict, org_id: str, standard_id: str, applicability_default: str) -> dict:
    """Switches a standard between `opt_in` (default) and
    `applies_to_all_projects`. Switching to the latter immediately
    reconciles a real `ProjectCompliance` row into existence for every
    current, non-archived, non-excluded project in the organisation
    against the standard's latest published version — so this must be
    called after the standard has a published version and after any
    exclusions are already in place (`exclude_project_from_standard_
    default`), not before."""
    r = httpx.patch(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/applicability-default",
        json={"applicability_default": applicability_default}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def exclude_project_from_standard_default(headers: dict, org_id: str, standard_id: str, project_id: str, *, reason: str) -> dict:
    """Excepts `project_id` out of a standard's `applies_to_all_
    projects` default. `reason` is mandatory. Call before flipping the
    standard's applicability default so reconciliation skips this project
    from the start, rather than assigning and then re-archiving it."""
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/compliance/standards/{standard_id}/exclusions",
        json={"project_id": project_id, "reason": reason}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_compliance_requirements(headers: dict, project_id: str, project_compliance_id: str) -> list[dict]:
    r = httpx.get(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_compliance_assessment(
    headers: dict, project_id: str, project_compliance_id: str, pcr_id: str, *,
    compliance_status: str, justification: str = "", notes: str = "",
) -> dict:
    r = httpx.patch(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/assessment",
        json={"compliance_status": compliance_status, "justification": justification, "notes": notes},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def submit_compliance_for_approval(headers: dict, project_id: str, project_compliance_id: str, pcr_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/submit-for-approval",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def approve_compliance_requirement(headers: dict, project_id: str, project_compliance_id: str, pcr_id: str, *, note: str = "") -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/approve",
        json={"decision_note": note}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_required_action_assessments(headers: dict, project_id: str, project_compliance_id: str, pcr_id: str) -> list[dict]:
    r = httpx.get(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/required-action-assessments",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def update_required_action_assessment(
    headers: dict, project_id: str, project_compliance_id: str, pcr_id: str, assessment_id: str, *,
    assignee: dict | None = None, due_date: str | None = None, notes: str = "",
) -> dict:
    """Updates a required action's assignee (`{"type": "user" | "org_group" | "project_group", "id": ...}`), due date and notes."""
    r = httpx.patch(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/required-action-assessments/{assessment_id}",
        json={"assignee": assignee, "due_date": due_date, "notes": notes}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def complete_required_action_assessment(headers: dict, project_id: str, project_compliance_id: str, pcr_id: str, assessment_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements/"
        f"{pcr_id}/required-action-assessments/{assessment_id}/complete",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_compliance_evidence(
    headers: dict, project_id: str, *, title: str, issuing_organisation: str | None = None,
    issued_date: str | None = None, expiry_date: str | None = None, notes: str = "",
    pcr_ids: list[str] | None = None, assessment_ids: list[str] | None = None,
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/compliance/evidence",
        json={
            "title": title, "issuing_organisation": issuing_organisation, "issued_date": issued_date,
            "expiry_date": expiry_date, "notes": notes,
            "project_compliance_requirement_ids": pcr_ids or [], "required_action_assessment_ids": assessment_ids or [],
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_compliance_review(
    headers: dict, project_id: str, project_compliance_id: str, *, frequency_label: str, next_due_date: str,
    recurrence_days: int | None = None, owner: dict | None = None, notes: str = "",
) -> dict:
    """Schedules a project review; `owner` is `{"type": "user" | "org_group" | "project_group", "id": ...}`."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/reviews",
        json={"frequency_label": frequency_label, "next_due_date": next_due_date, "recurrence_days": recurrence_days,
              "owner": owner, "notes": notes},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Demo content --------------------------------------------------------

DRONE_REQUIREMENTS = [
    # (name, reasoning, component_key, category_key, status, extra)
    ("Acquire GPS position lock within 5 seconds of power-on in open-sky conditions",
     "Field operators need to begin a mission almost immediately after power-on; a slow GPS "
     "acquisition directly extends time-on-site for every inspection, which is billed by the hour "
     "on most customer contracts.", "AV", "PERF", "approved", {}),
    ("Autonomously return to launch point when battery charge falls below 15%",
     "Loss-of-aircraft incidents from battery exhaustion are the single largest driver of hull "
     "insurance claims across the fleet to date; an automatic return-to-home at a conservative "
     "threshold removes reliance on the operator noticing in time. The threshold must cover the return energy "
     "\\(E_{rth} = P_{cruise} \\cdot \\frac{d}{v}\\) from the furthest point of the route, plus the reserve.",
     "FW", "SAF", "approved", {}),
    ("Provide a minimum flight time of 42 minutes at an 800g payload",
     "42 minutes covers the median inspection route length (per Q3 fleet telemetry) with enough "
     "margin for a return-to-home from the furthest point on the route without requiring a battery swap. "
     "Hover endurance follows from the battery energy and the hover power draw, \\(t = \\frac{E_{batt}}{P_{hover}}\\), "
     "so the target \\(t \\geq 42\\) min fixes the battery capacity for a given airframe.",
     "PR", "PERF", "approved", {}),
    ("Withstand sustained wind gusts of up to 45 km/h without loss of stability",
     "Coastal and offshore inspection sites regularly see gusts in this range; grounding the fleet "
     "below this threshold would make several existing customer sites unviable. The gust load scales with the "
     "dynamic pressure \\(q = \\tfrac{1}{2}\\rho v^{2}\\), and 45 km/h is \\(v = 12.5\\) m/s.", "AF", "FN", "reviewed", {}),
    ("Stream live video telemetry to the ground station at a minimum of 24fps",
     "Below 24fps, operators reported difficulty judging distance to structures during close-approach "
     "inspection manoeuvres in the beta program.", "AV", "FN", "reviewed", {}),
    ("Log all flight-critical state transitions to onboard non-volatile storage",
     "Required for post-incident analysis and is also a precondition for the Part 107 remote ID "
     "compliance work below — investigators expect a retrievable flight log independent of the "
     "telemetry uplink.", "FW", "REG", "approved", {}),
    ("Support geofencing with a configurable no-fly boundary",
     "Several customer sites are adjacent to controlled airspace; a configurable boundary lets us "
     "onboard those sites without a bespoke firmware build per customer.", "FW", "SAF", "reviewed", {}),
    ("Trigger an audible and visual alert prior to autonomous landing",
     "Ground crew and bystanders need advance warning before an unattended landing, particularly on "
     "sites with pedestrian traffic near the landing pad.", "AV", "SAF", "draft", {}),
    ("Operate in ambient temperatures between -10C and 45C",
     "Covers the full range of currently contracted inspection sites, from northern wind-farm sites "
     "in winter to desert solar sites in summer.", "AF", "FN", "draft", {}),
    ("Support firmware updates over a secure, authenticated wireless connection",
     "Field firmware updates currently require physically retrieving each aircraft; a secure "
     "over-the-air path is the single biggest lever on fleet maintenance cost identified in the "
     "2026 planning review.", "FW", "FN", "draft", {}),
    ("Complete pre-flight diagnostic checks in under 20 seconds",
     "Operator feedback consistently flags pre-flight checks as the most time-pressured part of a "
     "site visit when weather windows are short.", "AV", "PERF", "draft", {"review_in_days": -4}),
    ("Broadcast Part 107 remote identification per FAA requirements",
     "Regulatory requirement for continued commercial operation in U.S. airspace; non-negotiable "
     "for the fleet to remain airworthy past the compliance deadline.", "FW", "REG", "complete", {}),
]

CLOUD_REQUIREMENTS = [
    ("Authenticate all API requests using short-lived, signed access tokens",
     "Long-lived credentials were identified as a risk during the last customer security "
     "questionnaire; short-lived signed tokens bound the blast radius of any single leaked credential.",
     "API", "SEC", "approved", {}),
    ("Respond to authenticated read requests within 200ms at the 95th percentile under nominal load",
     "The live-tracking view in the web dashboard polls this endpoint continuously during an active "
     "flight; anything slower produces visibly stale drone positions on screen.", "API", "PERF", "approved", {}),
    ("Ingest telemetry from up to 500 concurrent drones without data loss",
     "500 concurrent aircraft is 3x current peak fleet utilisation, sized against the sales team's "
     "12-month fleet growth forecast.", "DP", "PERF", "approved", {}),
    ("Display live drone telemetry with end-to-end latency under 2 seconds",
     "Operators use the dashboard as a secondary situational-awareness view during flight; latency "
     "beyond a couple of seconds undermines trust in it as a safety backstop.", "WD", "FN", "reviewed", {}),
    ("Retain raw flight telemetry for a minimum of 12 months",
     "Matches the retention period referenced in customer inspection-report contracts and gives a "
     "full seasonal cycle of history for trend analysis.", "DP", "FN", "reviewed", {"review_in_days": -2}),
    ("Provide role-based access control scoped to individual fleets",
     "Several customers operate as resellers with their own sub-customers and need to restrict each "
     "sub-customer's users to only their own aircraft.", "API", "SEC", "approved", {}),
    ("Support exporting flight logs in CSV and KML formats",
     "CSV covers most customers' existing spreadsheet-based reporting workflows; KML is the format "
     "requested by name in two active enterprise deals for import into their own GIS tooling.",
     "WD", "FN", "draft", {}),
    ("Maintain 99.9% API availability measured monthly",
     "99.9% is the availability figure already committed to in the current enterprise SLA template; "
     "this requirement exists so engineering is held to the same number sales is quoting.", "API", "REL", "reviewed", {}),
    ("Automatically flag telemetry anomalies indicative of sensor failure",
     "Early detection of a degrading sensor lets maintenance schedule a repair before it causes an "
     "in-flight incident, rather than discovering it during post-flight review.", "DP", "FN", "draft", {}),
    ("Encrypt all telemetry data at rest",
     "Flight telemetry can reveal customer site layouts and operating patterns; encryption at rest "
     "is a standing commitment in the current data processing addendum template.", "DP", "SEC", "approved", {}),
    ("Support two-factor authentication for all user accounts",
     "Account takeover was the top risk flagged in the most recent customer security review of the "
     "platform.", "WD", "SEC", "draft", {}),
    ("Provide a status page reflecting real-time system health",
     "Reduces inbound support load during incidents — customers currently have no way to self-serve "
     "check whether an issue is on our side before opening a ticket.", "API", "REL", "draft", {}),
]

AVIONICS_REQUIREMENTS = [
    # (name, reasoning, component_key, category_key, status, extra)
    ("Fuse GPS, IMU, and barometric altitude into a single position estimate at 50Hz",
     "The flight controller consumes a single blended estimate rather than raw sensor feeds — fusing "
     "at 50Hz keeps the control loop within the latency budget the airframe stability model assumes.",
     "SN", "PERF", "approved", {}),
    ("Detect and flag GPS spoofing via cross-check against IMU dead-reckoning",
     "A diverging GPS/IMU solution beyond the expected drift envelope is the leading indicator of "
     "spoofing seen in the fleet's incident reports to date; flagging it lets the flight controller "
     "fall back to dead-reckoning rather than trusting a compromised fix.", "SN", "SAF", "reviewed", {}),
    ("Report sensor self-test results to the ground station on every power-on",
     "Field crews currently only discover a degraded sensor mid-flight; surfacing self-test results "
     "at power-on lets them stand down before launch instead.", "SN", "FN", "draft", {}),
]


REQUIREMENT_DESCRIPTIONS: dict[str, str] = {
    # The requirement statement (what the document prints in its Description column), keyed by requirement name. Formulas
    # are written between \\( and \\), as in any record text.
    "Acquire GPS position lock within 5 seconds of power-on in open-sky conditions":
        "The aircraft shall report a valid three-dimensional position fix no later than \\(t_{fix} = 5\\) s after power-on, "
        "with at least 8 satellites in view and an unobstructed sky.",
    "Autonomously return to launch point when battery charge falls below 15%":
        "When the remaining charge \\(C\\) falls below \\(0.15\\,C_{full}\\), the flight controller shall abandon the "
        "mission and fly the aircraft back to the launch point without operator input.",
    "Provide a minimum flight time of 42 minutes at an 800g payload":
        "With an 800 g payload the aircraft shall hover for at least \\(t = \\frac{E_{batt}}{P_{hover}} \\geq 42\\) minutes "
        "at sea level and 20 \u00b0C.",
    "Withstand sustained wind gusts of up to 45 km/h without loss of stability":
        "The aircraft shall hold its position within 1 m in gusts up to \\(v = 12.5\\) m/s (45 km/h), a dynamic pressure of "
        "\\(q = \\tfrac{1}{2}\\rho v^{2} \\approx 96\\) Pa.",
    "Stream live video telemetry to the ground station at a minimum of 24fps":
        "The video link shall deliver at least 24 frames per second to the ground station for the whole flight.",
    "Log all flight-critical state transitions to onboard non-volatile storage":
        "Every change of flight mode, arming state and failsafe shall be written with its time to non-volatile storage "
        "before the change takes effect.",
    "Support geofencing with a configurable no-fly boundary":
        "The operator shall be able to load a polygonal no-fly boundary, and the aircraft shall refuse to cross it.",
    "Trigger an audible and visual alert prior to autonomous landing":
        "The aircraft shall sound a tone and flash its lights for at least 5 s before any landing it starts without operator input.",
    "Operate in ambient temperatures between -10C and 45C":
        "The aircraft shall meet every performance requirement for ambient temperatures \\(T\\) with "
        "\\(-10 \\leq T \\leq 45\\) \u00b0C.",
    "Support firmware updates over a secure, authenticated wireless connection":
        "The aircraft shall accept a firmware image over the wireless link only when the image is signed by the manufacturer.",
    "Complete pre-flight diagnostic checks in under 20 seconds":
        "The pre-flight diagnostic sequence shall finish and report its result within \\(t = 20\\) s of the operator starting it.",
    "Broadcast Part 107 remote identification per FAA requirements":
        "The aircraft shall broadcast its identity, position and control-station location at least once per second, as the "
        "FAA remote identification rule requires.",
    "Authenticate all API requests using short-lived, signed access tokens":
        "Every API request shall carry a signed access token that expires within 15 minutes of issue.",
    "Respond to authenticated read requests within 200ms at the 95th percentile under nominal load":
        "At nominal load, 95% of authenticated read requests shall complete within 200 ms.",
    "Ingest telemetry from up to 500 concurrent drones without data loss":
        "The platform shall accept telemetry from 500 aircraft at once and lose no accepted message.",
    "Display live drone telemetry with end-to-end latency under 2 seconds":
        "A telemetry value shall appear in the web dashboard within 2 s of the aircraft sending it.",
    "Retain raw flight telemetry for a minimum of 12 months":
        "Raw telemetry shall remain retrievable for at least 12 months after the flight.",
    "Provide role-based access control scoped to individual fleets":
        "A user shall see and control only the fleets their role grants.",
    "Support exporting flight logs in CSV and KML formats":
        "A user shall be able to export a flight log as a CSV file or as a KML file.",
    "Maintain 99.9% API availability measured monthly":
        "The API shall be available for at least 99.9% of each calendar month, which allows no more than about 43 minutes of downtime.",
    "Automatically flag telemetry anomalies indicative of sensor failure":
        "The platform shall flag a flight whose sensor readings leave the expected range for the sensor.",
    "Encrypt all telemetry data at rest":
        "All stored telemetry shall be encrypted with keys the organisation manages.",
    "Support two-factor authentication for all user accounts":
        "Every account shall be able to require a second factor at sign-in.",
    "Provide a status page reflecting real-time system health":
        "A public page shall show the current state of each platform service, updated within 1 minute of a change.",
    "Fuse GPS, IMU, and barometric altitude into a single position estimate at 50Hz":
        "The estimator shall publish one fused position and altitude estimate at \\(f = 50\\) Hz, a period of "
        "\\(T = 1/f = 20\\) ms.",
    "Detect and flag GPS spoofing via cross-check against IMU dead-reckoning":
        "The estimator shall flag the GPS fix as suspect when it differs from the dead-reckoned position by more than the "
        "expected drift.",
    "Report sensor self-test results to the ground station on every power-on":
        "At every power-on the aircraft shall send the result of each sensor's self-test to the ground station.",
}


def seed_project(
    headers: dict, project: dict, components: dict[str, dict], categories: dict[str, dict[str, dict]],
    specs: list[tuple], demo_admin_id: str,
) -> dict[str, dict]:
    by_name = {}
    for name, reasoning, comp_key, cat_key, status_value, extra in specs:
        req = create_requirement(
            headers, project["id"], name=name, reasoning=reasoning, description=REQUIREMENT_DESCRIPTIONS.get(name, ""),
            component_id=components[comp_key]["id"], category_id=categories[comp_key][cat_key]["id"],
        )
        if status_value != "draft":
            review_date = None
            reviewer_id = None
            if "review_in_days" in extra:
                review_date = (date.today() + timedelta(days=extra["review_in_days"])).isoformat()
                reviewer_id = demo_admin_id
            target_status = "completed" if status_value == "complete" else status_value
            if target_status == "completed":
                # C-G-11: completion is an overlay on top of "approved", not
                # its own status — `req["status"]` correctly stays
                # "approved" after this; `req["is_completed"]` is what now
                # reflects the demo intent.
                req = set_requirement_status(headers, project["id"], req, "approved")
                req = complete_requirement(headers, project["id"], req["id"])
            else:
                req = set_requirement_status(headers, project["id"], req, target_status, review_date=review_date, reviewer_id=reviewer_id)
        elif "review_in_days" in extra:
            review_date = (date.today() + timedelta(days=extra["review_in_days"])).isoformat()
            req = set_requirement_status(headers, project["id"], req, "draft", review_date=review_date, reviewer_id=demo_admin_id)
        by_name[name] = req
    return by_name


# --- Decision Management module helpers --------------------------------------------
#
# `Decision.decision_type_id` is a required FK, but every *root* project
# already has 5 default `DecisionTypeDefinition` rows seeded by
# `on_project_created` (Architecture/Design/Engineering/Strategy/
# Operational), not gated on this module's own `enabled` state — so
# `list_decision_types` always has something to pick from without this
# script creating any itself, as long as the project used here (Falcon-3
# Inspection Drone, a root project) isn't a child (a
# child starts with none of its own and inherits its nearest ancestor's
# instead — see `service.resolve_effective_decision_types`).


def enable_module(headers: dict, org_id: str, module_key: str) -> None:
    """`default_enabled=False` modules (Decision Management) need this;
    `default_enabled=True` ones (Compliance) never call it — see `docs/
    modules.md`'s "Effective enabled" formula."""
    r = httpx.put(f"{BASE}/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=headers, timeout=30)
    r.raise_for_status()


def list_decision_types(headers: dict, project_id: str) -> dict[str, dict]:
    r = httpx.get(f"{BASE}/projects/{project_id}/modules/decisions/decision-types", headers=headers, timeout=30)
    r.raise_for_status()
    return {t["name"]: t for t in r.json()}


def create_decision(
    headers: dict, project_id: str, *, title: str, decision_statement: str, decision_type_id: str,
    owner_id: str | None = None, decision_maker_id: str | None = None, owner_group_id: str | None = None,
    context: str = "", options_considered: str = "", chosen_option: str = "", rationale: str = "",
    consequences: str = "", decision_date: str | None = None,
) -> dict:
    """Creates a Decision. The owner is a user (`owner_id`) or an organisation group (`owner_group_id`);
    the decision maker is a user."""
    owner = {"type": "org_group", "id": owner_group_id} if owner_group_id else {"type": "user", "id": owner_id}
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/decisions",
        json={
            "title": title, "decision_statement": decision_statement, "decision_type_id": decision_type_id,
            "owner": owner,
            "decision_maker": {"type": "user", "id": decision_maker_id} if decision_maker_id else None,
            "decision_date": decision_date,
            "context": context,
            "options_considered": options_considered, "chosen_option": chosen_option, "rationale": rationale,
            "consequences": consequences,
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def advance_decision_to_review(headers: dict, project_id: str, decision_id: str, *, submit_for_review: bool = True) -> None:
    """Moves a Decision to `Proposed`, and on to `Under review` unless `submit_for_review` is false — for demo
    Decisions meant to read as waiting for a verdict (the Approval ageing report)."""
    steps = ["propose", "submit-for-review"] if submit_for_review else ["propose"]
    for step in steps:
        httpx.post(f"{BASE}/projects/{project_id}/modules/decisions/{decision_id}/{step}", headers=headers, timeout=30).raise_for_status()


def propose_and_approve_decision(headers: dict, project_id: str, decision_id: str, *, approval_comment: str = "") -> dict:
    """Walks a Decision through its full lifecycle to `Approved` in one
    call — `Draft -> Proposed -> Under Review -> Approved` (§13/10.4) — for demo Decisions meant to already read as settled."""
    httpx.post(f"{BASE}/projects/{project_id}/modules/decisions/{decision_id}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(
        f"{BASE}/projects/{project_id}/modules/decisions/{decision_id}/submit-for-review", headers=headers, timeout=30
    ).raise_for_status()
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/decisions/{decision_id}/approve",
        json={"comment": approval_comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_decision_supersession(headers: dict, project_id: str, new_decision_id: str, old_decision_id: str) -> dict:
    """`new_decision_id` supersedes `old_decision_id` — both must already be
    `Approved` for the old one to flip to `Superseded` immediately (§13/10.6; see `service.py`'s own `_maybe_supersede`)."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/decisions/{new_decision_id}/supersessions",
        json={"old_decision_id": old_decision_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Context & Strategy module helpers -------------------------------------------------


def create_org_strategy(headers: dict, org_id: str, **fields) -> dict:
    r = httpx.post(f"{BASE}/orgs/{org_id}/modules/context_strategy/strategies", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_project_strategy(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/strategies", json=fields, headers=headers, timeout=30
    )
    r.raise_for_status()
    return r.json()


def propose_and_approve_org_strategy(headers: dict, org_id: str, strategy_id: str, *, approval_comment: str = "") -> dict:
    """Walks an org-scoped Strategy through `Draft -> Proposed -> Under
    Review -> Approved -> Active` in one call, for a demo Strategy meant to
    already read as settled and in force."""
    base = f"{BASE}/orgs/{org_id}/modules/context_strategy/strategies/{strategy_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/submit-for-review", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def propose_and_approve_project_strategy(
    headers: dict, project_id: str, strategy_id: str, *, approval_comment: str = ""
) -> dict:
    """Project-scoped sibling of `propose_and_approve_org_strategy`."""
    base = f"{BASE}/projects/{project_id}/modules/context_strategy/strategies/{strategy_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/submit-for-review", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


# --- Context & Strategy module helpers: Future State -----------------------


def create_org_future_state(headers: dict, org_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/context_strategy/future-states", json=fields, headers=headers, timeout=30
    )
    r.raise_for_status()
    return r.json()


def create_project_future_state(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/future-states", json=fields, headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def propose_and_approve_org_future_state(
    headers: dict, org_id: str, future_state_id: str, *, approval_comment: str = ""
) -> dict:
    """Walks an org-scoped Future State through `Draft -> Proposed -> Under
    Review -> Approved -> Active` in one call — sibling of `propose_and_
    approve_org_strategy`."""
    base = f"{BASE}/orgs/{org_id}/modules/context_strategy/future-states/{future_state_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/submit-for-review", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def propose_and_approve_project_future_state(
    headers: dict, project_id: str, future_state_id: str, *, approval_comment: str = ""
) -> dict:
    """Project-scoped sibling of `propose_and_approve_org_future_state`."""
    base = f"{BASE}/projects/{project_id}/modules/context_strategy/future-states/{future_state_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/submit-for-review", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


# --- Context & Strategy module helpers: Pain Points -----------------------


def list_effective_pain_point_types(headers: dict, project_id: str) -> dict[str, dict]:
    """Returns this project's effective Pain Point type list
    keyed by name — mirrors `list_decision_types`'s identical shape."""
    r = httpx.get(f"{BASE}/projects/{project_id}/modules/context_strategy/pain-point-types", headers=headers, timeout=30)
    r.raise_for_status()
    return {t["name"]: t for t in r.json()}


# What belongs under each default Pain Point type; shown under the Type picker on a new Pain Point.
PAIN_POINT_TYPE_DEFINITIONS: dict[str, str] = {
    "Market": "A problem in how the product competes or sells: pricing, positioning, the competitors' offer, buyers' expectations.",
    "User": "A problem for the people who use the product directly: tasks that are slow, confusing or error-prone.",
    "Operator": "A problem for the people who run, deploy or maintain the product: setup, monitoring, support, upgrades.",
}


def set_project_module(headers: dict, project_id: str, module_key: str, enabled: bool) -> None:
    """Sets a project's own switch for a module (a project starts with the organisation's defaults)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/{module_key}/enablement", json={"enabled": enabled}, headers=headers, timeout=30,
    )
    r.raise_for_status()


def hide_pain_point_types(headers: dict, project_id: str, names: list[str]) -> None:
    """Hides the organisation's default Pain Point types of these names in one project."""
    effective = list_effective_pain_point_types(headers, project_id)
    for name in names:
        r = httpx.delete(
            f"{BASE}/projects/{project_id}/modules/context_strategy/pain-point-types/{effective[name]['id']}", headers=headers, timeout=30,
        )
        r.raise_for_status()


def add_pain_point_types(headers: dict, project_id: str, definitions: dict[str, str]) -> None:
    """Adds project-only Pain Point types, each with its definition (the text shown under the Type picker)."""
    for name, definition in definitions.items():
        r = httpx.post(
            f"{BASE}/projects/{project_id}/modules/context_strategy/pain-point-types",
            json={"name": name, "definition": definition}, headers=headers, timeout=30,
        )
        r.raise_for_status()


def set_pain_point_type_definitions(headers: dict, org_id: str, types_by_name: dict[str, dict], definitions: dict[str, str]) -> None:
    """Writes the organisation-level definition of each named default Pain Point type. `types_by_name` is a project's
    effective list; an organisation type with no override has the organisation type's own id."""
    for name, definition in definitions.items():
        r = httpx.patch(
            f"{BASE}/orgs/{org_id}/modules/context_strategy/pain-point-types/{types_by_name[name]['id']}",
            json={"definition": definition}, headers=headers, timeout=30,
        )
        r.raise_for_status()


def create_pain_point(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points", json=fields, headers=headers, timeout=30
    )
    r.raise_for_status()
    return r.json()


def assign_owner(headers: dict, project_id: str, path: str, record: dict, fields: tuple[str, ...], owner: dict) -> dict:
    """Sets the owner of a Pain Point (`pain-points`) or Open Question (`open-questions`): both are full-replace
    edits, so the record's own `fields` are sent back with the `owner` principal (`{"type", "id"}`)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/context_strategy/{path}/{record['id']}",
        json={**{f: record[f] for f in fields}, "owner": owner}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def triage_pain_point(headers: dict, project_id: str, pain_point_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/triage",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def accept_pain_point(headers: dict, project_id: str, pain_point_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/accept",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def address_pain_point(headers: dict, project_id: str, pain_point_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/address",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def reject_pain_point(headers: dict, project_id: str, pain_point_id: str, *, comment: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/reject",
        json={"comment": comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mark_pain_point_duplicate(headers: dict, project_id: str, pain_point_id: str, *, comment: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/mark-duplicate",
        json={"comment": comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_pain_point_levels(headers: dict, project_id: str) -> dict[str, dict[str, str]]:
    """Returns the org's Pain Point scoring levels as `{axis_key: {level_name: level_id}}`."""
    r = httpx.get(f"{BASE}/projects/{project_id}/scoring-schemes/pain_point", headers=headers, timeout=30)
    r.raise_for_status()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in r.json()["axes"]}


def score_entry(levels: dict[str, dict[str, str]], target_id: str | None = None, **chosen: str) -> dict:
    """Builds one Pain Point score row from level names, e.g. `severity="Major", frequency="Constant"`;
    `target_id=None` is the General row (every criterion, including those scored for the whole Pain Point)."""
    return {"target_id": target_id, "levels": {axis: levels[axis][name] for axis, name in chosen.items()}}


def set_pain_point_scores(headers: dict, project_id: str, pain_point_id: str, scores: list[dict]) -> dict:
    """Replaces a Pain Point's scores (the General row and the personas that differ)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/scores",
        json={"scores": scores}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_project_scoring_default_model(headers: dict, project_id: str, scheme: str, model: str) -> dict:
    """Overrides a project's default scoring model (generic scoring-matrix
    core)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/scoring-schemes/{scheme}/default-model", json={"model": model},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_project_scoring_cell_ratings(headers: dict, project_id: str, scheme: str, model: str, cells: list[dict]) -> dict:
    """Overrides a project's per-cell ratings for a two-axis model (generic
    scoring-matrix core)."""
    r = httpx.put(
        f"{BASE}/projects/{project_id}/scoring-schemes/{scheme}/models/{model}/cell-ratings", json={"cells": cells},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Context & Strategy module helpers: Guiding Principles -----------------


def create_org_guiding_principle(headers: dict, org_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/context_strategy/guiding-principles", json=fields, headers=headers, timeout=30
    )
    r.raise_for_status()
    return r.json()


def create_project_guiding_principle(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/guiding-principles", json=fields, headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def propose_and_approve_org_guiding_principle(
    headers: dict, org_id: str, guiding_principle_id: str, *, approval_comment: str = ""
) -> dict:
    """Walks an org-scoped Guiding Principle through `Draft -> Proposed ->
    Approved -> Active` in one call — sibling of `propose_and_approve_org_
    strategy`, minus the `submit-for-review` step (Guiding Principle's
    lifecycle has no `Under Review` state — see `enums.
    GuidingPrincipleStatus`'s own docstring)."""
    base = f"{BASE}/orgs/{org_id}/modules/context_strategy/guiding-principles/{guiding_principle_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def propose_and_approve_project_guiding_principle(
    headers: dict, project_id: str, guiding_principle_id: str, *, approval_comment: str = ""
) -> dict:
    """Project-scoped sibling of `propose_and_approve_org_guiding_principle`."""
    base = f"{BASE}/projects/{project_id}/modules/context_strategy/guiding-principles/{guiding_principle_id}"
    httpx.post(f"{base}/propose", headers=headers, timeout=30).raise_for_status()
    httpx.post(f"{base}/approve", json={"comment": approval_comment}, headers=headers, timeout=30).raise_for_status()
    r = httpx.post(f"{base}/activate", json={}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


# --- Context & Strategy module helpers: Open Questions --------------------


def create_open_question(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions", json=fields, headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def investigate_open_question(headers: dict, project_id: str, open_question_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions/{open_question_id}/investigate",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mark_open_question_ready_for_decision(headers: dict, project_id: str, open_question_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions/{open_question_id}"
        "/mark-ready-for-decision",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def resolve_open_question(headers: dict, project_id: str, open_question_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions/{open_question_id}/resolve",
        json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def withdraw_open_question(headers: dict, project_id: str, open_question_id: str, *, comment: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions/{open_question_id}/withdraw",
        json={"comment": comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Context & Strategy relationship helpers ------------


def create_org_strategy_relationship(headers: dict, org_id: str, strategy_id: str, *, kind: str, target_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/context_strategy/strategies/{strategy_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_project_strategy_relationship(
    headers: dict, project_id: str, strategy_id: str, *, kind: str, target_id: str
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/strategies/{strategy_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_project_pain_point_relationship(
    headers: dict, project_id: str, pain_point_id: str, *, kind: str, target_id: str
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_org_guiding_principle_relationship(
    headers: dict, org_id: str, guiding_principle_id: str, *, kind: str, target_id: str
) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/context_strategy/guiding-principles/{guiding_principle_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_project_guiding_principle_relationship(
    headers: dict, project_id: str, guiding_principle_id: str, *, kind: str, target_id: str
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/guiding-principles/{guiding_principle_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_project_open_question_relationship(
    headers: dict, project_id: str, open_question_id: str, *, kind: str, target_id: str
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/context_strategy/open-questions/{open_question_id}/relationships",
        json={"kind": kind, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Stakeholders & Personas helpers (Persona) --------------------------------------


def create_org_persona(headers: dict, org_id: str, **fields) -> dict:
    r = httpx.post(f"{BASE}/orgs/{org_id}/modules/stakeholders/personas", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def create_project_persona(headers: dict, project_id: str, **fields) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/modules/stakeholders/personas", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def activate_org_persona(headers: dict, org_id: str, persona_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/modules/stakeholders/personas/{persona_id}/activate", json={}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def activate_project_persona(headers: dict, project_id: str, persona_id: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/stakeholders/personas/{persona_id}/activate", json={}, headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_project_persona_weight_override(headers: dict, project_id: str, persona_id: str, weight: float) -> dict:
    r = httpx.put(
        f"{BASE}/projects/{project_id}/modules/stakeholders/personas/{persona_id}/weight", json={"weight": weight},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# --- Stakeholders helpers (Stakeholder) ------------------


def get_stakeholder_levels(headers: dict, org_id: str) -> dict[str, dict[str, str]]:
    """`{axis: {level name: level id}}` of the org's `stakeholder` scoring scheme."""
    r = httpx.get(f"{BASE}/orgs/{org_id}/scoring-schemes/stakeholder", headers=headers, timeout=30)
    r.raise_for_status()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in r.json()["axes"]}


def get_stakeholder_type_id(headers: dict, *, org_id: str | None = None, project_id: str | None = None, name: str) -> str:
    """The id of the org (or a project's effective) Stakeholder type called `name`."""
    base = f"{BASE}/orgs/{org_id}/modules/stakeholders" if org_id else f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.get(f"{base}/stakeholder-types", headers=headers, timeout=30)
    r.raise_for_status()
    return next(t["id"] for t in r.json() if t["name"] == name)


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


def create_stakeholder_group(
    headers: dict, *, org_id: str | None = None, project_id: str | None = None, **fields
) -> dict:
    """Creates an org- or project-scoped Stakeholder group (exactly one of `org_id`/`project_id`); `fields` are
    `name`, `parent_group_id`, `exclusive_children`, `description`."""
    base = f"{BASE}/orgs/{org_id}/modules/stakeholders" if org_id else f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.post(f"{base}/stakeholder-groups", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def add_stakeholder_to_group(
    headers: dict, group_id: str, stakeholder_id: str, *, org_id: str | None = None, project_id: str | None = None
) -> None:
    """Puts a stakeholder directly into a group of the same tier (`org_id` for an org group, `project_id` for a project one)."""
    base = f"{BASE}/orgs/{org_id}/modules/stakeholders" if org_id else f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.post(
        f"{base}/stakeholder-groups/{group_id}/members", json={"stakeholder_id": stakeholder_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()


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


def enable_research_extras(headers: dict, org_id: str) -> None:
    """Turns the Stakeholders module's `research_extras` sub-component (session prompts, anonymous participants,
    findings; off by default) on for an organisation."""
    r = httpx.put(
        f"{BASE}/orgs/{org_id}/modules/stakeholders/subcomponents/research_extras", json={"enabled": True},
        headers=headers, timeout=30,
    )
    r.raise_for_status()


def create_engagement(
    headers: dict, project_id: str, *, outcomes: tuple[tuple[str, str, str], ...] = (), prompts: tuple[tuple[str, str], ...] = (),
    anonymous: tuple[tuple[str, str | None], ...] = (), findings: tuple[dict, ...] = (), **fields,
) -> dict:
    """Logs a project Engagement. `fields` are the create payload (title, channel, engagement_date,
    stakeholder_ids, persona_ids, group_ids, ...). `outcomes` are `(kind, target_type, target_id)` raised/answered links,
    `prompts` `(prompt, response_notes)`, `anonymous` `(label, persona_id)` and `findings` `{title, description,
    outcomes}` dicts; the last three need the `research_extras` sub-component."""
    base = f"{BASE}/projects/{project_id}/modules/stakeholders"
    r = httpx.post(f"{base}/engagements", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    engagement = r.json()
    url = f"{base}/engagements/{engagement['id']}"
    for kind, target_type, target_id in outcomes:
        body = {"kind": kind, "target_type": target_type, "target_id": target_id}
        httpx.post(f"{url}/outcomes", json=body, headers=headers, timeout=30).raise_for_status()
    for prompt, response_notes in prompts:
        httpx.post(f"{url}/prompts", json={"prompt": prompt, "response_notes": response_notes}, headers=headers, timeout=30).raise_for_status()
    for label, persona_id in anonymous:
        httpx.post(f"{url}/anonymous-participants", json={"label": label, "persona_id": persona_id}, headers=headers, timeout=30).raise_for_status()
    for finding in findings:
        body = {"title": finding["title"], "description": finding.get("description", "")}
        r = httpx.post(f"{url}/findings", json=body, headers=headers, timeout=30)
        r.raise_for_status()
        for kind, target_type, target_id in finding.get("outcomes", ()):
            body = {"kind": kind, "target_type": target_type, "target_id": target_id}
            httpx.post(f"{base}/findings/{r.json()['id']}/outcomes", json=body, headers=headers, timeout=30).raise_for_status()
    return engagement


def add_stakeholder_relationship(
    headers: dict, project_id: str, holder_kind: str, holder_id: str, kind: str, target_type: str, target_id: str,
) -> dict:
    """Adds a §10.5 relationship from a Stakeholder (`holder_kind="stakeholder"`) or Persona
    (`"persona"`) to a record of `project_id`, e.g. kind `experiences_pain_point` with target type `pain_point`."""
    r = httpx.post(
        f"{BASE}/projects/{project_id}/modules/stakeholders/{holder_kind}s/{holder_id}/relationships",
        json={"kind": kind, "target_type": target_type, "target_id": target_id}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def list_effective_risk_types(headers: dict, project_id: str) -> dict[str, dict]:
    """Returns a project's effective Risk types, keyed by name."""
    r = httpx.get(f"{BASE}/projects/{project_id}/modules/risk_management/risk-types", headers=headers, timeout=30)
    r.raise_for_status()
    return {t["name"]: t for t in r.json()}


def get_risk_levels(headers: dict, project_id: str) -> dict[str, dict[str, str]]:
    """Returns the `risk` scoring scheme's level ids as axis key -> level name -> id."""
    r = httpx.get(f"{BASE}/projects/{project_id}/scoring-schemes/risk", headers=headers, timeout=30)
    r.raise_for_status()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in r.json()["axes"]}


def create_risk(
    headers: dict, project_id: str, levels: dict[str, dict[str, str]], *, inherent: tuple[str, str] | None = None,
    residual: tuple[str, str] | None = None, **fields,
) -> dict:
    """Creates a project Risk (it starts Identified). `inherent`/`residual` are `(likelihood, consequence)` level names
    from the `risk` scoring scheme, turned into the matching level ids. `owner` is
    `{"type": "user" | "org_group" | "project_group", "id": ...}`."""
    for prefix, chosen in (("inherent", inherent), ("residual", residual)):
        if chosen is not None:
            fields[f"{prefix}_likelihood_level_id"] = levels["likelihood"][chosen[0]]
            fields[f"{prefix}_consequence_level_id"] = levels["consequence"][chosen[1]]
    r = httpx.post(f"{BASE}/projects/{project_id}/modules/risk_management/risks", json=fields, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_request_levels(headers: dict, project_id: str) -> dict[str, dict[str, str]]:
    """Returns the org's enhancement-request scoring levels as `{axis_key: {level_name: level_id}}`."""
    r = httpx.get(f"{BASE}/projects/{project_id}/scoring-schemes/enhancement_request", headers=headers, timeout=30)
    r.raise_for_status()
    return {axis["key"]: {lvl["name"]: lvl["id"] for lvl in axis["levels"]} for axis in r.json()["axes"]}


def request_score_fields(
    levels: dict[str, dict[str, str]], reach: str, impact: str, confidence: str, effort: str, ease: str | None = None,
    safety: str | None = None,
) -> dict:
    """The `levels` payload of a scored request, by level name (Demand is derived from the requesters, so it is
    never set here; leaving `ease` out leaves the request unscored under ICE; `safety` is the Falcon-3 project's own
    "Safety relevance" axis)."""
    chosen = {"reach": reach, "impact": impact, "confidence": confidence, "effort": effort}
    if ease is not None:
        chosen["ease"] = ease
    if safety is not None:
        chosen["c_safety_relevance"] = safety
    return {"levels": {axis: levels[axis][name] for axis, name in chosen.items()}}


def create_enhancement_request(headers: dict, base: str, *, title: str, description: str = "", **fields) -> dict:
    """Submits a Product Feedback enhancement request (it starts New). `base` is the project's or organisation's
    `.../modules/product_feedback` URL, so the same helper fills a project list and the organisation inbox."""
    r = httpx.post(
        f"{base}/requests", json={"title": title, "description": description, **fields}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def transition_enhancement_request(headers: dict, base: str, request_id: str, status: str, comment: str = "") -> dict:
    """Moves an enhancement request to `status` (declining needs a `comment`, the decline reason)."""
    r = httpx.post(
        f"{base}/requests/{request_id}/transition", json={"status": status, "comment": comment}, headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def transition_risk(headers: dict, project_id: str, risk_id: str, *statuses: str) -> dict:
    """Moves a Risk through the given lifecycle statuses in order and returns the last response."""
    out: dict = {}
    for status in statuses:
        r = httpx.post(
            f"{BASE}/projects/{project_id}/modules/risk_management/risks/{risk_id}/transition",
            json={"status": status}, headers=headers, timeout=30,
        )
        r.raise_for_status()
        out = r.json()
    return out


def seed_architecture(headers: dict, org_id: str, project_id: str) -> dict[str, int]:
    """Seeds a small Falcon-3 architecture: the drone as a System with a flight-controller Board (ports on each),
    a GPS Sensor, a Telemetry Service and a ground-station Service, and the connections between them (SPI, UART,
    REST API, Power), plus an organisation-owned identity service shared with the project through a collection.
    The Board, Sensor and Service types are drawn with the built-in symbols a new organisation is given, and the
    drone with a symbol uploaded to the project's own library. Returns the number of elements and connections created."""
    enable_module(headers, org_id, "architecture")
    base = f"{BASE}/projects/{project_id}/modules/architecture"

    def effective(path: str) -> dict[str, str]:
        r = httpx.get(f"{base}/{path}", headers=headers, timeout=30)
        r.raise_for_status()
        return {row["name"]: row["id"] for row in r.json()}

    element_types, connection_types = effective("element-types"), effective("connection-types")
    quadcopter = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" '
        'stroke-linecap="round"><circle cx="14" cy="14" r="8"/><circle cx="50" cy="14" r="8"/><circle cx="14" cy="50" r="8"/>'
        '<circle cx="50" cy="50" r="8"/><path d="M20 20l24 24M44 20L20 44"/><rect x="26" y="26" width="12" height="12" rx="2"/></svg>'
    )
    uploaded = httpx.post(
        f"{base}/symbols", headers=headers, timeout=30, data={"name": "Quadcopter"},
        files={"file": ("quadcopter.svg", quadcopter.encode(), "image/svg+xml")},
    )
    uploaded.raise_for_status()

    def element(
        name: str, type_name: str, description: str, *, parent: str | None = None, ports: tuple = (), symbol: str | None = None,
    ) -> dict:
        r = httpx.post(
            f"{base}/elements", headers=headers, timeout=30,
            json={
                "name": name, "description": description, "element_type_id": element_types[type_name],
                "parent_id": parent, "activate": True, "symbol_id": symbol,
                "ports": [{"name": n, "direction": d, "connection_type_id": connection_types.get(t)} for n, d, t in ports],
            },
        )
        r.raise_for_status()
        return r.json()

    def connect(name: str, type_name: str, source: dict, source_port: str, target: dict, target_port: str, protocol: str) -> dict:
        def port(item: dict, port_name: str) -> str | None:
            return next((p["id"] for p in item["ports"] if p["name"] == port_name), None)

        r = httpx.post(
            f"{base}/connections", headers=headers, timeout=30,
            json={
                "name": name, "connection_type_id": connection_types[type_name], "protocol": protocol,
                "source_element_id": source["id"], "source_port_id": port(source, source_port),
                "target_element_id": target["id"], "target_port_id": port(target, target_port), "activate": True,
            },
        )
        r.raise_for_status()
        return r.json()

    drone = element(
        "Falcon-3 drone", "System", "The inspection drone and its ground segment.", symbol=uploaded.json()["id"],
    )
    airframe = element("Airframe electronics", "Subsystem", "Everything that flies.", parent=drone["id"])
    fc = element(
        "Flight controller", "Board", "Runs the control loop and the failsafes.", parent=airframe["id"],
        ports=(("IMU bus", "both", "SPI"), ("GPS link", "in", "UART"), ("Telemetry link", "out", "UART")),
    )
    gps = element("GPS receiver", "Sensor", "Position and time.", parent=airframe["id"], ports=(("UART out", "out", "UART"),))
    imu = element("IMU", "Sensor", "Attitude and acceleration.", parent=airframe["id"], ports=(("SPI", "both", "SPI"),))
    radio = element(
        "Telemetry radio", "Board", "Link to the ground station.", parent=airframe["id"],
        ports=(("UART in", "in", "UART"), ("Downlink", "out", "Ethernet")),
    )
    ground = element("Ground station service", "Service", "Receives telemetry and sends missions.", parent=drone["id"],
                     ports=(("Telemetry API", "in", "REST API"),))
    connect("IMU samples", "SPI", imu, "SPI", fc, "IMU bus", "SPI mode 3, 8 MHz")
    connect("Position fixes", "UART", gps, "UART out", fc, "GPS link", "NMEA 0183, 115200 baud")
    connect("Telemetry out", "UART", fc, "Telemetry link", radio, "UART in", "MAVLink 2")
    connect("Telemetry upload", "REST API", radio, "Downlink", ground, "Telemetry API", "HTTPS, JSON")

    # An element the organisation owns, shared with Falcon-3 through a collection, and a connection to it.
    org_base = f"{BASE}/orgs/{org_id}/modules/architecture"
    org_types = {r["name"]: r["id"] for r in httpx.get(f"{org_base}/element-types", headers=headers, timeout=30).json()}
    identity = httpx.post(
        f"{org_base}/elements", headers=headers, timeout=30,
        json={"name": "Corporate identity service", "description": "Sign-in for every product.",
              "element_type_id": org_types["Service"], "activate": True},
    )
    identity.raise_for_status()
    collection = httpx.post(f"{org_base}/collections", headers=headers, timeout=30, json={"name": "Corporate services"})
    collection.raise_for_status()
    collection_url = f"{org_base}/collections/{collection.json()['id']}"
    httpx.post(
        f"{collection_url}/members", headers=headers, timeout=30, json={"element_ids": [identity.json()["id"]]},
    ).raise_for_status()
    httpx.post(f"{collection_url}/grants", headers=headers, timeout=30, json={"project_id": project_id}).raise_for_status()
    connect("Operator sign-in", "REST API", ground, "", identity.json(), "", "OpenID Connect")
    return {"elements": 8, "connections": 5}


def main() -> None:
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    h_admin = h(admin_token)

    existing_orgs = httpx.get(f"{BASE}/orgs", headers=h_admin, timeout=30).json()
    if any(o["name"] == ORG_NAME for o in existing_orgs):
        print(f"Demo dataset already seeded (found {ORG_NAME!r}). Exiting without changes.")
        return

    print(f"Creating organisation {ORG_NAME!r}...")
    org = create_org(h_admin, ORG_NAME)

    print("Creating demo personas...")
    demo_admin = create_org_user(h_admin, org["id"], "demo.admin@example.com", "Jordan Alvarez", "org_admin")
    demo_engineer = create_org_user(h_admin, org["id"], "demo.engineer@example.com", "Priya Natarajan", "member")
    demo_stakeholder = create_org_user(h_admin, org["id"], "demo.stakeholder@example.com", "Sam Whitfield", "member")

    h_pm = h(login("demo.admin@example.com", PASSWORD))

    print("Creating the organisation's stage workflows...")
    outsourced_workflow = create_org_workflow(h_pm, org["id"], "Outsourced work", [
        ("Scoping", "open"), ("Technical scoping", "open"), ("Review board", "review"), ("Tendering", "on_hold"),
        ("Awarded", "locked"), ("In progress", "locked"), ("Completion", "closed"),
    ])
    improvement_workflow = create_org_workflow(h_pm, org["id"], "Continuous improvement", [
        ("Scoping", "open"), ("Implementation ready", "locked"), ("Done", "closed"),
    ])

    print("Publishing the server policies...")
    publish_server_policy(h_admin, "privacy", "How personal data is handled", [
        "This is a demonstration service. It holds only the sample data in this organisation.",
        "Replace this text with the privacy policy of your own service before real use.",
    ])
    publish_server_policy(h_admin, "data", "How records are kept", [
        "Records are kept until a project administrator deletes them.",
        "Replace this text with the data policy of your own service before real use.",
    ])

    print("Publishing an organisation policy...")
    publish_org_policy(
        h_pm, org["id"], "Confidentiality agreement", [
            "Information in this organisation is shared for demonstration only.",
            "Replace this text with your own confidentiality agreement before real use.",
        ],
    )

    print("Posting an organisation message...")
    create_announcement(
        h_pm, org["id"], title="Demonstration data",
        body="Everything in this organisation is sample data; edit or delete it freely.",
    )

    print("Adding organisation dashboards...")
    create_org_dashboard(h_pm, org["id"], "Delivery", [
        {"id": "requirements", "type": "metric_tile", "width": 3, "height": 2, "config": {"metric": "org_requirement_count"}},
        {"id": "by-status", "type": "status_chart", "width": 4, "height": 5, "config": {"metric": "org_projects_by_status", "chart": "pie"}},
        {"id": "note", "type": "text", "width": 5, "height": 3, "config": {"markdown": "Delivery figures across every project."}},
    ])
    create_org_dashboard(h_pm, org["id"], "Engineering", [
        {
            "id": "records", "type": "metric_tile", "width": 3, "height": 2,
            "config": {"metric": "org_record_count", "params": {"record_type": "requirement"}},
        },
    ], viewer_user_ids=[demo_engineer["user_id"]])

    print("Setting the organisation's report look...")
    set_report_look(h_pm, org["id"], accent_color_hex="#0F62FE", footer_text="Solstice Robotics — Confidential")

    print("Setting organisation outgoing-email branding...")
    httpx.put(
        f"{BASE}/orgs/{org['id']}/branding",
        json={
            "accent_color_hex": None, "header_title": None,
            # The band behind the logo on the sign-in page and in email headers (the demo shows a chosen colour).
            "logo_band_color_hex": "#0B2545",
            # The sign-in page footer rests at the bottom of the window (the platform default is below the card).
            "footer_position": "bottom_of_page",
            "email_footer_company_name": "Solstice Robotics, Inc.",
            "email_footer_website": "https://solsticerobotics.example.com",
            "email_footer_address": "400 Aerodrome Way, Suite 210\nAustin, TX 78701",
        },
        headers=h_pm, timeout=30,
    ).raise_for_status()

    print("Adding a custom requirement link type...")
    # Beyond the 12 seeded defaults (C-G-09) — demonstrates that an
    # organisation can extend the link-type vocabulary with its own.
    # `flow` makes the artefact link graph read it as upstream (the superseded one is older), unlike a
    # custom type left at the default "none", which the graph shows as merely related.
    supersedes_link_type = create_link_type(
        h_pm, org["id"], forward_name="Supersedes", reverse_name="Is superseded by", flow="forward_is_upstream"
    )
    # A restricted type: only a requirement may start it and only an action may be its target, so the link
    # panel offers it just for that pair ("Can link from"/"Can link to" in Org Admin's Link types).
    create_link_type(
        h_pm, org["id"], forward_name="Is validated in simulation by", reverse_name="Validates in simulation",
        flow="forward_is_downstream", allowed_source_types=["requirement"], allowed_target_types=["requirement_action"],
    )
    default_link_types = {lt["forward_name"]: lt for lt in httpx.get(f"{BASE}/orgs/{org['id']}/link-types", headers=h_pm, timeout=30).json()}
    project_statuses = {s["name"]: s for s in httpx.get(f"{BASE}/orgs/{org['id']}/project-statuses", headers=h_pm, timeout=30).json()}

    print("Creating 'Falcon-3 Inspection Drone'...")
    drone = create_project(
        h_pm, org["id"], "Falcon-3 Inspection Drone",
        "Autonomous multirotor platform for utility and infrastructure visual inspection.",
        # Eligible to be a parent (docs/decisions.md): 'Falcon-3 Avionics
        # Subsystem' below is created as its child — a project must opt in
        # to this before another project can be attached under it.
        can_be_parent=True,
        # The short name the 'Project overview with logo' report prints in its footer.
        report_name="Falcon-3",
    )
    set_project_status(h_pm, drone["id"], project_statuses["Active"]["id"])
    # Demonstrates C-C-03's terminology overrides with aerospace-engineering
    # vocabulary that reads naturally for a hardware programme — "stage"
    # becomes "Phase", "requirement" becomes "Spec", and "change_request"
    # becomes "ECR" (Engineering Change Request), while "project"/
    # "component"/"category" are left at their English defaults on purpose,
    # so the demo also shows a *partial* override (not every one of the six
    # keys has to be set).
    set_project_terminology(h_pm, drone["id"], {"stage": "Phase", "requirement": "Spec", "change_request": "ECR"})
    # A renamed navigation entry (its name shows in the navigation and as the page title).
    set_project_nav_labels(h_pm, drone["id"], {"reviews-due": "Scheduled reviews"})
    # A configured overview: a gauge on how much is complete (warning below 50%, critical below 25%), a count of the
    # Avionics requirements named by component prefix, and a text note.
    add_overview_widgets(h_pm, drone["id"], [
        {
            "id": "demo-completion", "type": "gauge", "title": "Programme completion", "width": 3, "height": 4, "visible": True,
            "config": {
                "metric": "requirement_completed_percent", "minimum": 0, "maximum": 100, "warning": 50, "critical": 25,
                "direction": "below",
            },
        },
        {
            "id": "demo-avionics", "type": "metric_tile", "title": "Avionics specifications", "width": 3, "height": 2, "visible": True,
            "config": {"metric": "record_count", "params": {"record_type": "requirement", "filters": {"component": ["AV"]}}},
        },
        {
            "id": "demo-note", "type": "text", "title": "Reading this overview", "width": 6, "height": 3, "visible": True,
            "config": {"markdown": "Figures cover **this project only**. The gauge turns to a warning below 50% complete and to critical below 25%."},
        },
    ])
    assign_project_role(h_pm, drone["id"], demo_engineer["user_id"], "stakeholder")
    assign_project_role(h_pm, drone["id"], demo_stakeholder["user_id"], "stakeholder")
    drone_components = {
        "AF": create_component(h_pm, drone["id"], "Airframe", "AF"),
        "PR": create_component(h_pm, drone["id"], "Propulsion", "PR"),
        "AV": create_component(h_pm, drone["id"], "Avionics", "AV"),
        "FW": create_component(h_pm, drone["id"], "Firmware", "FW"),
    }
    # Nested under whichever component each actually appears with in
    # DRONE_REQUIREMENTS below — a real tree, not a project-wide flat list.
    drone_categories = create_categories_for_components(
        h_pm, drone["id"], drone_components,
        {"AV": ["PERF", "FN", "SAF"], "FW": ["SAF", "REG", "FN"], "PR": ["PERF"], "AF": ["FN"]},
    )
    create_custom_field(h_pm, drone["id"], "requirement", "Risk Level", "list", ["Low", "Medium", "High"])
    drone_design = create_stage(h_pm, drone["id"], "Detailed Design")
    drone_validation = create_stage(h_pm, drone["id"], "Verification & Validation", outsourced_workflow["id"])
    transition_stage(h_pm, drone["id"], drone_design["id"], "review")
    # Component phases: Airframe is already in review for the design stage, and the firmware has no
    # separate validation stage of its own (its checks run with the avionics).
    enable_component_phases(h_pm, drone["id"])
    move_component_track(h_pm, drone["id"], drone_components["AF"]["id"], drone_design["id"], "review")
    mark_component_track_not_applicable(h_pm, drone["id"], drone_components["FW"]["id"], drone_validation["id"])
    # Phase schedule: the design review has run past its expected end (an overdue reminder), the next phase starts
    # within the lead time (an upcoming reminder), Airframe's own review has a range, and the outsourced
    # validation stage is planned through tendering.
    today = date.today()
    schedule_phase(h_pm, drone["id"], drone_design["id"], "review", today - timedelta(days=14), today - timedelta(days=2))
    schedule_phase(h_pm, drone["id"], drone_design["id"], "approved", today + timedelta(days=3), today + timedelta(days=10))
    airframe = drone_components["AF"]["id"]
    schedule_phase(h_pm, drone["id"], drone_design["id"], "review", today - timedelta(days=7), today + timedelta(days=4), airframe)
    schedule_phase(h_pm, drone["id"], drone_validation["id"], "technical scoping", today, today + timedelta(days=14))
    schedule_phase(h_pm, drone["id"], drone_validation["id"], "tendering", today + timedelta(days=15), today + timedelta(days=45))

    print("Seeding Falcon-3 requirements...")
    drone_reqs = seed_project(h_pm, drone, drone_components, drone_categories, DRONE_REQUIREMENTS, demo_admin["user_id"])

    print("Archiving a descoped Falcon-3 requirement (demonstrates the 'Include archived' filter and Restore button)...")
    archive_requirement(h_pm, drone["id"], drone_reqs["Support geofencing with a configurable no-fly boundary"]["id"])

    print("Linking related Falcon-3 requirements (C-G-09)...")
    gps_req = drone_reqs["Acquire GPS position lock within 5 seconds of power-on in open-sky conditions"]
    return_to_home_req = drone_reqs["Autonomously return to launch point when battery charge falls below 15%"]
    preflight_req = drone_reqs["Complete pre-flight diagnostic checks in under 20 seconds"]
    remote_id_req = drone_reqs["Broadcast Part 107 remote identification per FAA requirements"]
    flight_log_req = drone_reqs["Log all flight-critical state transitions to onboard non-volatile storage"]
    create_requirement_link(h_pm, drone["id"], return_to_home_req["id"], gps_req["id"], default_link_types["Depends on"]["id"])
    create_requirement_link(h_pm, drone["id"], preflight_req["id"], gps_req["id"], default_link_types["Depends on"]["id"])
    create_requirement_link(h_pm, drone["id"], remote_id_req["id"], flight_log_req["id"], supersedes_link_type["id"])
    # Multi-hop chain for the artefact link graph: remote ID needs a position fix (depends on GPS), and the
    # return-to-home threshold derives from the flight-time requirement's margin (an upstream of an upstream
    # when read from GPS at depth 2).
    flight_time_req = drone_reqs["Provide a minimum flight time of 42 minutes at an 800g payload"]
    create_requirement_link(h_pm, drone["id"], remote_id_req["id"], gps_req["id"], default_link_types["Depends on"]["id"])
    create_requirement_link(h_pm, drone["id"], return_to_home_req["id"], flight_time_req["id"], default_link_types["Derives from"]["id"])

    print("Creating and linking requirement actions on Falcon-3 (review/test tasks)...")
    drone_action_types = {t["name"]: t for t in httpx.get(f"{BASE}/projects/{drone['id']}/action-types", headers=h_pm, timeout=30).json()}
    # `remote_id_req` is seeded directly into "complete" (DRONE_REQUIREMENTS,
    # above) — approved and marked completed (C-G-11), so already locked
    # (status stays APPROVED throughout), so adding an action to it goes
    # through an ADD_ACTION change request rather than the direct create-and-link call every other action
    # below still uses on its still-draft target requirement.
    firmware_review_title = "Review remote-ID firmware module against FAA rule text"
    firmware_review_cr = create_add_action_change_request(
        h_pm, drone["id"], remote_id_req["id"],
        action_title=firmware_review_title,
        action_description="Line-by-line review of the broadcast module against the published Part 107 remote "
        "identification rule, ahead of the compliance deadline.",
        action_type_id=drone_action_types["Review"]["id"],
        reason="Compliance deadline requires a documented review of the broadcast module, not just informal sign-off.",
        assignee={"type": "user", "id": demo_engineer["user_id"]},
    )
    submit_change_request(h_pm, drone["id"], firmware_review_cr["id"])
    decide_change_request(h_pm, drone["id"], firmware_review_cr["id"], approve=True,
                           note="Approved — compliance review, proceed.")
    firmware_review = next(
        a for a in httpx.get(f"{BASE}/projects/{drone['id']}/requirements/{remote_id_req['id']}/actions", headers=h_pm, timeout=30).json()
        if a["title"] == firmware_review_title
    )
    set_action_outcome(h_pm, drone["id"], firmware_review, "completed")
    add_action_comment(
        h_pm, drone["id"], firmware_review["id"],
        "Reviewed against the current rule text — one broadcast field was using the wrong units, fixed in "
        "firmware rev 2.3.1. No other gaps found.",
    )
    # Completed and signed off — archived to demonstrate the 'Include
    # archived' filter and Restore button on ActionDetailPage.
    archive_action(h_pm, drone["id"], firmware_review["id"])

    print("Attaching files across Falcon-3 (direct requirement attachment + action attachment)...")
    # `preflight_req`, not `remote_id_req` — `remote_id_req` is seeded
    # directly into "complete" (DRONE_REQUIREMENTS, above) and is
    # therefore locked from the moment it's created, so a *direct*
    # requirement-file upload against it always 409s ("must be added via a
    # change request", `routers/requirements.py`) — the same lock the
    # action-creation block immediately above this one already correctly
    # routes around via an ADD_ACTION change request. `preflight_req`
    # ("Complete pre-flight diagnostic checks...") is still `draft` at this
    # point in the script, so it accepts a direct attachment.
    upload_requirement_attachment(
        h_pm, drone["id"], preflight_req["id"], "preflight-diagnostic-checklist.txt",
        b"Standard pre-flight diagnostic checklist referenced by the 20-second timing requirement.",
    )
    upload_action_attachment(
        h_pm, drone["id"], firmware_review["id"], "firmware-2.3.1-compliance-signoff.pdf",
        b"%PDF-fake Compliance sign-off for firmware rev 2.3.1.",
    )
    # A picture in the project's own report image library, so the Files page shows a preview beside it.
    upload_report_image(h_pm, f"/projects/{drone['id']}", LOGO_PATH, "image/svg+xml")

    wind_test = create_and_link_action(
        h_pm, drone["id"], drone_reqs["Withstand sustained wind gusts of up to 45 km/h without loss of stability"]["id"],
        title="Wind tunnel stability test at 45 km/h sustained gust",
        description="Bench validation of airframe stability at the specified sustained gust threshold, "
        "ahead of the Verification & Validation stage.",
        action_type_id=drone_action_types["Test"]["id"], assignee={"type": "user", "id": demo_stakeholder["user_id"]},
        due_date=(date.today() + timedelta(days=3)).isoformat(),
    )
    set_action_outcome(h_pm, drone["id"], wind_test, "failed")
    add_action_comment(
        h_pm, drone["id"], wind_test["id"],
        "Observed noticeable yaw oscillation above 40 km/h in the current airframe revision — re-test "
        "required once the propulsion team's damping fix lands.",
    )
    # A single action shared across two requirements (its own project-scoped
    # identity, not owned by either one — see models.requirement_action).
    link_action(h_pm, drone["id"], preflight_req["id"], wind_test["id"])

    # Teams used by the group-parity demos below. Created (and the requirement edit made) before the Scoping
    # baseline because baselining approves every draft requirement, which locks it against direct edits.
    # A team can own a Decision (users-and-groups parity): the organisation group owns the OTA Decision further down.
    architecture_board = httpx.post(
        f"{BASE}/orgs/{org['id']}/groups", json={"name": "Architecture Board"}, headers=h_pm, timeout=30,
    )
    architecture_board.raise_for_status()
    for member in (demo_admin, demo_engineer):
        httpx.post(
            f"{BASE}/orgs/{org['id']}/groups/{architecture_board.json()['id']}/members",
            json={"user_id": member["user_id"]}, headers=h_pm, timeout=30,
        ).raise_for_status()
    verification_squad = httpx.post(f"{BASE}/projects/{drone['id']}/groups", json={"name": "Verification Squad"}, headers=h_pm, timeout=30)
    verification_squad.raise_for_status()
    httpx.post(
        f"{BASE}/projects/{drone['id']}/groups/{verification_squad.json()['id']}/members",
        json={"user_id": demo_engineer["user_id"]}, headers=h_pm, timeout=30,
    ).raise_for_status()
    # Core records can name a team too: the Architecture Board owns a draft requirement and the Verification Squad
    # reviews it (the squad also takes the wind-tunnel test, and the board a change request task, further down).
    set_requirement_status(
        h_pm, drone["id"], drone_reqs["Operate in ambient temperatures between -10C and 45C"], "draft",
        review_date=(date.today() + timedelta(days=21)).isoformat(),
        owner={"type": "org_group", "id": architecture_board.json()["id"]},
        reviewer={"type": "project_group", "id": verification_squad.json()["id"]},
    )

    print("Approving the Scoping stage baseline for Falcon-3...")
    scoping_stage = httpx.get(f"{BASE}/projects/{drone['id']}/stages", headers=h_pm, timeout=30).json()[0]
    transition_stage(h_pm, drone["id"], scoping_stage["id"], "review")
    transition_stage(h_pm, drone["id"], scoping_stage["id"], "approved")

    print("Discussing a requirement on Falcon-3...")
    flight_time_req = drone_reqs["Provide a minimum flight time of 42 minutes at an 800g payload"]
    flight_time_comment = add_requirement_comment(
        h(login("demo.engineer@example.com", PASSWORD)), drone["id"], flight_time_req["id"],
        "Bench tests with the new obstacle-avoidance sensor payload are showing ~38 minutes, not 42 — "
        "filing a change request to true this up rather than let the two drift apart silently.",
    )
    # Third of the three project-files origins (GET /projects/{id}/files,
    # ProjectFilesPage): a comment attachment, alongside the direct
    # requirement attachment and action attachment seeded above.
    upload_comment_attachment(
        h(login("demo.engineer@example.com", PASSWORD)), drone["id"], flight_time_req["id"], flight_time_comment["id"],
        "bench-test-telemetry.txt", b"Raw bench-test flight-time telemetry backing the ~38 minute reading.",
    )
    add_requirement_comment(
        h_pm, drone["id"], flight_time_req["id"],
        "Agreed — let's capture the sensor payload trade-off explicitly in the change request "
        "reasoning so it's traceable later.",
    )

    print("Opening a change request on Falcon-3...")
    drone_cr = create_change_request(
        h_pm, drone["id"], kind="modify_requirement", requirement_id=flight_time_req["id"],
        proposed_name="Provide a minimum flight time of 38 minutes at an 800g payload",
        proposed_reasoning=flight_time_req["reasoning"] + " Revised downward from 42 minutes to reflect "
        "the additional draw from the obstacle-avoidance sensor payload added in Rev B.",
        reason="Obstacle-avoidance sensor payload (added post-baseline) draws an additional ~4W, "
        "reducing achievable flight time in verified bench testing from 42 to 38 minutes.",
        component_id=drone_components["PR"]["id"], category_id=drone_categories["PR"]["PERF"]["id"],
        # The request also proposes three traceability links, merged only if the
        # approver ticks them. The third is made unmergeable below (linked directly after the request was made),
        # so the approval dialog also shows a link that "can no longer be merged" with its reason.
        proposed_links=[
            {"link_type_id": default_link_types["Related to"]["id"], "direction": "outgoing",
             "other_type": "requirement", "other_id": other["id"]}
            for other in (flight_log_req, gps_req, preflight_req)
        ],
    )
    create_artefact_link(
        h_pm, drone["id"], "requirement", flight_time_req["id"], link_type_id=default_link_types["Related to"]["id"],
        other_type="requirement", other_id=preflight_req["id"],
    )
    submit_change_request(h_pm, drone["id"], drone_cr["id"])
    add_cr_comment(h(login("demo.stakeholder@example.com", PASSWORD)), drone["id"], drone_cr["id"],
                    "38 minutes still clears every current route's return-to-home margin per the Q3 telemetry — no objection from the ops side.")
    cast_vote(h(login("demo.stakeholder@example.com", PASSWORD)), drone["id"], drone_cr["id"], "approve",
              "Confirmed against current route data.")
    drone_cr_task = create_cr_task(h_pm, drone["id"], drone_cr["id"], "Update the customer-facing spec sheet once approved.",
                                   assignee={"type": "user", "id": demo_engineer["user_id"]}, due_date=(date.today() + timedelta(days=7)).isoformat())

    print("Creating 'Falcon-3 Avionics Subsystem' as a sub-project of Falcon-3 (hierarchical projects)...")
    # Demonstrates both RBAC-cascade directions from the same small fixture
    # (see docs/decisions.md's "Hierarchical projects" entry): forward
    # (MIRROR_ALL — everyone with a role on Falcon-3 gets that same role
    # here too) and reverse (Falcon-3 consumes members from this sub-project,
    # so demo_engineer's *direct* PROJECT_MANAGER grant here also gives them
    # baseline read access on the parent, on top of their existing direct
    # stakeholder role there).
    avionics = create_project(
        h_pm, org["id"], "Falcon-3 Avionics Subsystem",
        "Sensor fusion, navigation, and onboard diagnostics for the Falcon-3 flight controller.",
        parent_project_id=drone["id"], role_inheritance_mode="mirror_all",
    )
    add_member_source(h_pm, drone["id"], avionics["id"])
    assign_project_role(h_pm, avionics["id"], demo_engineer["user_id"], "project_manager")
    print("Seeding custom report layouts: an organisation layout every project inherits, Falcon-3's own, and Avionics hiding the organisation's...")
    org_layout = create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Handover requirements", "Every requirement, grouped by component.",
        {**REQUIREMENTS_BY_COMPONENT_LAYOUT, "file_name": "{{project_code}}-{{report_title}}-{{generated_on}}"},
        folder="Handover/Requirements",
    )
    create_report_layout(
        h_pm, f"/projects/{drone['id']}", "Falcon-3 requirements", "Falcon-3's requirements by component.", REQUIREMENTS_BY_COMPONENT_LAYOUT,
    )
    hide_report_layout(h_pm, avionics["id"], org_layout["id"])
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Context overview", "Context & Strategy figures and tables, embedded as widgets.", CONTEXT_OVERVIEW_LAYOUT,
        folder="Handover",
    )
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Requirements by category (choose)",
        "Pick the categories when running it: one layout for any selection.", REQUIREMENTS_BY_CATEGORY_LAYOUT,
        folder="Handover/Requirements",
    )
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Pain points with pictures", "A table of Pain Points with the pictures attached to each.",
        PAIN_POINTS_WITH_PICTURES_LAYOUT,
    )
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Requirements handbook (with contents)",
        "Requirements by component, with a table of contents that links to each component.", REQUIREMENTS_HANDBOOK_LAYOUT,
        folder="Handover/Requirements",
    )
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Requirements by component and category",
        "A heading above each category's table that names its component and category.",
        REQUIREMENTS_BY_COMPONENT_AND_CATEGORY_LAYOUT, folder="Handover/Requirements",
    )
    design_formulae = create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Design formulae", "Equations in a text block and as blocks of their own.", DESIGN_FORMULAE_LAYOUT,
    )
    print("Leaving the Design formulae layout with a draft: unpublished work the designer opens on, with its notice...")
    save_report_layout_draft(
        h_pm, f"/orgs/{org['id']}", design_formulae,
        {**DESIGN_FORMULAE_LAYOUT, "nodes": [*DESIGN_FORMULAE_LAYOUT["nodes"], {"type": "heading", "text": "Margins of safety"}]},
    )
    print("Seeding a report with the logo on a shape (the white mark over an accent plate), and making sure the Project Workbook starter is there...")
    httpx.post(f"{BASE}/orgs/{org['id']}/report-layouts/starters", headers=h_pm, timeout=30).raise_for_status()
    logo = upload_report_image(h_pm, f"/orgs/{org['id']}", LOGO_PATH, "image/svg+xml")
    create_report_layout(
        h_pm, f"/orgs/{org['id']}", "Project overview with logo",
        "A cover banner (the logo on a plate in the report accent colour), the project name, a document-details table, "
        "its requirements and a review and control table.",
        with_snippets(
            h_pm, f"/orgs/{org['id']}", project_overview_with_logo_layout(logo["id"]),
            [("document-details", 4), ("document-control", None)],
        ),
        folder="Handover",
    )
    print("Seeding a saved report snippet: the by-component grouping, kept for the organisation to insert into other layouts...")
    create_report_snippet(
        h_pm, f"/orgs/{org['id']}", "Requirements by component", "A group of the requirements by component, each with a table.",
        REQUIREMENTS_BY_COMPONENT_LAYOUT, start=2,
    )
    print("Seeding a report pack: the requirements by category and by component handed over together, with a saved set...")
    handover = create_report_pack(
        h_pm, f"/orgs/{org['id']}", "Programme handover", "The requirements for an external team, as one zip.",
        {
            "schema_version": 1,
            "variables": [{
                "name": "categories", "type": "enum", "multiple": True, "label": "Categories",
                "source": {"record_type": "requirement", "field": "category"},
            }],
            "entries": [
                {"kind": "layout", "name": "Requirements by category (choose)", "format": "pdf", "filename": "requirements-by-category"},
                {"kind": "layout", "name": "Requirements by component", "format": "docx", "filename": "requirements-by-component"},
            ],
        },
        folder="Handover",
    )
    create_report_pack_set(h_pm, f"/orgs/{org['id']}", handover["id"], "Safety only", {"categories": ["Safety"]})
    avionics_components = {"SN": create_component(h_pm, avionics["id"], "Sensors", "SN")}
    avionics_categories = create_categories_for_components(h_pm, avionics["id"], avionics_components, {"SN": ["PERF", "SAF", "FN"]})
    avionics_reqs = seed_project(
        h_pm, avionics, avionics_components, avionics_categories, AVIONICS_REQUIREMENTS, demo_admin["user_id"]
    )

    print("Creating 'Solstice Cloud Platform'...")
    cloud = create_project(
        h_pm, org["id"], "Solstice Cloud Platform",
        "Fleet telemetry ingestion, live tracking, and reporting backend for the Falcon fleet.",
    )
    assign_project_role(h_pm, cloud["id"], demo_engineer["user_id"], "stakeholder")
    assign_project_role(h_pm, cloud["id"], demo_stakeholder["user_id"], "stakeholder")
    # Demonstrates the opt-in
    # "require a change request to add/remove links on approved
    # requirements" project setting (Project Admin settings), off a
    # project with no direct-link seeding of its own so there's no
    # ordering hazard with an earlier link created before this point.
    r = httpx.patch(
        f"{BASE}/projects/{cloud['id']}", json={"require_change_request_for_approved_links": True},
        headers=h_pm, timeout=30,
    )
    r.raise_for_status()

    print("Demonstrating the generalized cross-project RBAC mechanisms (docs/decisions.md) — Falcon-3 and Solstice"
          " Cloud Platform are unrelated projects (no parent/child relationship), unlike Falcon-3/Avionics above...")
    # Generalized member-source: Falcon-3 additionally consumes stakeholders
    # (only — mirror_role, not every role) from the unrelated Solstice Cloud
    # Platform project, so demo_stakeholder's real stakeholder role on Cloud
    # also reaches Falcon-3 without a second, duplicate direct grant there.
    add_member_source(h_pm, drone["id"], cloud["id"], mirror_mode="mirror_role", mirror_filter_role="stakeholder")
    # Project-referencing group: Solstice Cloud Platform gets its own
    # explicit "Stakeholders" group (no default group exists to reach by
    # name any more), defined as
    # "Falcon-3's own direct members" — the second cross-project mechanism,
    # reached from the group side rather than the project side.
    cloud_stakeholders_group = create_project_group(h_pm, cloud["id"], "Stakeholders", "stakeholder")
    add_project_group_source_reference(h_pm, cloud["id"], cloud_stakeholders_group["id"], drone["id"])

    cloud_components = {
        "API": create_component(h_pm, cloud["id"], "API", "API"),
        "DP": create_component(h_pm, cloud["id"], "Data Pipeline", "DP"),
        "WD": create_component(h_pm, cloud["id"], "Web Dashboard", "WD"),
    }
    cloud_categories = create_categories_for_components(
        h_pm, cloud["id"], cloud_components,
        {"API": ["SEC", "PERF", "REL"], "DP": ["PERF", "FN", "SEC"], "WD": ["FN", "SEC"]},
    )
    create_custom_field(h_pm, cloud["id"], "requirement", "Compliance Tag", "short_text")
    cloud_dev = create_stage(h_pm, cloud["id"], "Development")
    create_stage(h_pm, cloud["id"], "Hardening", improvement_workflow["id"])
    transition_stage(h_pm, cloud["id"], cloud_dev["id"], "review")

    print("Seeding Solstice Cloud Platform requirements...")
    cloud_reqs = seed_project(h_pm, cloud, cloud_components, cloud_categories, CLOUD_REQUIREMENTS, demo_admin["user_id"])

    print("Opening and approving a change request on Solstice Cloud Platform...")
    # A modify change request can only target an already-locked requirement
    # — already true here, since
    # this requirement's CLOUD_REQUIREMENTS spec sets its status to
    # "approved" directly (via `seed_project`/`set_requirement_status`), not
    # left as "draft".
    latency_req = cloud_reqs["Respond to authenticated read requests within 200ms at the 95th percentile under nominal load"]
    cloud_cr = create_change_request(
        h_pm, cloud["id"], kind="modify_requirement", requirement_id=latency_req["id"],
        proposed_name="Respond to authenticated read requests within 150ms at the 95th percentile under nominal load",
        proposed_reasoning=latency_req["reasoning"] + " Tightened from 200ms to 150ms to match the renegotiated enterprise SLA.",
        reason="Customer SLA renegotiation (Contract Amendment 4) commits to a tighter latency guarantee "
        "than the original requirement specified.",
        component_id=cloud_components["API"]["id"], category_id=cloud_categories["API"]["PERF"]["id"],
    )
    submit_change_request(h_pm, cloud["id"], cloud_cr["id"])
    decide_change_request(h_pm, cloud["id"], cloud_cr["id"], approve=True,
                           note="Approved — infra team confirmed headroom for the tighter target in the latest load test.")

    print("Proposing an action on the now-locked latency requirement (add-action change request)...")
    # Once a requirement is locked
    # (true for `latency_req` since the CR just above), adding an action to
    # it goes through an ADD_ACTION change request instead of the direct
    # create-and-link endpoint — `latency_req` is reused deliberately here
    # (not a fresh requirement) specifically to demonstrate the gate on an
    # already-locked one.
    cloud_action_types = {t["name"]: t for t in httpx.get(f"{BASE}/projects/{cloud['id']}/action-types", headers=h_pm, timeout=30).json()}
    latency_action_cr = create_add_action_change_request(
        h_pm, cloud["id"], latency_req["id"],
        action_title="Re-run the p95 latency benchmark against the tightened 150ms target",
        action_description="Confirm the renegotiated SLA is actually met under nominal load, not just "
        "theoretically achievable, before the next customer review.",
        action_type_id=cloud_action_types["Test"]["id"], reason="Need evidence against the tightened target "
        "before the next customer review, not just the infra team's headroom estimate.",
        assignee={"type": "user", "id": demo_engineer["user_id"]},
    )
    submit_change_request(h_pm, cloud["id"], latency_action_cr["id"])
    decide_change_request(h_pm, cloud["id"], latency_action_cr["id"], approve=True,
                           note="Approved — good idea to confirm with real numbers.")

    print("Opening a new-requirement change request on Solstice Cloud Platform...")
    audit_cr = create_change_request(
        h_pm, cloud["id"], kind="new_requirement", requirement_id=None,
        proposed_name="Provide audit logging of all administrative actions",
        proposed_reasoning="Administrative actions (role grants, SSO configuration, org settings changes) "
        "currently lack a dedicated, customer-visible audit trail distinct from internal system logs.",
        reason="Identified during the platform's SOC 2 readiness review as a gap against the access-control "
        "and change-management policies' audit-logging expectations.",
        component_id=cloud_components["API"]["id"], category_id=cloud_categories["API"]["SEC"]["id"],
    )
    submit_change_request(h_pm, cloud["id"], audit_cr["id"])

    print("Seeding Compliance Module data on Falcon-3 Inspection Drone...")
    # A standard built around the same Part 107/flight-logging regulatory
    # themes DRONE_REQUIREMENTS already narrates (remote_id_req, flight_log_req
    # above) — a compliance standard is a distinct, organisation-level
    # resource (§31: "A Compliance Standard is not a Project"), not another
    # requirement, but reusing the same narrative keeps the demo coherent.
    # "Document Review"/"Test" now ship as every organisation's default
    # compliance action types rather than needing to be created
    # here by hand — look them up instead of `create_compliance_action_type`,
    # mirroring how `drone_action_types`/`cloud_action_types` above already
    # look up the generic per-project defaults rather than recreating them.
    compliance_action_types = {
        t["name"]: t
        for t in httpx.get(f"{BASE}/orgs/{org['id']}/modules/compliance/action-types", headers=h_pm, timeout=30).json()
    }
    review_action_type = compliance_action_types["Document Review"]
    test_action_type = compliance_action_types["Test"]
    # A team can own a standard and be assigned its work (users-and-groups parity): an organisation group
    # owns ASA-1 and its annual review, and a project group takes the logging required action below.
    compliance_office = httpx.post(f"{BASE}/orgs/{org['id']}/groups", json={"name": "Compliance Office"}, headers=h_pm, timeout=30)
    compliance_office.raise_for_status()
    httpx.post(
        f"{BASE}/orgs/{org['id']}/groups/{compliance_office.json()['id']}/members",
        json={"user_id": demo_admin["user_id"]}, headers=h_pm, timeout=30,
    ).raise_for_status()
    airworthiness_standard = create_compliance_standard(
        h_pm, org["id"], reference="ASA-1", name="Aerospace Safety & Airworthiness Standard",
        description="Solstice's internal airworthiness and regulatory-compliance standard for commercial "
        "drone platforms, incorporating FAA Part 107 remote-ID obligations.",
        issuing_organisation="Solstice Compliance Board", owner={"type": "org_group", "id": compliance_office.json()["id"]},
        initial_version_label="1.0", initial_version_change_note="Initial release.",
    )
    airworthiness_version = list_compliance_versions(h_pm, org["id"], airworthiness_standard["id"])[0]
    remote_id_section = create_compliance_requirement(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        name="Remote Identification", reference="1",
        description="Requirements ensuring continued compliance with FAA Part 107 remote-ID obligations.",
    )
    remote_id_compliance_req = create_compliance_requirement(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        name="Broadcast Part 107 remote identification per FAA rule text", reference="1.1",
        reasoning="Non-negotiable for the fleet to remain airworthy past the compliance deadline.",
        parent_requirement_id=remote_id_section["id"],
    )
    remote_id_action = create_compliance_required_action(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        remote_id_compliance_req["id"], review_action_type["id"],
        name="Review broadcast module against FAA rule text",
        description="Line-by-line review of the broadcast module against the published rule text.",
    )
    logging_compliance_req = create_compliance_requirement(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        name="Flight Data Logging", reference="2",
        reasoning="Investigators expect a retrievable flight log independent of the telemetry uplink.",
    )
    create_compliance_required_action(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        logging_compliance_req["id"], test_action_type["id"],
        name="Verify flight log retrieval from non-volatile storage on the updated firmware",
    )
    # Demo_engineer also holds this standard's own `standards_
    # contributor` role — its own working-group grant, distinct from her
    # project-scoped `compliance_officer` grant below (demonstrated before
    # publishing, since a contributor may only edit a still-draft version).
    grant_standard_role(h_pm, org["id"], airworthiness_standard["id"], demo_engineer["user_id"], "standards_contributor")
    publish_compliance_version(h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"])
    # Demonstrate the always-editable version summary and a
    # post-publish clarification — both `standards_manager`-or-override
    # only (demo_admin, via her org admin override) once a version is no
    # longer a draft.
    update_compliance_version_summary(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"],
        "Current release; supersedes no earlier version. Remote-ID broadcast wording clarified post-publish.",
    )
    remote_id_compliance_req = clarify_compliance_requirement(
        h_pm, org["id"], airworthiness_standard["id"], airworthiness_version["id"], remote_id_compliance_req["id"],
        name="Broadcast Part 107 remote identification per the FAA rule text published in 14 CFR 89",
        reference=remote_id_compliance_req["reference"],
        reasoning=remote_id_compliance_req["reasoning"],
        clarification_note="Added the specific CFR citation for clarity; the underlying obligation is unchanged.",
    )

    drone_compliance = assign_compliance_standard(h_pm, org["id"], drone["id"], airworthiness_standard["id"], airworthiness_version["id"])
    grant_compliance_officer(h_pm, drone["id"], demo_engineer["user_id"])
    # The seeded "Link editor" preset (View + Link on every record type) lets Priya trace the Drone project's
    # records without being a manager.
    grant_custom_role(h_pm, org["id"], "Link editor", demo_engineer["user_id"], drone["id"])
    # A requirement traces to the standard clause it derives from as an ordinary link:
    # visible in the requirement's Links panel, found with the "Add a link" finder.
    create_artefact_link(
        h_pm, drone["id"], "requirement", remote_id_req["id"], link_type_id=default_link_types["Derives from"]["id"],
        other_type="compliance_requirement", other_id=remote_id_compliance_req["id"],
    )

    compliance_pcrs = list_compliance_requirements(h_pm, drone["id"], drone_compliance["id"])
    remote_id_pcr = next(p for p in compliance_pcrs if p["requirement_id"] == remote_id_compliance_req["id"])
    logging_pcr = next(p for p in compliance_pcrs if p["requirement_id"] == logging_compliance_req["id"])

    print("  Assessing and approving the remote-ID compliance requirement...")
    update_compliance_assessment(
        h_pm, drone["id"], drone_compliance["id"], remote_id_pcr["id"], compliance_status="compliant",
        notes="Verified against current rule text in firmware rev 2.3.1 (see the linked action review).",
    )
    submit_compliance_for_approval(h_pm, drone["id"], drone_compliance["id"], remote_id_pcr["id"])
    approve_compliance_requirement(
        h_pm, drone["id"], drone_compliance["id"], remote_id_pcr["id"],
        note="Verified against FAA rule text; approved for continued operation.",
    )
    remote_id_assessments = list_required_action_assessments(h_pm, drone["id"], drone_compliance["id"], remote_id_pcr["id"])
    remote_id_assessment = next(a for a in remote_id_assessments if a["required_action_id"] == remote_id_action["id"])
    complete_required_action_assessment(h_pm, drone["id"], drone_compliance["id"], remote_id_pcr["id"], remote_id_assessment["id"])

    print("  Flagging the flight-data-logging requirement Non-Compliant (outstanding action, demonstrates the gap)...")
    update_compliance_assessment(
        h_pm, drone["id"], drone_compliance["id"], logging_pcr["id"], compliance_status="non_compliant",
        justification="New logging firmware not yet verified to retain logs across a hard power cycle.",
    )
    logging_assessments = list_required_action_assessments(h_pm, drone["id"], drone_compliance["id"], logging_pcr["id"])
    logging_assessment = logging_assessments[0]
    update_required_action_assessment(
        h_pm, drone["id"], drone_compliance["id"], logging_pcr["id"], logging_assessment["id"],
        assignee={"type": "project_group", "id": verification_squad.json()["id"]},
        due_date=(date.today() + timedelta(days=14)).isoformat(), notes="Blocked on the new logging firmware build.",
    )

    print("  Attaching compliance evidence and scheduling the annual review...")
    create_compliance_evidence(
        h_pm, drone["id"], title="Firmware 2.3.1 Remote-ID Review Report",
        issuing_organisation="Solstice Compliance Team", issued_date=date.today().isoformat(),
        expiry_date=(date.today() + timedelta(days=300)).isoformat(),
        notes="Supports the remote-ID requirement's compliant assessment above.",
        pcr_ids=[remote_id_pcr["id"]], assessment_ids=[remote_id_assessment["id"]],
    )
    create_compliance_review(
        h_pm, drone["id"], drone_compliance["id"], frequency_label="Annual", recurrence_days=365,
        next_due_date=(date.today() + timedelta(days=330)).isoformat(),
        owner={"type": "org_group", "id": compliance_office.json()["id"]},
        notes="Annual review of continued Part 107 remote-ID compliance.",
    )

    print("Seeding default reference standards — EN 60529 and ISO/IEC 27001...")
    # Realistic *labels* for demo purposes only, built around each real
    # standard's own public section structure (IEC 60529's IP-Code digits,
    # ISO 27001's Annex A control domains) — not a reproduction of either
    # standard's actual copyrighted requirement text, mirroring how ASA-1
    # above is already clearly an invented internal standard, not a real
    # regulation.
    ip_rating_standard = create_compliance_standard(
        h_pm, org["id"], reference="EN 60529", name="EN 60529 — Degrees of Protection Provided by Enclosures (IP Code)",
        description="Solstice's internal reference standard for enclosure ingress-protection ratings on "
        "outdoor-operated hardware, based on the IEC/EN 60529 IP Code structure.",
        issuing_organisation="International Electrotechnical Commission (IEC)", owner={"type": "user", "id": demo_admin["user_id"]},
        initial_version_label="1.0", initial_version_change_note="Initial release.",
    )
    ip_rating_version = list_compliance_versions(h_pm, org["id"], ip_rating_standard["id"])[0]
    solids_section = create_compliance_requirement(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        name="First Digit — Protection Against Solid Objects", reference="1",
        description="Requirements covering the IP Code's first (solid-particle ingress) digit.",
    )
    dust_req = create_compliance_requirement(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        name="Achieve a minimum ingress rating of IP5X (dust-protected) for the primary electronics enclosure",
        reference="1.1", reasoning="Coastal and desert inspection sites expose the airframe to fine dust and sand; "
        "a dust-protected primary enclosure prevents particulate ingress into flight-critical electronics between "
        "scheduled maintenance.", parent_requirement_id=solids_section["id"],
    )
    create_compliance_required_action(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"], dust_req["id"], test_action_type["id"],
        name="Dust-chamber ingress test at IP5X",
        description="Bench validation of the primary electronics enclosure in a dust chamber against the IP5X threshold.",
    )
    liquids_section = create_compliance_requirement(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        name="Second Digit — Protection Against Water", reference="2",
        description="Requirements covering the IP Code's second (liquid ingress) digit.",
    )
    splash_req = create_compliance_requirement(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        name="Achieve a minimum ingress rating of IPX4 (splashing water) for the primary electronics enclosure",
        reference="2.1", reasoning="Several contracted inspection sites operate in light rain conditions; IPX4 "
        "keeps the airframe airworthy through a typical shift without grounding for weather.",
        parent_requirement_id=liquids_section["id"],
    )
    create_compliance_required_action(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"], splash_req["id"], review_action_type["id"],
        name="Review enclosure seal design against the IPX4 test method",
    )
    create_compliance_requirement(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        name="Achieve an IPX6K rating for connectors exposed during post-flight rinse-down maintenance",
        reference="2.2", reasoning="Field crews rinse airframes with a pressure washer after dusty sites; "
        "connectors not rated for powerful water jets have been a recurring source of post-maintenance "
        "electrical faults.", parent_requirement_id=liquids_section["id"],
    )
    publish_compliance_version(h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"])
    # An edited, always-editable version summary on the first
    # published version.
    update_compliance_version_summary(
        h_pm, org["id"], ip_rating_standard["id"], ip_rating_version["id"],
        "Current release, based on the IEC/EN 60529 IP Code structure. Description clarified post-publish to "
        "note this standard covers the primary electronics enclosure and exposed connectors only, not the "
        "full airframe.",
    )

    infosec_standard = create_compliance_standard(
        h_pm, org["id"], reference="ISO/IEC 27001", name="ISO/IEC 27001 — Information Security Management System",
        description="Solstice's internal reference standard for information-security management controls, "
        "based on the ISO/IEC 27001 Annex A control-domain structure.",
        issuing_organisation="International Organization for Standardization (ISO)", owner={"type": "user", "id": demo_admin["user_id"]},
        initial_version_label="1.0", initial_version_change_note="Initial release.",
    )
    infosec_version = list_compliance_versions(h_pm, org["id"], infosec_standard["id"])[0]
    org_controls_section = create_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"],
        name="Annex A.5 — Organizational Controls", reference="A.5",
        description="Requirements covering Annex A's organizational-control domain.",
    )
    create_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"],
        name="Maintain a documented information security policy approved by senior management", reference="A.5.1",
        reasoning="A policy without documented senior-management approval carries no organisational weight when "
        "it conflicts with a delivery deadline — approval is what makes it enforceable.",
        parent_requirement_id=org_controls_section["id"],
    )
    tech_controls_section = create_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"],
        name="Annex A.8 — Technology Controls", reference="A.8",
        description="Requirements covering Annex A's technology-control domain.",
    )
    mfa_req = create_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"],
        name="Enforce multi-factor authentication for all privileged system access", reference="A.8.5",
        reasoning="Account takeover of a privileged account was the top risk flagged in the most recent "
        "customer security review of the platform.", parent_requirement_id=tech_controls_section["id"],
    )
    create_compliance_required_action(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"], mfa_req["id"], test_action_type["id"],
        name="Verify MFA enforcement against every privileged role in the production identity provider",
    )
    encryption_req = create_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"],
        name="Encrypt sensitive data at rest and in transit", reference="A.8.24",
        reasoning="Flight telemetry can reveal customer site layouts and operating patterns; encryption at rest "
        "and in transit is a standing commitment in the current data processing addendum template.",
        parent_requirement_id=tech_controls_section["id"],
    )
    create_compliance_required_action(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"], encryption_req["id"], review_action_type["id"],
        name="Review current encryption configuration against the data processing addendum",
    )
    publish_compliance_version(h_pm, org["id"], infosec_standard["id"], infosec_version["id"])
    # A post-publish clarification on an already-published
    # requirement.
    clarify_compliance_requirement(
        h_pm, org["id"], infosec_standard["id"], infosec_version["id"], mfa_req["id"],
        name="Enforce multi-factor authentication for all privileged system access, including break-glass accounts",
        reference=mfa_req["reference"], reasoning=mfa_req["reasoning"],
        clarification_note="Clarified to explicitly include break-glass/emergency-access accounts, which were "
        "ambiguous under the original wording; the underlying obligation is unchanged.",
    )
    # Exclude the avionics sub-project *before* flipping the
    # standard to apply to all projects, so reconciliation skips it from
    # the start rather than assigning and then re-archiving it.
    exclude_project_from_standard_default(
        h_pm, org["id"], infosec_standard["id"], avionics["id"],
        reason="Internal avionics subsystem project with no independent customer data handling or external "
        "network access; covered under the parent Falcon-3 project's own ISO/IEC 27001 assessment instead.",
    )
    update_standard_applicability_default(h_pm, org["id"], infosec_standard["id"], "applies_to_all_projects")

    print("Seeding Decision Management — enabling the module, then a superseded pair on Falcon-3...")
    # default_enabled=False — an org must opt in explicitly, same as a real admin would
    # from Org Admin's Modules tab.
    enable_module(h_pm, org["id"], "decisions")
    # The Decision register is only a known report once the module is on for the organisation.
    print("Arranging the Reports list: the organisation files the Decision register under Governance/Decisions...")
    r = httpx.put(
        f"{BASE}/orgs/{org['id']}/report-placements", json={"report_key": "report:decisions.d1", "folder": "Governance/Decisions"},
        headers=h_pm, timeout=30,
    )
    r.raise_for_status()
    drone_decision_types = list_decision_types(h_pm, drone["id"])
    set_action_outcome(h_pm, drone["id"], {**wind_test, "assignee": {"type": "project_group", "id": verification_squad.json()["id"]}}, "failed")
    httpx.patch(
        f"{BASE}/projects/{drone['id']}/change-requests/{drone_cr['id']}/tasks/{drone_cr_task['id']}",
        json={"assignee": {"type": "org_group", "id": architecture_board.json()["id"]}}, headers=h_pm, timeout=30,
    ).raise_for_status()
    httpx.post(
        f"{BASE}/projects/{drone['id']}/requirements/{preflight_req['id']}/watchers",
        json={"group": {"type": "org_group", "id": architecture_board.json()["id"]}}, headers=h_pm, timeout=30,
    ).raise_for_status()
    single_fc_decision = create_decision(
        h_pm, drone["id"], title="Use a single flight controller with hot-swap failover",
        decision_statement="Falcon-3 will ship with one primary flight controller board and a cold-spare"
        " swapped in by ground crew between flights, rather than dual-redundant boards flying together.",
        decision_type_id=drone_decision_types["Architecture"]["id"], owner_id=demo_admin["user_id"],
        decision_maker_id=demo_admin["user_id"], decision_date=(date.today() - timedelta(days=75)).isoformat(),
        context="Early Falcon-3 prototypes carried a single flight controller with no in-flight redundancy.",
        options_considered="(1) Single controller, cold-spare swapped between flights. (2) Dual-redundant"
        " controllers flying together with in-flight failover.",
        chosen_option="Option 1 — single controller with a cold-spare.",
        rationale="Dual-redundant hardware wasn't available within the initial flight-test budget or"
        " schedule; a cold-spare gets most of the reliability benefit for ground-based utility inspection"
        " flights, where an in-flight failure can safely abort to a landing.",
        consequences="Loses in-flight recovery from a controller failure; acceptable for the initial"
        " operating envelope but revisit once flights move over populated areas.",
    )
    propose_and_approve_decision(
        h_pm, drone["id"], single_fc_decision["id"],
        approval_comment="Approved for the initial flight-test campaign; revisit before BVLOS operations.",
    )
    dual_fc_decision = create_decision(
        h_pm, drone["id"], title="Adopt dual-redundant flight controller architecture for Falcon-3",
        decision_statement="Falcon-3 will fly with two flight controller boards in an active/standby"
        " arrangement, with automatic in-flight failover, superseding the earlier single-controller design.",
        decision_type_id=drone_decision_types["Architecture"]["id"], owner_id=demo_engineer["user_id"],
        decision_maker_id=demo_admin["user_id"], decision_date=(date.today() - timedelta(days=12)).isoformat(),
        context="Planned operations now include inspection routes over populated infrastructure corridors,"
        " where a single controller failure could mean an uncontrolled descent rather than a safe abort.",
        options_considered="(1) Keep the single-controller/cold-spare design. (2) Dual-redundant controllers"
        " with automatic failover. (3) Triple modular redundancy.",
        chosen_option="Option 2 — dual-redundant with automatic failover.",
        rationale="Matches the reliability bar for flight over populated areas without the cost/weight"
        " penalty of full triple modular redundancy, which the airframe's payload budget can't absorb.",
        consequences="Adds airframe weight and BOM cost per unit; avionics firmware needs an active/standby"
        " handover path that didn't exist before (tracked as its own firmware requirement).",
    )
    propose_and_approve_decision(
        h_pm, drone["id"], dual_fc_decision["id"],
        approval_comment="Approved ahead of the populated-corridor inspection contract; supersedes the"
        " single-controller decision.",
    )
    create_decision_supersession(h_pm, drone["id"], dual_fc_decision["id"], single_fc_decision["id"])
    print("  Leaving a third Decision in Draft (undecided) — demonstrates the list's mixed-status filtering...")
    create_decision(
        h_pm, drone["id"], title="Migrate firmware OTA update channel to signed images",
        decision_statement="Not yet decided — evaluating whether to require cryptographically signed"
        " firmware images for over-the-air updates before the next fleet-wide rollout.",
        decision_type_id=drone_decision_types["Engineering"]["id"], owner_group_id=architecture_board.json()["id"],
        context="Current OTA channel accepts unsigned images verified only by a checksum, adequate for an"
        " internal test fleet but not for a customer-operated one.",
    )
    print("  Two Decisions waiting for a verdict (one with no decision maker) — feeds the Approval ageing report...")
    modem_decision = create_decision(
        h_pm, drone["id"], title="Select the cellular modem vendor for Falcon-3 telemetry",
        decision_statement="Falcon-3 will standardise on one cellular modem vendor for its telemetry uplink.",
        decision_type_id=drone_decision_types["Engineering"]["id"], owner_id=demo_engineer["user_id"],
        context="Two vendors are qualified; field trials finished last month.",
    )
    advance_decision_to_review(h_pm, drone["id"], modem_decision["id"])
    gimbal_decision = create_decision(
        h_pm, drone["id"], title="Adopt a 3-axis gimbal as the standard inspection payload mount",
        decision_statement="Falcon-3 inspection payloads will mount on a 3-axis gimbal.",
        decision_type_id=drone_decision_types["Design"]["id"], owner_id=demo_engineer["user_id"],
        decision_maker_id=demo_admin["user_id"],
    )
    advance_decision_to_review(h_pm, drone["id"], gimbal_decision["id"], submit_for_review=False)

    print("Seeding Context & Strategy — enabling the module, then an org Strategy and a project Strategy...")
    # default_enabled=False — an org must opt in explicitly, same as Decision Management above.
    enable_module(h_pm, org["id"], "context_strategy")
    org_strategy = create_org_strategy(
        h_pm, org["id"], title="Lead the market in autonomous aerial inspection",
        objective="Become the preferred aerial-inspection platform for critical infrastructure operators.",
        current_state="A capable but early-stage entrant with two live product lines and a small install base.",
        desired_future_state="The default choice for utility/infrastructure operators evaluating autonomous"
        " inspection within three years.",
        rationale="Infrastructure operators are moving from manual to autonomous inspection faster than"
        " expected; being the default choice compounds through data/training-set advantages over time.",
        expected_outcomes="Majority market share among utility-scale inspection contracts within three years.",
        constraints="Regulatory approval timelines for BVLOS operations vary significantly by jurisdiction.",
        measures_of_success="Contracted inspection routes under management; win rate on competitive RFPs.",
        priority="high", time_horizon="long_term",
    )
    propose_and_approve_org_strategy(
        h_pm, org["id"], org_strategy["id"],
        approval_comment="Approved at the organisation's strategy review; supersedes no prior strategy.",
    )
    drone_strategy = create_project_strategy(
        h_pm, drone["id"], title="Falcon-3: win the populated-corridor inspection contract",
        objective="Deliver a dual-redundant inspection platform certified for flight over populated"
        " infrastructure corridors.",
        current_state="Single-controller platform flying test routes over unpopulated terrain only.",
        desired_future_state="Dual-redundant platform certified and contracted for populated-corridor routes.",
        rationale="Directly implements the organisation's Strategy above — populated-corridor contracts are"
        " the largest near-term source of the market share that Strategy targets.",
        expected_outcomes="Signed populated-corridor inspection contract within the next fiscal year.",
        constraints="Airframe payload budget limits redundancy to dual, not triple, modular redundancy.",
        measures_of_success="Certification sign-off date; contract value signed.",
        priority="high", time_horizon="medium_term",
    )
    propose_and_approve_project_strategy(
        h_pm, drone["id"], drone_strategy["id"],
        approval_comment="Approved — directly traces to the dual-redundant flight controller Decision above.",
    )

    print("Seeding Future State — an org Future State and a project Future State, each linked"
          " to the Strategy it elaborates via a real 'Defines' relationship...")
    org_future_state = create_org_future_state(
        h_pm, org["id"], title="Default choice for utility-scale autonomous inspection",
        current_state="A capable but early-stage entrant with two live product lines and a small install base.",
        desired_state="The default choice for utility/infrastructure operators evaluating autonomous inspection,"
        " with the majority of contracted inspection routes under management across the sector.",
        target_date="2029-06-30",
        outcomes="Majority market share among utility-scale inspection contracts; the organisation's autonomous"
        " inspection data/training-set advantage compounds faster than any single competitor can close it.",
        success_measures="Contracted inspection routes under management; win rate on competitive RFPs; unaided"
        " brand recall among utility-scale procurement teams.",
        constraints="Regulatory approval timelines for BVLOS operations vary significantly by jurisdiction and"
        " cannot be accelerated unilaterally.",
        assumptions="Utility/infrastructure operators continue migrating from manual to autonomous inspection at"
        " roughly the current pace, rather than stalling on regulatory uncertainty.",
    )
    propose_and_approve_org_future_state(
        h_pm, org["id"], org_future_state["id"],
        approval_comment="Approved at the organisation's strategy review, alongside the Strategy it elaborates.",
    )
    drone_future_state = create_project_future_state(
        h_pm, drone["id"], title="Falcon-3 certified and contracted for populated-corridor routes",
        current_state="Single-controller platform flying test routes over unpopulated terrain only.",
        desired_state="Dual-redundant Falcon-3 platform certified for flight over populated infrastructure"
        " corridors, with a signed populated-corridor inspection contract in place.",
        target_date="2027-09-30",
        outcomes="Signed populated-corridor inspection contract; certification sign-off enabling further"
        " populated-corridor contracts without re-certifying the airframe.",
        success_measures="Certification sign-off date; contract value signed; number of populated-corridor routes"
        " flown without incident in the first two quarters post-certification.",
        constraints="Airframe payload budget limits redundancy to dual, not triple, modular redundancy.",
        assumptions="The dual-redundant flight controller Decision above is not itself superseded again before"
        " certification testing completes.",
    )
    propose_and_approve_project_future_state(
        h_pm, drone["id"], drone_future_state["id"],
        approval_comment="Approved — this is the future state the dual-redundant flight controller Decision and"
        " the Falcon-3 Strategy above are both driving toward.",
    )
    # A Draft Future State whose target date has already passed and which names no success measures, so the
    # roadmap report (R5) demonstrates both of its gap lists.
    create_project_future_state(
        h_pm, drone["id"], title="Falcon-3 type-certified in the home market",
        current_state="Certification test campaign planned but not yet scheduled with the regulator.",
        desired_state="Falcon-3 holds a home-market type certificate covering the single-controller airframe.",
        target_date=(date.today() - timedelta(days=45)).isoformat(),
    )
    create_org_strategy_relationship(
        h_pm, org["id"], org_strategy["id"], kind="defines_future_state", target_id=org_future_state["id"],
    )
    create_project_strategy_relationship(
        h_pm, drone["id"], drone_strategy["id"], kind="defines_future_state", target_id=drone_future_state["id"],
    )
    create_project_strategy_relationship(
        h_pm, drone["id"], drone_strategy["id"], kind="drives_requirement", target_id=remote_id_req["id"],
    )

    print("Seeding Pain Points — one per branch outcome (Accepted->Addressed, Rejected,"
          " Duplicate) on the Falcon-3 project, using the org's default Market/User/Operator types...")
    # `default_enabled` sub-components mean no
    # separate enable-subcomponent call is needed beyond the whole-module
    # `enable_module` call already made above for Strategy/Future State.
    drone_pain_point_types = list_effective_pain_point_types(h_pm, drone["id"])
    set_pain_point_type_definitions(h_pm, org["id"], drone_pain_point_types, PAIN_POINT_TYPE_DEFINITIONS)
    drone_pain_point_types = list_effective_pain_point_types(h_pm, drone["id"])
    pp_accepted = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["Operator"]["id"],
        title="Field inspectors re-key paper reports days after each flight",
        description="Inspection reports are recorded on paper in the field, then manually re-keyed into the"
        " reporting system by an office administrator, often 2-3 days after the flight itself.",
        source="Ops incident report — Q3 field review", impact="SLA-breach risk on every populated-corridor"
        " contract; re-keying also introduces transcription errors into the compliance record.",
        evidence="14 SLA-breach support tickets in the last quarter, all citing report delay as root cause.",
        priority="high", date_identified="2026-08-15",
    )
    # A team can own a Pain Point (users-and-groups parity): a project group, since a Pain Point is project-scoped.
    field_ops = httpx.post(f"{BASE}/projects/{drone['id']}/groups", json={"name": "Field Operations Squad"}, headers=h_pm, timeout=30)
    field_ops.raise_for_status()
    httpx.post(
        f"{BASE}/projects/{drone['id']}/groups/{field_ops.json()['id']}/members",
        json={"user_id": demo_engineer["user_id"]}, headers=h_pm, timeout=30,
    ).raise_for_status()
    assign_owner(
        h_pm, drone["id"], "pain-points", pp_accepted,
        ("pain_point_type_id", "title", "description", "source", "impact", "evidence", "priority", "date_identified", "is_intentional"),
        {"type": "project_group", "id": field_ops.json()["id"]},
    )
    triage_pain_point(h_pm, drone["id"], pp_accepted["id"])
    accept_pain_point(h_pm, drone["id"], pp_accepted["id"])
    address_pain_point(h_pm, drone["id"], pp_accepted["id"])
    print(f"  Accepted -> Addressed: {pp_accepted['title']!r}")

    pp_rejected = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["Market"]["id"],
        title="Competitor offers a lower-cost single-controller platform for unpopulated-corridor routes",
        description="A competitor's cheaper, single-controller platform has started winning unpopulated-corridor"
        " inspection contracts on price alone.",
        source="Customer interview — lost-deal debrief", impact="Some unpopulated-corridor deals lost on price.",
        evidence="Two lost-deal debriefs citing price as the deciding factor.",
        priority="low", date_identified="2026-07-20",
    )
    triage_pain_point(h_pm, drone["id"], pp_rejected["id"])
    reject_pain_point(
        h_pm, drone["id"], pp_rejected["id"],
        comment="Out of scope — Falcon-3's own strategy explicitly targets populated-corridor contracts, where"
        " dual-redundancy is a certification requirement competitors can't easily match on price alone.",
    )
    create_project_pain_point_relationship(
        h_pm, drone["id"], pp_rejected["id"], kind="drives_strategy", target_id=drone_strategy["id"],
    )
    print(f"  Rejected: {pp_rejected['title']!r} (real 'Drives' relationship to the Falcon-3 Strategy, not just the"
          " rejection comment's own prose)")

    pp_duplicate = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["Operator"]["id"],
        title="Field reports are delayed reaching the compliance record",
        description="Same underlying delay as the paper re-keying Pain Point above, reported separately by a"
        " different operator team before the two reports were compared.",
        source="Support ticket #492", impact="Duplicate of the accepted paper-re-keying Pain Point above.",
        evidence="Support ticket #492.", priority="medium", date_identified="2026-08-18",
    )
    triage_pain_point(h_pm, drone["id"], pp_duplicate["id"])
    mark_pain_point_duplicate(
        h_pm, drone["id"], pp_duplicate["id"],
        comment=f"Duplicate of {pp_accepted['title']!r} (id {pp_accepted['id']}) — same root cause, reported"
        " independently by a different operator team.",
    )
    create_project_pain_point_relationship(
        h_pm, drone["id"], pp_duplicate["id"], kind="duplicate_of", target_id=pp_accepted["id"],
    )
    print(f"  Duplicate: {pp_duplicate['title']!r} (real 'Duplicate of' relationship to the canonical Pain Point,"
          " not just the mandatory comment's own prose)")

    print("Linking a Pain Point -> Decision -> Requirement chain on Falcon-3 through the generic link endpoint...")
    # Decision-to-Pain-Point links have no per-module endpoint: the org's seeded "Addresses" type (Decision ->
    # Pain point) is used from the Pain Point's side, and the core "Implements" type from the Requirement's
    # side, so the chain can be authored (and read as a graph) from any of the three pages.
    chain_link_types = {lt["forward_name"]: lt for lt in httpx.get(f"{BASE}/orgs/{org['id']}/link-types", headers=h_pm, timeout=30).json()}
    create_artefact_link(
        h_pm, drone["id"], "pain_point", pp_accepted["id"], link_type_id=chain_link_types["Addresses"]["id"],
        other_type="decision", other_id=single_fc_decision["id"], direction="incoming",
    )
    create_artefact_link(
        h_pm, drone["id"], "requirement", gps_req["id"], link_type_id=chain_link_types["Implements"]["id"],
        other_type="decision", other_id=single_fc_decision["id"], direction="incoming",
    )

    print("Linking across Falcon-3 and its Avionics sub-project: the parent's dual-redundant Decision"
          " 'Implements' an Avionics requirement, and an Avionics Decision 'Addresses' the parent's Pain Point"
          " (the seeded 'Addresses' type keeps the upstream Pain Point in the same or a parent project)...")
    avionics_requirement = next(iter(avionics_reqs.values()))
    create_artefact_link(
        h_pm, drone["id"], "decision", dual_fc_decision["id"], link_type_id=chain_link_types["Implements"]["id"],
        other_type="requirement", other_id=avionics_requirement["id"], other_project_id=avionics["id"],
    )
    avionics_decision = create_decision(
        h_pm, avionics["id"], title="Fuse IMU and GPS with a dual-redundant estimator",
        decision_statement="Avionics will run two independent sensor-fusion estimators and vote on their output.",
        decision_type_id=drone_decision_types["Architecture"]["id"], owner_id=demo_engineer["user_id"],
        context="Sub-project-level consequence of the Falcon-3 dual-redundancy decision.",
    )
    create_artefact_link(
        h_pm, avionics["id"], "decision", avionics_decision["id"], link_type_id=chain_link_types["Addresses"]["id"],
        other_type="pain_point", other_id=pp_accepted["id"], other_project_id=drone["id"],
    )

    print("Seeding a project-level link type on Falcon-3: \"Is verified by\" (a requirement is verified by"
          " another), inherited by the Avionics sub-project, and Falcon-3 hides the organisation's"
          " \"Equivalent to\" (not \"Mitigates\": Risk treatment links need it)...")
    verified_by = create_project_link_type(
        h_pm, drone["id"], forward_name="Is verified by", reverse_name="Verifies", flow="forward_is_downstream",
    )
    create_artefact_link(
        h_pm, drone["id"], "requirement", gps_req["id"], link_type_id=verified_by["id"],
        other_type="requirement", other_id=flight_time_req["id"],
    )
    set_link_type_visibility(h_pm, drone["id"], chain_link_types["Equivalent to"]["id"], True)

    print("Seeding Pain Point scoring config — org keeps the seeded Severity/Frequency/"
          "Confidence levels and module-default model; Falcon-3 overrides its default model to S×F...")
    set_project_scoring_default_model(h_pm, drone["id"], "pain_point", "sxf")

    print("Seeding Guiding Principles — an org Guiding Principle and a project Guiding"
          " Principle, both walked to Active and linked to the Strategy they support...")
    # `default_enabled` sub-components mean no
    # separate enable-subcomponent call is needed beyond the whole-module
    # `enable_module` call already made above for Strategy/Future State/Pain Point.
    org_guiding_principle = create_org_guiding_principle(
        h_pm, org["id"], name="Operate safely under degraded connectivity",
        principle_statement="Every product must keep operating safely, with a clear degraded-mode indicator to"
        " the operator, when connectivity back to fleet/cloud services is lost.",
        rationale="Utility/infrastructure inspection sites the organisation's Strategy above targets frequently"
        " have unreliable or absent network coverage; a platform that fails unsafely offline cannot win"
        " populated-corridor contracts regardless of its certification status.",
        priority="high", owner={"type": "org_group", "id": architecture_board.json()["id"]},
    )
    propose_and_approve_org_guiding_principle(
        h_pm, org["id"], org_guiding_principle["id"],
        approval_comment="Approved at the organisation's strategy review, alongside the Strategy/Future State"
        " it constrains.",
    )
    create_org_guiding_principle_relationship(
        h_pm, org["id"], org_guiding_principle["id"], kind="supports_strategy", target_id=org_strategy["id"],
    )
    drone_guiding_principle = create_project_guiding_principle(
        h_pm, drone["id"], name="Field reports are captured once, at the point of inspection",
        principle_statement="Inspection findings must be captured directly in the system of record at the point"
        " of inspection — never on an intermediate paper form re-keyed later.",
        rationale="Directly addresses the accepted 'field inspectors re-key paper reports' Pain Point above —"
        " re-keying is both an SLA-breach risk and a transcription-error risk in the compliance record, so this"
        " principle exists to stop new features from reintroducing the same failure mode.",
        priority="high", owner={"type": "user", "id": demo_engineer["user_id"]},
    )
    propose_and_approve_project_guiding_principle(
        h_pm, drone["id"], drone_guiding_principle["id"],
        approval_comment="Approved — directly checked against the accepted paper-re-keying Pain Point above.",
    )

    print("Seeding Open Questions — one walked partway through investigation, one withdrawn"
          " (no ArtefactLink relationship to a Decision yet, and no 'Create Decision"
          " from Open Question' workflow yet)...")
    oq_battery_vendor = create_open_question(
        h_pm, drone["id"], question="Should the Falcon-3 drone fleet standardise on a single battery vendor?",
        context="Falcon-3 currently qualifies battery packs from two vendors. A single-vendor policy would"
        " simplify spares logistics and field-technician training, directly supporting the 'field reports"
        " captured once' Guiding Principle above by reducing the number of distinct part numbers inspectors"
        " must record — but it increases exposure to a single supply-chain disruption.",
        evidence="Procurement flagged a 6-week lead-time gap for the secondary vendor last quarter; the"
        " primary vendor has never missed a delivery window in 18 months.",
        priority="high", due_date=(date.today() + timedelta(days=21)).isoformat(),
    )
    assign_owner(
        h_pm, drone["id"], "open-questions", oq_battery_vendor,
        ("question", "context", "evidence", "priority", "due_date"),
        {"type": "org_group", "id": architecture_board.json()["id"]},
    )
    investigate_open_question(h_pm, drone["id"], oq_battery_vendor["id"])
    mark_open_question_ready_for_decision(h_pm, drone["id"], oq_battery_vendor["id"])
    print(f"  Ready for Decision: {oq_battery_vendor['question']!r} (awaiting a Decision to resolve it)")

    oq_offline_ui = create_open_question(
        h_pm, drone["id"], question="Should the degraded-connectivity indicator (per the org Guiding Principle"
        " above) be a persistent banner or a modal interrupt?",
        context="Raised during UI design review; the org's 'Operate safely under degraded connectivity'"
        " Guiding Principle requires a clear indicator, but not a specific presentation.",
        evidence="", priority="medium",
    )
    investigate_open_question(h_pm, drone["id"], oq_offline_ui["id"])
    withdraw_open_question(
        h_pm, drone["id"], oq_offline_ui["id"],
        comment="Withdrawn — already settled as part of the platform-wide UX style guide's alert-tier"
        " patterns; no separate decision needed for this product.",
    )
    print(f"  Withdrawn: {oq_offline_ui['question']!r}")

    # Still open, past its due date and unowned, so the register report (R4) demonstrates its Overdue and
    # Unowned gap lists.
    create_open_question(
        h_pm, drone["id"], question="Which destination markets require Remote ID broadcast at launch?",
        context="Sales has quoted two markets that have not yet confirmed their Remote ID rules.",
        evidence="", priority="medium", due_date=(date.today() - timedelta(days=12)).isoformat(),
    )
    print("  Open and overdue: 'Which destination markets require Remote ID broadcast at launch?'")

    print("Seeding Stakeholders & Personas — enabling the module, then two org personas (one"
          " weighted, one not) and a project persona on Falcon-3, plus a Falcon-3 weight override that its"
          " Avionics sub-project inherits...")
    enable_module(h_pm, org["id"], "stakeholders")
    persona_inspector = create_org_persona(
        h_pm, org["id"], name="Field Inspector", role_title="Utility field inspector",
        description="Walks infrastructure corridors capturing inspection findings.",
        goals="Capture every finding once, at the point of inspection, without re-keying.",
        needs="Offline-first data capture; a degraded-connectivity indicator that is hard to miss.",
        behaviours="Works in short bursts between sites; avoids anything needing a signal.",
        context_environment="Outdoors, gloves on, often no network coverage.",
        skills_proficiency="Expert in the infrastructure, comfortable but not enthusiastic with software.",
        frequency_of_use="Daily", constraints="Intermittent connectivity; one hand often occupied.", weight=3.0,
    )
    activate_org_persona(h_pm, org["id"], persona_inspector["id"])
    persona_auditor = create_org_persona(
        h_pm, org["id"], name="Compliance Auditor", role_title="Regulatory auditor",
        description="Reviews certification evidence on behalf of the regulator; not yet validated with a real auditor.",
        goals="Verify evidence quickly without having to chase the engineering team.",
    )
    drone_operator_persona = create_project_persona(
        h_pm, drone["id"], name="BVLOS Remote Pilot", role_title="Remote pilot",
        description="Flies Falcon-3 beyond visual line of sight from an operations centre.",
        goals="Keep every flight within the certified envelope.", needs="Unambiguous status for the redundant"
        " flight controllers.", frequency_of_use="Several flights per shift", weight=2.0,
        # A team can own a Persona (users-and-groups parity): the Architecture Board owns this one.
        owner={"type": "org_group", "id": architecture_board.json()["id"]},
    )
    activate_project_persona(h_pm, drone["id"], drone_operator_persona["id"])
    set_project_persona_weight_override(h_pm, drone["id"], persona_inspector["id"], 5.0)
    persona_harbour = create_org_persona(
        h_pm, org["id"], name="Harbour Pilot", role_title="Marine pilot",
        description="Guides vessels into port; relevant to the org's marine products, not to the drone programme.",
        goals="Bring each vessel alongside safely.", weight=1.0,
    )
    activate_org_persona(h_pm, org["id"], persona_harbour["id"])
    set_persona_visibility(h_pm, drone["id"], persona_harbour["id"], True)
    print(f"  Personas: {persona_inspector['name']!r} (org, Active, weight 3), {persona_harbour['name']!r} (org, Active,"
          f" hidden from Falcon-3), {persona_auditor['name']!r} (org,"
          f" Draft, unweighted), {drone_operator_persona['name']!r} (Falcon-3, Active, weight 2); Falcon-3 weights"
          f" {persona_inspector['name']!r} at 5, which Falcon-3 Avionics Subsystem inherits")

    print("Seeding per-persona Pain Point scoring on Falcon-3 — per-persona scores across"
          " personas of different weights (one persona left unscored), an all-personas Blocker, an intentional"
          " limitation, and an unscored Pain Point...")
    pp_levels = get_pain_point_levels(h_pm, drone["id"])
    print("  Falcon-3 pins the Severity × Frequency cell Blocker × Rare to High (its score alone would only earn"
          " Medium): a blocker is never a minor problem, however rare (cell ratings)...")
    set_project_scoring_cell_ratings(h_pm, drone["id"], "pain_point", "sxf", [{
        "first_level_id": pp_levels["severity"]["Blocker"], "second_level_id": pp_levels["frequency"]["Rare"],
        "band_label": "High",
    }])
    set_pain_point_scores(h_pm, drone["id"], pp_accepted["id"], [
        # General: Cost of Delay's criteria (the whole Pain Point) and the default for the per-persona ones.
        score_entry(
            pp_levels, None, severity="Moderate", frequency="Frequent", confidence="High", value="High",
            time_criticality="Moderate", risk_reduction="Substantial", job_size="Medium",
        ),
        score_entry(pp_levels, persona_inspector["id"], severity="Major", frequency="Frequent", confidence="High"),
        score_entry(pp_levels, drone_operator_persona["id"], severity="Moderate", frequency="Constant", confidence="Medium"),
    ])
    pp_scored = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["User"]["id"],
        title="Pilots cannot tell which redundant flight controller is in command",
        description="The ground-station display shows both flight controllers as 'healthy' without indicating"
        " which one is currently flying the aircraft.",
        source="Pilot debrief — BVLOS trial", impact="A failover mid-flight is not noticed until the next scheduled"
        " status poll.", evidence="Observed in 3 of 10 BVLOS trial flights.",
        priority="high", date_identified="2026-09-02",
    )
    triage_pain_point(h_pm, drone["id"], pp_scored["id"])
    accept_pain_point(h_pm, drone["id"], pp_scored["id"])
    # Evidence pictures on a Pain Point that is still open (a Pain Point at a terminal outcome takes no more attachments).
    for picture in (TRIAL_SITE_PICTURE, ARCHITECTURE_DIAGRAM):
        attach_picture(h_pm, drone["id"], f"modules/context_strategy/pain-points/{pp_scored['id']}", picture)
    set_pain_point_scores(h_pm, drone["id"], pp_scored["id"], [
        score_entry(pp_levels, drone_operator_persona["id"], severity="Blocker", frequency="Occasional", confidence="High"),
        score_entry(pp_levels, persona_inspector["id"], severity="Minor", frequency="Rare", confidence="Medium"),
    ])
    pp_all_personas = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["Operator"]["id"],
        title="Flight logs cannot be exported for audit", priority="medium", date_identified="2026-09-05",
        description="There is no way to export a flight's log for an external audit.",
        impact="Every audit request needs an engineer to extract the logs by hand.",
    )
    set_pain_point_scores(h_pm, drone["id"], pp_all_personas["id"], [
        score_entry(pp_levels, None, severity="Moderate", frequency="Occasional", confidence="Low"),
    ])
    create_project_pain_point_relationship(
        h_pm, drone["id"], pp_all_personas["id"], kind="motivates_requirement",
        target_id=drone_reqs["Log all flight-critical state transitions to onboard non-volatile storage"]["id"],
    )
    pp_intentional = create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["Market"]["id"],
        title="Standard tier limits flights to line-of-sight", priority="low", date_identified="2026-09-08",
        description="BVLOS operation is only available on the Pro tier.", is_intentional=True,
        impact="Customers needing BVLOS must upgrade — a deliberate differentiator.",
    )
    set_pain_point_scores(h_pm, drone["id"], pp_intentional["id"], [
        score_entry(pp_levels, drone_operator_persona["id"], severity="Major", frequency="Constant", confidence="High"),
    ])
    create_pain_point(
        h_pm, drone["id"], pain_point_type_id=drone_pain_point_types["User"]["id"],
        title="Pre-flight checklist is not available offline", priority="medium", date_identified="2026-09-10",
        description="The checklist app needs a connection, which remote launch sites rarely have.",
    )
    print(f"  Scored: {pp_accepted['title']!r} (2 personas), {pp_scored['title']!r} (Blocker for the BVLOS pilot),"
          f" {pp_all_personas['title']!r} (all personas), {pp_intentional['title']!r} (intentional); one Pain Point"
          " left unscored.")

    print("Seeding Stakeholders — an org Regulator stakeholder rated High influence/Medium"
          " interest that represents the Compliance Auditor persona, and a Falcon-3 Customer stakeholder with a"
          " monthly cadence that represents the BVLOS Remote Pilot persona...")
    levels = get_stakeholder_levels(h_pm, org["id"])
    stakeholder_authority = create_stakeholder(
        h_pm, org_id=org["id"], activate=True, represents=(persona_auditor["id"],), name="Pat Okafor",
        owner={"type": "user", "id": demo_engineer["user_id"]},
        stakeholder_type_id=get_stakeholder_type_id(h_pm, org_id=org["id"], name="Regulator"),
        role="Certification auditor", organisation_group="Civil Aviation Authority",
        interests="Evidence that the airworthiness case is complete and traceable.",
        responsibilities="Signs off the type certificate.", goals_needs="Traceable evidence without chasing engineers.",
        priorities="Safety of flight above schedule.", constraints="Only available for two audit windows a year.",
        workflows_scenarios="Desk review of the certification evidence, then an on-site audit.",
        contact_info="pat.okafor@authority.example.com", target_cadence="quarterly",
        availability_constraints="Prefers email; unavailable in Q1.",
        influence_level_id=levels["influence"]["High"], interest_level_id=levels["interest"]["Medium"],
    )
    stakeholder_fleet = create_stakeholder(
        h_pm, project_id=drone["id"], activate=True, represents=(drone_operator_persona["id"],), name="Dana Whitfield",
        stakeholder_type_id=get_stakeholder_type_id(h_pm, project_id=drone["id"], name="Customer"),
        role="Fleet operations manager", organisation_group="Skyline Logistics",
        interests="Maximum flight hours per airframe.", goals_needs="A status display her pilots can trust at a glance.",
        contact_info="dana.whitfield@skyline.example.com", target_cadence="monthly",
        availability_constraints="Weekday mornings only.",
        influence_level_id=levels["influence"]["Medium"], interest_level_id=levels["interest"]["High"],
    )
    stakeholder_harbour = create_stakeholder(
        h_pm, org_id=org["id"], activate=True, name="Lee Harbour",
        stakeholder_type_id=get_stakeholder_type_id(h_pm, org_id=org["id"], name="Regulator"),
        role="Port authority liaison", organisation_group="Harbour Authority",
        interests="Marine safety inspections of vessels.", target_cadence="yearly",
        influence_level_id=levels["influence"]["Low"], interest_level_id=levels["interest"]["Low"],
    )
    set_stakeholder_visibility(h_pm, drone["id"], stakeholder_harbour["id"], True)
    print(f"  Stakeholders: {stakeholder_authority['name']!r} (org, Regulator, Active, High/Medium, quarterly),"
          f" {stakeholder_fleet['name']!r} (Falcon-3, Customer, Active, Medium/High, monthly),"
          f" {stakeholder_harbour['name']!r} (org, Regulator, Active) — hidden from Falcon-3, which has no marine dealings")

    print("Seeding Stakeholder groups — an org Client taxonomy whose children are mutually exclusive,"
          " a Regulator group, and a Falcon-3 project group nested under an org group...")
    group_client = create_stakeholder_group(h_pm, org_id=org["id"], name="Client", exclusive_children=True)
    group_skyline = create_stakeholder_group(
        h_pm, org_id=org["id"], name="Skyline Logistics", parent_group_id=group_client["id"],
    )
    group_regulators = create_stakeholder_group(h_pm, org_id=org["id"], name="Regulators")
    group_aviation = create_stakeholder_group(
        h_pm, org_id=org["id"], name="Aviation", parent_group_id=group_regulators["id"],
    )
    add_stakeholder_to_group(h_pm, group_aviation["id"], stakeholder_authority["id"], org_id=org["id"])
    add_stakeholder_to_group(h_pm, group_regulators["id"], stakeholder_harbour["id"], org_id=org["id"])
    group_pilot_customers = create_stakeholder_group(
        h_pm, project_id=drone["id"], name="Launch-site customers", parent_group_id=group_skyline["id"],
    )
    add_stakeholder_to_group(h_pm, group_pilot_customers["id"], stakeholder_fleet["id"], project_id=drone["id"])
    print("  Groups: Client > Skyline Logistics > (Falcon-3) Launch-site customers; Regulators > Aviation (Pat Okafor),"
          " Regulators (Lee Harbour)")

    print("Seeding Stakeholder Needs — Falcon-3's fleet manager needs a trustworthy status display,"
          " which gave rise to its first requirement; the BVLOS Remote Pilot persona has the same need...")
    need_status_display = create_need(
        h_pm, drone["id"], activate=True, holders=(("stakeholder", stakeholder_fleet["id"]), ("persona", drone_operator_persona["id"])),
        requirement_ids=(flight_log_req["id"],), name="Trust the flight status at a glance",
        owner={"type": "org_group", "id": architecture_board.json()["id"]},
        description="My pilots must be able to tell, in under a second, whether the redundant flight controllers agree.",
        rationale="Two incidents last year where a pilot misread a degraded-channel warning.",
    )
    create_need(
        h_pm, drone["id"], holders=(("stakeholder", stakeholder_authority["id"]),), name="Evidence without chasing engineers",
        description="Certification evidence should be traceable to the requirement it supports without a meeting.",
    )
    print(f"  Needs: {need_status_display['name']!r} (Active, held by Dana Whitfield and the BVLOS Remote Pilot persona,"
          f" gave rise to {flight_log_req['name']!r}), plus a Draft need held by Pat Okafor")

    print("Seeding Engagements — a quick email log, a focus group with anonymous participants and"
          " findings, and an old briefing that leaves the quarterly regulator overdue...")
    enable_research_extras(h_pm, org["id"])
    engagement_email = create_engagement(
        h_pm, drone["id"], title="Status display feedback", channel="email", engagement_date="2026-10-02",
        summary="Dana wants the degraded-channel warning to be unmissable.", notes="Replied to her 1 Oct email.",
        stakeholder_ids=[stakeholder_fleet["id"]], outcomes=(("raised", "stakeholder_need", need_status_display["id"]),),
    )
    engagement_focus = create_engagement(
        h_pm, drone["id"], title="Launch-site pilot focus group", channel="focus_group", engagement_date="2026-09-18",
        facilitators=[{"type": "user", "id": demo_engineer["user_id"]}, {"type": "org_group", "id": architecture_board.json()["id"]}],
        purpose="How pilots read the status display.",
        summary="Pilots missed the degraded-channel warning in glare.", consent_recorded=True, retain_until="2027-09-18",
        persona_ids=[drone_operator_persona["id"]], group_ids=[group_pilot_customers["id"]],
        outcomes=(("raised", "pain_point", pp_scored["id"]),),
        prompts=(("Talk us through a pre-flight check.", "Three said they skip the checklist app."),
                 ("What would make the warning unmissable?", "Sound, and a full-width banner.")),
        anonymous=(("Participant 1", drone_operator_persona["id"]), ("Participant 2", drone_operator_persona["id"]),
                   ("Participant 3", None)),
        findings=({"title": "The warning is invisible in glare", "description": "Four of five pilots missed it outdoors.",
                   "outcomes": (("raised", "pain_point", pp_scored["id"]),)},),
    )
    engagement_old = create_engagement(
        h_pm, drone["id"], title="Audit window briefing", channel="meeting", engagement_date="2026-03-04",
        summary="Walked Pat through the evidence index.", stakeholder_ids=[stakeholder_authority["id"]],
    )
    print(f"  Engagements: {engagement_email['title']!r} (email, Dana), {engagement_focus['title']!r} (focus group, group"
          f" audience, 3 anonymous participants, 2 prompts, 1 finding), {engagement_old['title']!r} (March: Pat Okafor, whose"
          " quarterly cadence is now overdue)")

    print("Seeding Stakeholder/Persona relationships — the Field Inspector persona experiences the"
          " re-keying Pain Point, the fleet manager provides the status-display requirement and was consulted on the"
          " single flight controller Decision, the regulator reviews that requirement...")
    for holder_kind, holder_id, kind, target_type, target_id in (
        ("persona", persona_inspector["id"], "experiences_pain_point", "pain_point", pp_accepted["id"]),
        ("stakeholder", stakeholder_fleet["id"], "provides_requirement", "requirement", flight_log_req["id"]),
        ("stakeholder", stakeholder_fleet["id"], "consulted_on_decision", "decision", single_fc_decision["id"]),
        ("stakeholder", stakeholder_authority["id"], "reviews", "requirement", flight_log_req["id"]),
    ):
        add_stakeholder_relationship(h_pm, drone["id"], holder_kind, holder_id, kind, target_type, target_id)

    print("Seeding Risk Management — enabling the module, then a small Falcon-3 risk register."
          " Falcon-3 pins the Likelihood x Consequence cell Rare x Catastrophic to High (its score alone would only earn"
          " Medium): a catastrophe is never a minor risk, however unlikely...")
    enable_module(h_pm, org["id"], "risk_management")
    risk_types = list_effective_risk_types(h_pm, drone["id"])
    risk_levels = get_risk_levels(h_pm, drone["id"])
    # Falcon-3 is an airframe project: the organisation's "Environmental" Risk type is hidden here (Project admin ->
    # Risk Types shows "Add organisation defaults (1)"); other projects still see it and no risk below uses it.
    r = httpx.delete(
        f"{BASE}/projects/{drone['id']}/modules/risk_management/risk-types/{risk_types['Environmental']['id']}",
        headers=h_pm, timeout=30,
    )
    r.raise_for_status()
    set_project_scoring_cell_ratings(h_pm, drone["id"], "risk", "lxc", [{
        "first_level_id": risk_levels["likelihood"]["Rare"], "second_level_id": risk_levels["consequence"]["Catastrophic"],
        "band_label": "High",
    }])
    risk_single_controller = create_risk(
        h_pm, drone["id"], risk_levels, risk_type_id=risk_types["Safety"]["id"],
        owner={"type": "org_group", "id": architecture_board.json()["id"]},  # a team owns the safety risk (users-and-groups parity)
        title="Flight controller fails in flight",
        statement="If the flight controller fails during a flight over people, the drone falls uncontrolled.",
        cause="Single flight controller board with no in-flight redundancy.", risk_event="Loss of flight control.",
        consequence="Injury to bystanders and loss of the airframe.", treatment_strategy="mitigate",
        acceptance_criteria="Dual-redundant architecture certified; no single fault leads to loss of control.",
        inherent=("Possible", "Catastrophic"), residual=("Unlikely", "Major"), review_date=(date.today() + timedelta(days=60)).isoformat(),
    )
    for picture in (BENCH_RIG_PICTURE, ARCHITECTURE_DIAGRAM):
        attach_picture(h_pm, drone["id"], f"modules/risk_management/risks/{risk_single_controller['id']}", picture)
    risk_modem = create_risk(
        h_pm, drone["id"], risk_levels, risk_type_id=risk_types["Supply chain"]["id"], owner={"type": "user", "id": demo_admin["user_id"]},
        title="Cellular modem supplier misses delivery",
        statement="If the single-sourced modem arrives late, integration testing slips and the certification date is at risk.",
        risk_event="Late delivery of the telemetry modem.", consequence="Integration slips by several weeks.",
        treatment_strategy="mitigate", inherent=("Likely", "Moderate"), residual=("Possible", "Minor"),
    )
    risk_regulator = create_risk(
        h_pm, drone["id"], risk_levels, risk_type_id=risk_types["Compliance"]["id"], owner={"type": "user", "id": demo_admin["user_id"]},
        title="Regulator withdraws BVLOS approval",
        statement="If the regulator withdraws beyond-visual-line-of-sight approval, populated-corridor contracts cannot be flown.",
        consequence="The core commercial route is lost.", inherent=("Rare", "Catastrophic"), residual=("Rare", "Catastrophic"),
        treatment_strategy="accept", acceptance_criteria="Approval conditions are tracked quarterly; contracts allow a re-route.",
    )
    # Spread the register across the lifecycle: one in treatment, one assessed, one formally accepted (the project
    # manager satisfies the Risk Acceptor role), and the unscored one left Identified.
    transition_risk(h_pm, drone["id"], risk_single_controller["id"], "assessed", "treatment_planned", "treatment_in_progress")
    transition_risk(h_pm, drone["id"], risk_modem["id"], "assessed")
    transition_risk(h_pm, drone["id"], risk_regulator["id"], "assessed", "accepted")
    risk_unscored = create_risk(
        h_pm, drone["id"], risk_levels, risk_type_id=risk_types["Performance"]["id"], title="Gimbal vibration degrades imagery",
        statement="Rotor vibration may blur inspection imagery at the gimbal's maximum zoom.",
    )
    # Treatment links and their verdicts. A link alone only "proposes" a treatment; the project manager
    # (a Risk Manager) attests the pre-flight diagnostics are effective, leaves the return-to-home link proposed, and
    # the modem risk is treated by a dual-sourcing action that is linked but not yet assessed.
    risk_link_types = {lt["forward_name"]: lt for lt in httpx.get(f"{BASE}/orgs/{org['id']}/link-types", headers=h_pm, timeout=30).json()}
    risk_url = f"{BASE}/projects/{drone['id']}/modules/risk_management/risks"
    effective_link = create_artefact_link(
        h_pm, drone["id"], "risk", risk_single_controller["id"], link_type_id=risk_link_types["Mitigates"]["id"],
        other_type="requirement", other_id=preflight_req["id"], direction="incoming",
    )
    httpx.put(
        f"{risk_url}/{risk_single_controller['id']}/treatments/{effective_link['id']}",
        json={"status": "effective", "rationale": "Diagnostics detect a degraded controller on the ground, before launch."},
        headers=h_pm, timeout=30,
    ).raise_for_status()
    create_artefact_link(
        h_pm, drone["id"], "risk", risk_single_controller["id"], link_type_id=risk_link_types["Mitigates"]["id"],
        other_type="requirement", other_id=return_to_home_req["id"], direction="incoming",
    )
    modem_action_types = httpx.get(f"{BASE}/projects/{drone['id']}/action-types", headers=h_pm, timeout=30).json()
    # A standalone action: every Falcon-3 requirement is approved by now, so none accepts a direct attachment.
    modem_action_response = httpx.post(
        f"{BASE}/projects/{drone['id']}/actions",
        json={
            "title": "Qualify a second cellular modem supplier",
            "description": "Dual-source the telemetry modem so one late delivery cannot stall integration.",
            "action_type_id": modem_action_types[0]["id"],
        },
        headers=h_pm, timeout=30,
    )
    modem_action_response.raise_for_status()
    modem_action = modem_action_response.json()
    create_artefact_link(
        h_pm, drone["id"], "risk", risk_modem["id"], link_type_id=risk_link_types["Treated by"]["id"],
        other_type="requirement_action", other_id=modem_action["id"],
    )
    create_artefact_link(
        h_pm, drone["id"], "risk", risk_single_controller["id"], link_type_id=risk_link_types["Impacts"]["id"],
        other_type="requirement", other_id=flight_log_req["id"],
    )
    # The single-controller risk has been reviewed (its next review is a month out); the modem risk's
    # scheduled review date has passed, so it shows as overdue and the review-due sweep has something to notify about.
    httpx.post(
        f"{risk_url}/{risk_single_controller['id']}/reviews",
        json={
            "outcome": "confirmed", "notes": "Diagnostics still cover the failure mode; the residual rating stands.",
            "next_review_date": (date.today() + timedelta(days=30)).isoformat(),
        },
        headers=h_pm, timeout=30,
    ).raise_for_status()
    httpx.put(
        f"{risk_url}/{risk_modem['id']}", json={"review_date": (date.today() - timedelta(days=5)).isoformat()},
        headers=h_pm, timeout=30,
    ).raise_for_status()
    print(f"  Risks: {risk_single_controller['unique_code']} {risk_single_controller['title']!r}"
          f" (inherent {risk_single_controller['inherent_rating']['label']}, residual {risk_single_controller['residual_rating']['label']}),"
          f" {risk_regulator['unique_code']} {risk_regulator['title']!r} (inherent {risk_regulator['inherent_rating']['label']}"
          f" from its pinned cell), plus {risk_unscored['unique_code']} captured with no assessment yet and a modem supply-chain risk")

    print("Seeding Product Feedback — enabling the module, then enhancement requests on Falcon-3 across the"
          " lifecycle (one owned by the avionics engineer, one declined with a reason, one with Jira and ServiceNow"
          " references and a channel per requester; two scored with Reach, Impact, Confidence and Effort) and two in the organisation's inbox...")
    enable_module(h_pm, org["id"], "product_feedback")
    feedback_url = f"{BASE}/projects/{drone['id']}/modules/product_feedback"
    inbox_url = f"{BASE}/orgs/{org['id']}/modules/product_feedback"
    # Falcon-3's own scoring criteria, added to the built-in ones: a "Safety relevance" axis and a weighted-sum model
    # that trades impact against it (the project layer of the scoring scheme).
    scoring_url = f"{BASE}/projects/{drone['id']}/scoring-schemes/enhancement_request"
    httpx.post(f"{scoring_url}/axes", json={
        "label": "Safety relevance", "description": "How much the request matters for safe operation.",
        "levels": [{"name": "None", "weight": 1}, {"name": "Supports safe operation", "weight": 2},
                   {"name": "Safety critical", "weight": 4}],
    }, headers=h_pm, timeout=30).raise_for_status()
    httpx.post(f"{scoring_url}/models", json={
        "label": "Impact and safety", "combination": "weighted_sum", "axes": [
            {"axis_key": "impact", "role": "sum", "importance": 60},
            {"axis_key": "c_safety_relevance", "role": "sum", "importance": 40}],
    }, headers=h_pm, timeout=30).raise_for_status()
    request_levels = get_request_levels(h_pm, drone["id"])
    external_systems = {
        e["name"]: e["id"] for e in httpx.get(f"{feedback_url}/external-systems", headers=h_pm, timeout=30).json()
    }
    request_channels = {
        e["name"]: e["id"] for e in httpx.get(f"{feedback_url}/request-channels", headers=h_pm, timeout=30).json()
    }
    export_request = create_enhancement_request(
        h_pm, feedback_url, title="Export the inspection log as a spreadsheet",
        **request_score_fields(request_levels, "Many", "High", "High", "Small", "Easy", safety="Supports safe operation"),
        description="Inspectors want to pull a day's inspection log into a spreadsheet for the weekly review.",
        owner={"type": "user", "id": demo_engineer["user_id"]},
        references=[
            {"system_id": external_systems["Jira"], "key": "FAL-214", "url": "https://tracker.example.com/browse/FAL-214"},
            {"system_id": external_systems["ServiceNow"], "key": "INC0012345", "role": "origin"},
        ],
    )
    transition_enhancement_request(h_pm, feedback_url, export_request["id"], "under_review")
    transition_enhancement_request(h_pm, feedback_url, export_request["id"], "accepted")
    offline_request = create_enhancement_request(
        h_pm, feedback_url, title="Offline map tiles for remote sites",
        description="Field teams lose the map when they work outside coverage.",
        **request_score_fields(request_levels, "Some", "Massive", "Medium", "Large", "Hard"),
    )
    declined_request = create_enhancement_request(
        h_pm, feedback_url, title="Add a built-in video editor",
        description="Let operators trim flight footage in the app.",
    )
    transition_enhancement_request(
        h_pm, feedback_url, declined_request["id"], "declined",
        "Out of scope: footage is edited in the customer's existing tools.",
    )
    create_enhancement_request(
        h_pm, inbox_url, title="Single sign-on for the operator console",
        description="Operations staff want to use the company login.",
    )
    create_enhancement_request(
        h_pm, inbox_url, title="Dark mode for night operations",
        description="The console is too bright for night flights.",
    )
    # Demand: who asked is a "Requested by" link to a Stakeholder, Persona or Engagement; a duplicate is merged into
    # the request it repeats, so the accepted request's demand is the union of both requests' requesters.
    requested_by = next(
        lt for lt in httpx.get(f"{BASE}/orgs/{org['id']}/link-types", headers=h_pm, timeout=30).json()
        if lt["forward_name"] == "Requested by"
    )
    duplicate_request = create_enhancement_request(
        h_pm, feedback_url, title="Download inspection results as CSV",
        description="Same ask as the spreadsheet export, from the certification side.",
    )
    for request, other_type, other in (
        (export_request, "stakeholder", stakeholder_fleet), (export_request, "engagement", engagement_focus),
        (duplicate_request, "stakeholder", stakeholder_authority), (duplicate_request, "persona", persona_auditor),
    ):
        create_artefact_link(
            h_pm, drone["id"], "enhancement_request", request["id"], link_type_id=requested_by["id"],
            other_type=other_type, other_id=other["id"],
        )
    httpx.post(
        f"{feedback_url}/requests/{duplicate_request['id']}/merge",
        json={"canonical_id": export_request["id"], "note": "Same ask, different wording."}, headers=h_pm, timeout=30,
    ).raise_for_status()
    # The channel per ask: how each requester of the accepted request (merged duplicate's included) asked. The
    # engagement's participants are shown as an Engagement and need none.
    for other, channel in ((stakeholder_fleet, "Support ticket"), (stakeholder_authority, "Email"), (persona_auditor, "Survey")):
        httpx.put(
            f"{feedback_url}/requests/{export_request['id']}/requester-channel",
            json={"parties": [{"artefact_type": "persona" if other is persona_auditor else "stakeholder", "id": other["id"]}],
                  "channel_id": request_channels[channel]}, headers=h_pm, timeout=30,
        ).raise_for_status()
    # Problem and delivery: the accepted request addresses a Pain Point and is realised by a requirement; a delivered
    # request has one requester told and one still to tell (the close-the-loop list).
    link_types = {lt["forward_name"]: lt for lt in httpx.get(f"{BASE}/orgs/{org['id']}/link-types", headers=h_pm, timeout=30).json()}
    create_artefact_link(
        h_pm, drone["id"], "enhancement_request", export_request["id"], link_type_id=link_types["Addresses"]["id"],
        other_type="pain_point", other_id=pp_accepted["id"],
    )
    create_artefact_link(
        h_pm, drone["id"], "enhancement_request", export_request["id"], link_type_id=link_types["Realised by"]["id"],
        other_type="requirement", other_id=list(drone_reqs.values())[0]["id"],
    )
    # More demand for the reports: a request with no problem behind it (Unlinked requests), a declined request nobody
    # has told yet (Close the loop), and requests addressing Pain Points with and without a Requirement (Problem demand).
    # Everything is created today, so Triage ageing lists these only with "Waiting longer than" set to 0 days.
    for request, other_type, other in (
        (offline_request, "stakeholder", stakeholder_fleet), (offline_request, "persona", drone_operator_persona),
        (declined_request, "stakeholder", stakeholder_authority),
    ):
        create_artefact_link(
            h_pm, drone["id"], "enhancement_request", request["id"], link_type_id=requested_by["id"],
            other_type=other_type, other_id=other["id"],
        )
    controller_request = create_enhancement_request(
        h_pm, feedback_url, title="Show which flight controller is in command",
        description="A clear indicator on the ground-station display of the active controller.",
        **request_score_fields(request_levels, "Some", "Massive", "High", "Medium", "Moderate", safety="Safety critical"),
    )
    transition_enhancement_request(h_pm, feedback_url, controller_request["id"], "under_review")
    audit_request = create_enhancement_request(
        h_pm, feedback_url, title="Audit-ready flight log export",
        description="A signed export of a flight's log for external auditors.",
        **request_score_fields(request_levels, "Few", "High", "Medium", "Large"),
    )
    summary_request = create_enhancement_request(
        h_pm, feedback_url, title="Weekly inspection summary by email",
        description="A digest of the week's inspections for the fleet manager.",
    )
    for request, other_type, other in (
        (controller_request, "persona", drone_operator_persona),
        (audit_request, "stakeholder", stakeholder_authority), (audit_request, "persona", persona_auditor),
        (summary_request, "stakeholder", stakeholder_fleet),
    ):
        create_artefact_link(
            h_pm, drone["id"], "enhancement_request", request["id"], link_type_id=requested_by["id"],
            other_type=other_type, other_id=other["id"],
        )
    for request, pain_point in (
        (controller_request, pp_scored), (audit_request, pp_all_personas), (summary_request, pp_accepted),
    ):
        create_artefact_link(
            h_pm, drone["id"], "enhancement_request", request["id"], link_type_id=link_types["Addresses"]["id"],
            other_type="pain_point", other_id=pain_point["id"],
        )
    delivered_request = create_enhancement_request(
        h_pm, feedback_url, title="Pre-flight checklist as a printable sheet",
        description="Pilots want the pre-flight checklist on one printable page.",
    )
    for status in ("under_review", "accepted", "delivered"):
        transition_enhancement_request(h_pm, feedback_url, delivered_request["id"], status)
    for other_type, other in (("stakeholder", stakeholder_fleet), ("persona", persona_auditor)):
        create_artefact_link(
            h_pm, drone["id"], "enhancement_request", delivered_request["id"], link_type_id=requested_by["id"],
            other_type=other_type, other_id=other["id"],
        )
    httpx.put(
        f"{feedback_url}/requests/{delivered_request['id']}/informed",
        json={"parties": [{"artefact_type": "stakeholder", "id": stakeholder_fleet["id"]}], "informed": True,
              "note": "Told at the monthly review."}, headers=h_pm, timeout=30,
    ).raise_for_status()
    print("  Product Feedback: 8 Falcon-3 requests (accepted with requesters from a stakeholder, an engagement and a"
          " merged duplicate, linked to a Pain Point and a requirement; one with demand but no Pain Point; declined and"
          " delivered with requesters still to be told; three scored requests addressing Pain Points that have no"
          " Requirement yet) and 2 organisation inbox requests; reports: Demand ranking, Unlinked requests, Close the"
          " loop, Triage ageing (set 'Waiting longer than' to 0) and Problem demand")

    print("Linking Pain Points, a Risk and a Decision to the requirements they drive (Motivates, Impacts, Affects)...")
    video_req = drone_reqs["Stream live video telemetry to the ground station at a minimum of 24fps"]
    for pain_point, requirement in ((pp_scored, flight_log_req), (pp_scored, video_req), (pp_accepted, flight_log_req)):
        create_artefact_link(
            h_pm, drone["id"], "pain_point", pain_point["id"], link_type_id=chain_link_types["Motivates"]["id"],
            other_type="requirement", other_id=requirement["id"],
        )
    for requirement in (return_to_home_req, gps_req):
        create_artefact_link(
            h_pm, drone["id"], "risk", risk_single_controller["id"], link_type_id=risk_link_types["Impacts"]["id"],
            other_type="requirement", other_id=requirement["id"],
        )
    create_artefact_link(
        h_pm, drone["id"], "decision", dual_fc_decision["id"], link_type_id=chain_link_types["Affects"]["id"],
        other_type="requirement", other_id=return_to_home_req["id"],
    )

    print("Seeding the Business Requirements Document with evidence: every Pain Point and Risk with its pictures and linked requirements...")
    create_illustrated_brd(h_pm, org["id"])

    print("Seeding two template projects (Product Design, Project Management) and a project created from one, with Cost of Delay scoring...")
    product_design = create_project(
        h_pm, org["id"], "Product Design template",
        "Starting point for a product design project: feedback, personas and decisions, with Usability and Accessibility Pain Points.",
        is_template=True,
    )
    for module_key, enabled in (("risk_management", False), ("compliance", False)):
        set_project_module(h_pm, product_design["id"], module_key, enabled)
    hide_pain_point_types(h_pm, product_design["id"], ["Market", "Operator"])
    add_pain_point_types(h_pm, product_design["id"], {
        "Usability": "A task is slow, confusing or error-prone for the people who use the product.",
        "Accessibility": "A person cannot use the product because of a disability, a device or a setting.",
    })
    # Pain Points on this template are ranked by Cost of Delay divided by job size (WSJF) instead of the platform default.
    set_project_scoring_default_model(h_pm, product_design["id"], "pain_point", "wsjf")
    design_components = {
        "RS": create_component(h_pm, product_design["id"], "Research", "RS"),
        "UI": create_component(h_pm, product_design["id"], "Interface", "UI"),
    }
    design_categories = create_categories_for_components(h_pm, product_design["id"], design_components, {"RS": ["FN"], "UI": ["FN", "PERF"]})
    create_stage(h_pm, product_design["id"], "Discovery")
    create_stage(h_pm, product_design["id"], "Release", improvement_workflow["id"])
    for name, reasoning, comp_key, cat_key in (
        ("Record every usability session with the participant's consent",
         "Sessions that are not recorded cannot be reviewed by people who were not in the room.", "RS", "FN"),
        ("Load the main screen in under 2 seconds on a mid-range phone",
         "A slow first screen is the most common reason a person abandons a task.", "UI", "PERF"),
        ("Offer every action from the keyboard",
         "People who cannot use a pointing device must reach every action.", "UI", "FN"),
    ):
        create_requirement(
            h_pm, product_design["id"], name=name, reasoning=reasoning, component_id=design_components[comp_key]["id"],
            category_id=design_categories[comp_key][cat_key]["id"],
        )

    project_management = create_project(
        h_pm, org["id"], "Project Management template",
        "Starting point for delivering work through suppliers: risks, decisions and compliance, with Schedule, Budget and Resourcing Pain Points.",
        is_template=True,
    )
    for module_key, enabled in (("product_feedback", False), ("stakeholders", False)):
        set_project_module(h_pm, project_management["id"], module_key, enabled)
    hide_pain_point_types(h_pm, project_management["id"], ["Market", "User", "Operator"])
    add_pain_point_types(h_pm, project_management["id"], {
        "Schedule": "Work is late, or its dates cannot be trusted.",
        "Budget": "Spending is above plan, or the cost of the work is not known.",
        "Resourcing": "The people or suppliers the work needs are not available.",
    })
    delivery_components = {
        "PL": create_component(h_pm, project_management["id"], "Planning", "PL"),
        "DL": create_component(h_pm, project_management["id"], "Delivery", "DL"),
    }
    delivery_categories = create_categories_for_components(
        h_pm, project_management["id"], delivery_components, {"PL": ["FN", "REG"], "DL": ["FN", "PERF"]},
    )
    create_stage(h_pm, project_management["id"], "Initiation")
    create_stage(h_pm, project_management["id"], "Tendering and delivery", outsourced_workflow["id"])
    for name, reasoning, comp_key, cat_key in (
        ("Name an accountable owner for every deliverable",
         "A deliverable with no owner has no one to ask when it is late.", "PL", "FN"),
        ("Agree the acceptance criteria with each supplier before work starts",
         "Criteria agreed after the work starts are argued over, not applied.", "PL", "REG"),
        ("Report progress against the plan every two weeks",
         "A fixed reporting rhythm makes a slipping date visible while it can still be recovered.", "DL", "PERF"),
    ):
        create_requirement(
            h_pm, project_management["id"], name=name, reasoning=reasoning, component_id=delivery_components[comp_key]["id"],
            category_id=delivery_categories[comp_key][cat_key]["id"],
        )

    operator_app = create_project(
        h_pm, org["id"], "Falcon-3 Operator App",
        "The tablet app pilots use at the launch site, created from the Product Design template.",
        template_project_id=product_design["id"],
    )
    app_pain_point_types = list_effective_pain_point_types(h_pm, operator_app["id"])
    app_levels = get_pain_point_levels(h_pm, operator_app["id"])
    for title, description, point_type, scores in (
        ("Pilots cannot read the status screen in direct sunlight",
         "The tablet's status screen washes out at the launch site, so pilots shade it with a hand or guess.", "Usability",
         {"value": "High", "time_criticality": "Substantial", "risk_reduction": "High", "job_size": "Small"}),
        ("Colour alone separates a warning from a fault on the status screen",
         "A pilot who cannot tell red from amber cannot tell a warning from a fault.", "Accessibility",
         {"value": "Substantial", "time_criticality": "Low", "risk_reduction": "Moderate", "job_size": "Large"}),
    ):
        pain_point = create_pain_point(
            h_pm, operator_app["id"], pain_point_type_id=app_pain_point_types[point_type]["id"], title=title,
            description=description, source="Pilot debrief — launch-site trial", priority="medium",
        )
        triage_pain_point(h_pm, operator_app["id"], pain_point["id"])
        accept_pain_point(h_pm, operator_app["id"], pain_point["id"])
        set_pain_point_scores(h_pm, operator_app["id"], pain_point["id"], [score_entry(app_levels, None, **scores)])

    print("Seeding tags — Falcon-3's own vocabulary (with colours), tags on requirements, a Pain Point, a Risk and"
          " a Persona of different kinds, an organisation tag on an organisation Persona, and the Avionics"
          " sub-project following Falcon-3's list...")
    create_tag(h_pm, drone["id"], "Safety-critical", "#c53030")
    create_tag(h_pm, drone["id"], "Regulatory", "#2b6cb0")
    create_tag(h_pm, drone["id"], "Release 1", "#2f855a")
    create_tag(h_pm, drone["id"], "Needs review")
    drone_req_list = list(drone_reqs.values())
    for index, requirement in enumerate(drone_req_list[:6]):
        names = ["Safety-critical"] if index % 3 == 0 else ["Regulatory", "Release 1"] if index % 3 == 1 else ["Release 1"]
        tag_record(h_pm, drone["id"], "requirement", requirement["id"], names)
    tag_record(h_pm, drone["id"], "pain_point", pp_accepted["id"], ["Safety-critical", "Needs review"])
    tag_record(h_pm, drone["id"], "risk", risk_single_controller["id"], ["Safety-critical"])
    tag_record(h_pm, drone["id"], "persona", drone_operator_persona["id"], ["Regulatory"])
    create_tag_org = httpx.post(
        f"{BASE}/orgs/{org['id']}/tags", json={"name": "Strategic", "colour": "#6b46c1"}, headers=h_pm, timeout=30,
    )
    create_tag_org.raise_for_status()
    tag_record(h_pm, drone["id"], "persona", persona_inspector["id"], ["Strategic"])

    print("Seeding component placements — a Pain Point and a Risk in more than one component or category, and a Persona"
          " in one component, so the Components column, the component filter and the header chips have content...")
    place_record(h_pm, drone["id"], "pain_point", pp_accepted["id"], [
        (drone_components["FW"], drone_categories["FW"]["SAF"]), (drone_components["AV"], None),
    ])
    place_record(h_pm, drone["id"], "risk", risk_single_controller["id"], [
        (drone_components["AV"], drone_categories["AV"]["SAF"]),
    ])
    place_record(h_pm, drone["id"], "persona", drone_operator_persona["id"], [(drone_components["PR"], None)])

    print("Seeding a restricted tag vocabulary — Solstice Cloud Platform lists its tags and allows no others,"
          " so its tag field only offers the list (Falcon-3 stays free)...")
    for name, colour in (("Security", "#c53030"), ("Performance", "#b7791f"), ("Availability", "#2b6cb0")):
        create_tag(h_pm, cloud["id"], name, colour)
    httpx.put(
        f"{BASE}/projects/{cloud['id']}/tag-settings", json={"mode": "restricted"}, headers=h_pm, timeout=30,
    ).raise_for_status()
    for index, requirement in enumerate(list(cloud_reqs.values())[:3]):
        tag_record(h_pm, cloud["id"], "requirement", requirement["id"], [("Security", "Performance", "Availability")[index]])

    print("Seeding System Architecture — enabling the module, then a small Falcon-3 block diagram: a drone System with"
          " airframe electronics (flight controller, GPS, IMU, telemetry radio) and a ground-station service, joined by"
          " SPI, UART and REST connections...")
    architecture_counts = seed_architecture(h_pm, org["id"], drone["id"])

    # The project of this product's own records (requirements, decisions, SOC 2 assessment); a module of its own
    # because it loads a large fixture generated from the repository's documents.
    import seed_repo_demo

    repo_counts = seed_repo_demo.seed_repo_demo(
        h_pm, org, admin_user_id=demo_admin["user_id"],
        member_user_ids=[demo_engineer["user_id"], demo_stakeholder["user_id"]],
    )

    # Four further example templates (Software delivery, Compliance readiness, Research and discovery, Hardware design).
    import seed_template_projects

    seed_template_projects.seed_template_projects(h_pm, org, owner_id=demo_admin["user_id"])

    print()
    print("Done. Demo personas (all share one password: DemoDemo123! unless demo_setup.py rotated it):")
    print("  demo.admin@example.com       - org admin, project manager on all three projects")
    print("  demo.engineer@example.com    - stakeholder on Falcon-3/Solstice Cloud; direct project manager"
          " on Falcon-3 Avionics Subsystem (also reaches Falcon-3 via its member-source consumption)")
    print("  demo.stakeholder@example.com - stakeholder on Falcon-3/Solstice Cloud")
    print()
    print(f"Organisation: {ORG_NAME}")
    print(f"  Falcon-3 Inspection Drone  ({len(drone_reqs)} requirements, 1 change request pending, status: Active)")
    print("    - 3 requirement links (2 default 'Depends on', 1 custom 'Supersedes')")
    print("    - 2 requirement actions (1 completed review, 1 failed test, shared across 2 requirements)")
    print("    - Falcon-3 Avionics Subsystem (sub-project, mirror-all inherits from Falcon-3;"
          " Falcon-3 also consumes members from it — see docs/decisions.md's 'Hierarchical projects' entry)")
    print("    - Also consumes stakeholders (mirror_role) from the unrelated Solstice Cloud Platform"
          " project — the generalized (non-parent/child) member-source, see docs/decisions.md")
    print(f"  Solstice Cloud Platform    ({len(cloud_reqs)} requirements, 1 approved + 1 pending change request, status: Proposed)")
    print("    - Its own 'Stakeholders' group is defined as Falcon-3's direct members"
          " (the project-referencing group mechanism, see docs/decisions.md)")
    print("  Compliance standards: ASA-1 (assigned to Falcon-3 only), EN 60529 (opt-in, unassigned),"
          " ISO/IEC 27001 (applies to all projects — auto-assigned to Falcon-3 and Solstice Cloud,"
          " Falcon-3 Avionics Subsystem excepted)")
    print("  Decision Management (enabled org-wide): 5 Decisions on Falcon-3 (two more wait for a verdict, so the"
          " Decision register, Approval ageing, Decision log and Rationale coverage reports all have content) — the single-flight-controller"
          " decision (Approved, then Superseded), the dual-redundant decision that supersedes it (Approved),"
          " and an OTA-signing decision left in Draft; the single-flight-controller decision also addresses the"
          " accepted Pain Point and implements the GPS requirement through the generic link endpoint (a Pain Point ->"
          " Decision -> Requirement chain, readable as a link graph from any of the three), and the org has a"
          " restricted link type ('Is validated in simulation by', requirement -> action only)")
    print("  Context & Strategy (enabled org-wide): 1 organisation Strategy (Active) and 1 project Strategy on"
          " Falcon-3 (Active), tracing the org's market-share objective down to the dual-redundant contract win;"
          " 1 organisation Future State and 1 Active project Future State on Falcon-3 (plus a Draft one with a"
          " passed target date and no success measures), each Active one linked to the"
          " Strategy it elaborates via a real 'Defines' relationship; 7 Pain Points on Falcon-3"
          " (Accepted->Addressed, Rejected with a real 'Drives' link back to the Falcon-3 Strategy, and Duplicate"
          " with a real 'Duplicate of' link to the canonical Pain Point, plus four demonstrating per-persona"
          " scoring: scored across personas with a BVLOS-pilot Blocker, scored for all personas, an intentional"
          " limitation, and one unscored; Falcon-3 defaults to the Severity x Frequency model); 1 organisation Guiding Principle (Active,"
          " linked to the org Strategy via a real 'Supports' relationship) and 1 project Guiding Principle (Active)"
          " on Falcon-3; and 3 Open Questions on Falcon-3 (one Ready for Decision, one Withdrawn, one open and overdue — the 'resolved by"
          " Decision' relationship stays reserved, see docs/decisions.md)")
    print("  Stakeholders & Personas (enabled org-wide): 3 organisation Personas (Field Inspector — Active, weight 3;"
          " Compliance Auditor — Draft, unweighted; Harbour Pilot — Active, hidden from Falcon-3) and 1 project Persona on Falcon-3 (BVLOS Remote"
          " Pilot — Active, weight 2), with a Falcon-3 weight override of 5 on Field Inspector that the Avionics sub-project inherits;"
          " plus 2 organisation Stakeholders (Pat Okafor, Regulator — High influence/Medium interest, quarterly, represents"
          " Compliance Auditor; and Lee Harbour, hidden from Falcon-3 to show per-project visibility) and 1 Falcon-3"
          " Stakeholder (Dana Whitfield, Customer, monthly, represents BVLOS Remote Pilot); plus 3 Falcon-3 Engagements (a"
          " quick email log; a focus group aimed at a Stakeholder group, with anonymous participants, prompts and a finding;"
          " and a March briefing that leaves Pat Okafor overdue on a quarterly cadence)")
    print("  Components: on Falcon-3, one Pain Point sits in Firmware / Safety and Avionics, one Risk in Avionics / Safety"
          " and one Persona in Propulsion (a requirement keeps its own component and category)")
    print("  Tags: Falcon-3 has a free vocabulary with colours (inherited by the Avionics sub-project); Solstice Cloud"
          " Platform is restricted to three listed tags")
    print("  Risk Management (enabled org-wide): 4 Risks on Falcon-3 (RSK-001 flight controller failure — High inherent,"
          " Medium residual; a supply-chain risk; the regulator risk, whose Rare x Catastrophic cell is pinned to High; and one"
          " Identified risk with no assessment), with the Likelihood x Consequence matrix and 12 default Risk types")
    print("  Evidence: every Falcon-3 requirement has a statement (six with equations); a Pain Point and the flight-controller Risk"
          " carry pictures and an SVG diagram; Pain Points, a Risk and a Decision are linked to requirements, so the"
          " 'Business Requirements Document (with evidence)' layout prints links, pictures and equations")
    print(f"  System Architecture (enabled org-wide): {architecture_counts['elements']} elements on Falcon-3 in a tree"
          f" (a System, a Subsystem, boards, sensors and a ground-station service, each with ports) and"
          f" {architecture_counts['connections']} typed connections between them")
    if repo_counts:
        print(f"  {seed_repo_demo.PROJECT_NAME}: " + ", ".join(f"{count} {name}" for name, count in repo_counts.items())
              + " — loaded from this repository's documents (docs/decisions.md, docs/requirements.md, docs/soc2/)")
    print("  Templates: 'Product Design template' (Usability and Accessibility Pain Point types, Cost of Delay ÷ job size scoring,"
          " no Risk Management or Compliance) and 'Project Management template' (Schedule, Budget and Resourcing Pain Point types,"
          " no Product Feedback or Stakeholders); 'Falcon-3 Operator App' was created from the first, with two Pain Points scored by WSJF")
    print("  More templates: " + ", ".join(repr(spec.name) for spec in seed_template_projects.SPECS)
          + " — each with its own stage workflow, vocabularies, overview dashboard and starter drafts")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
