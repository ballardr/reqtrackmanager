"""
Module: scripts.seed_demo_data

Seeds a realistic, presentable demo dataset — a fictional engineering
company ("Solstice Robotics") with three projects (one a sub-project of
another, demonstrating hierarchical projects), requirements at varied
lifecycle stages, an in-review and an approved change request, discussion
comments, custom fields, and a report branding template. Intended for
screenshots, demos, and (eventually) a public demo instance.

Design notes:
- Every object is created through the real HTTP API (not direct DB writes),
  same convention as scripts/seed_e2e_dataset.py, so this exercises the same
  code paths a real user would.
- Deliberately separate from seed_e2e_dataset.py: that dataset's org/persona
  names and content exist to give the Playwright suite fixed, predictable
  anchors (docs/e2e-workflows.md), not to look good in a screenshot. This
  one exists purely to look like a real, in-use product.
- Idempotent by skipping, same as the E2E seed: if "Solstice Robotics"
  already exists, exits without changes rather than creating a duplicate.
  This script does NOT attempt to wipe/reset existing demo data itself —
  there is no organisation-deletion endpoint (see docs/soc2/policies/
  data-retention-and-disposal-policy.md's Known Gaps), and this script only
  ever talks to the API, not the database directly. A full reset (for a
  future "resets nightly" public demo instance) is a database-level
  operation instead — see docs/deployment.md's "Demo instance" section for
  the documented recipe (`docker compose down -v && up -d --build`, then
  re-run this script against the fresh database).

Run via (from tests/container):
    docker compose exec backend python scripts/seed_demo_data.py

Login afterward as demo.admin@example.com / DemoDemo123! (org admin, project
manager on both projects) — see the printed summary at the end for every
persona and their role.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe123!"
PASSWORD = "DemoDemo123!"

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
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/users",
        json={"email": email, "display_name": display_name, "password": PASSWORD, "role": role},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_project(
    headers: dict, org_id: str, name: str, summary: str,
    *, parent_project_id: str | None = None, role_inheritance_mode: str | None = None, can_be_parent: bool = False,
) -> dict:
    payload: dict = {"organization_id": org_id, "name": name, "summary": summary}
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
    """Creates a project group explicitly. Projects no longer auto-create
    any groups on creation (follow-up UX batch Phase C, 2026-08-31 removed
    the four "standard" default groups — see docs/decisions.md), so any
    group this script wants to demonstrate (e.g. a cross-project source
    reference below) has to be created as its own explicit step now,
    rather than reached by name via a pre-existing default."""
    r = httpx.post(f"{BASE}/projects/{project_id}/groups", json={"name": name, "role": role}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


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


def create_stage(headers: dict, project_id: str, name: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/stages", json={"name": name}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def transition_stage(headers: dict, project_id: str, stage_id: str, new_status: str) -> None:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/stages/{stage_id}/transition",
        params={"new_status": new_status}, headers=headers, timeout=30,
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
    custom_fields: dict | None = None,
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements",
        json={
            "name": name, "reasoning": reasoning, "component_id": component_id, "category_id": category_id,
            "keywords": [], "custom_fields": custom_fields or {},
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def set_requirement_status(
    headers: dict, project_id: str, requirement: dict, status_value: str,
    *, review_date: str | None = None, reviewer_id: str | None = None,
) -> dict:
    """Direct edit setting `status` (and optionally a review schedule) on a
    still-unlocked requirement — mirrors what a PM moving a requirement
    through draft -> reviewed -> approved would actually click through."""
    body = {
        "name": requirement["name"], "reasoning": requirement["reasoning"],
        "clarification": requirement.get("clarification", ""),
        "component_id": requirement["component_id"], "category_id": requirement["category_id"],
        "owner_id": requirement.get("owner_id") or requirement["creator_id"],
        "status": status_value, "keywords": requirement.get("keywords", []),
        "custom_fields": requirement.get("custom_fields", {}),
        "change_note": f"Marked {status_value} during scoping.",
    }
    if review_date is not None:
        body["review_date"] = review_date
    if reviewer_id is not None:
        body["reviewer_id"] = reviewer_id
    r = httpx.put(f"{BASE}/projects/{project_id}/requirements/{requirement['id']}", json=body, headers=headers, timeout=30)
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
    to click "Restore" on — see `POST .../unarchive`, added per the 2026-08
    UX audit roadmap ("archive was one-way for requirements, unlike
    projects")."""
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


def create_change_request(
    headers: dict, project_id: str, *, kind: str, requirement_id: str | None, proposed_name: str,
    proposed_reasoning: str, reason: str, component_id: str | None = None, category_id: str | None = None,
) -> dict:
    body = {
        "kind": kind, "requirement_id": requirement_id, "proposed_name": proposed_name,
        "proposed_reasoning": proposed_reasoning, "reason": reason,
    }
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
    action_title: str, action_description: str, action_type_id: str, reason: str, assignee_id: str | None = None,
) -> dict:
    """An ADD_ACTION change request (2026-08 UX audit roadmap item 514) —
    only valid once `requirement_id` is already locked (status APPROVED,
    completed or not — C-G-11 completion no longer changes `status`); see
    `create_change_request`'s sibling helpers, which each already require
    the same, for a requirement to target with this."""
    body = {
        "kind": "add_action", "requirement_id": requirement_id, "reason": reason,
        "proposed_action_title": action_title, "proposed_action_description": action_description,
        "proposed_action_type_id": action_type_id, "proposed_action_assignee_id": assignee_id,
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


def create_cr_task(headers: dict, project_id: str, cr_id: str, description: str, assignee_id: str | None = None, due_date: str | None = None) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/change-requests/{cr_id}/tasks",
        json={"description": description, "assignee_id": assignee_id, "due_date": due_date},
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


def create_and_link_action(
    headers: dict, project_id: str, requirement_id: str, *, title: str, description: str, action_type_id: str,
    assignee_id: str | None = None, due_date: str | None = None,
) -> dict:
    r = httpx.post(
        f"{BASE}/projects/{project_id}/requirements/{requirement_id}/actions/create-and-link",
        json={
            "title": title, "description": description, "action_type_id": action_type_id,
            "assignee_id": assignee_id, "due_date": due_date,
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
            "assignee_id": action.get("assignee_id"), "due_date": action.get("due_date"),
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
    "Restore" on — see `POST .../unarchive`, added per the 2026-08 UX audit
    roadmap ("archive was one-way for actions, unlike projects")."""
    r = httpx.post(f"{BASE}/projects/{project_id}/actions/{action_id}/archive", headers=headers, timeout=30)
    r.raise_for_status()


def create_report_template(headers: dict, org_id: str, *, name: str, accent_color_hex: str, footer_text: str) -> dict:
    r = httpx.post(
        f"{BASE}/orgs/{org_id}/report-templates",
        json={
            "name": name, "accent_color_hex": accent_color_hex, "include_cover_page": True,
            "include_logo": False, "footer_text": footer_text,
        },
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
     "threshold removes reliance on the operator noticing in time.", "FW", "SAF", "approved", {}),
    ("Provide a minimum flight time of 42 minutes at an 800g payload",
     "42 minutes covers the median inspection route length (per Q3 fleet telemetry) with enough "
     "margin for a return-to-home from the furthest point on the route without requiring a battery swap.",
     "PR", "PERF", "approved", {}),
    ("Withstand sustained wind gusts of up to 45 km/h without loss of stability",
     "Coastal and offshore inspection sites regularly see gusts in this range; grounding the fleet "
     "below this threshold would make several existing customer sites unviable.", "AF", "FN", "reviewed", {}),
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


def seed_project(
    headers: dict, project: dict, components: dict[str, dict], categories: dict[str, dict[str, dict]],
    specs: list[tuple], demo_admin_id: str,
) -> dict[str, dict]:
    by_name = {}
    for name, reasoning, comp_key, cat_key, status_value, extra in specs:
        req = create_requirement(
            headers, project["id"], name=name, reasoning=reasoning,
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

    print("Branding a report template...")
    create_report_template(
        h_pm, org["id"], name="Solstice Standard Report", accent_color_hex="#0F62FE",
        footer_text="Solstice Robotics — Confidential",
    )

    print("Setting organisation outgoing-email branding...")
    httpx.put(
        f"{BASE}/orgs/{org['id']}/branding",
        json={
            "accent_color_hex": None, "header_title": None,
            "email_footer_company_name": "Solstice Robotics, Inc.",
            "email_footer_website": "https://solsticerobotics.example.com",
            "email_footer_address": "400 Aerodrome Way, Suite 210\nAustin, TX 78701",
        },
        headers=h_pm, timeout=30,
    ).raise_for_status()

    print("Adding a custom requirement link type...")
    # Beyond the 12 seeded defaults (C-G-09) — demonstrates that an
    # organisation can extend the link-type vocabulary with its own.
    supersedes_link_type = create_link_type(h_pm, org["id"], forward_name="Supersedes", reverse_name="Is superseded by")
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
    create_stage(h_pm, drone["id"], "Verification & Validation")
    transition_stage(h_pm, drone["id"], drone_design["id"], "review")

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

    print("Creating and linking requirement actions on Falcon-3 (review/test tasks)...")
    drone_action_types = {t["name"]: t for t in httpx.get(f"{BASE}/projects/{drone['id']}/action-types", headers=h_pm, timeout=30).json()}
    # `remote_id_req` is seeded directly into "complete" (DRONE_REQUIREMENTS,
    # above) — approved and marked completed (C-G-11), so already locked
    # (status stays APPROVED throughout), so adding an action to it goes
    # through an ADD_ACTION change request (2026-08 UX audit roadmap item
    # 514) rather than the direct create-and-link call every other action
    # below still uses on its still-draft target requirement.
    firmware_review_title = "Review remote-ID firmware module against FAA rule text"
    firmware_review_cr = create_add_action_change_request(
        h_pm, drone["id"], remote_id_req["id"],
        action_title=firmware_review_title,
        action_description="Line-by-line review of the broadcast module against the published Part 107 remote "
        "identification rule, ahead of the compliance deadline.",
        action_type_id=drone_action_types["Review"]["id"],
        reason="Compliance deadline requires a documented review of the broadcast module, not just informal sign-off.",
        assignee_id=demo_engineer["user_id"],
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

    wind_test = create_and_link_action(
        h_pm, drone["id"], drone_reqs["Withstand sustained wind gusts of up to 45 km/h without loss of stability"]["id"],
        title="Wind tunnel stability test at 45 km/h sustained gust",
        description="Bench validation of airframe stability at the specified sustained gust threshold, "
        "ahead of the Verification & Validation stage.",
        action_type_id=drone_action_types["Test"]["id"], assignee_id=demo_stakeholder["user_id"],
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
    )
    submit_change_request(h_pm, drone["id"], drone_cr["id"])
    add_cr_comment(h(login("demo.stakeholder@example.com", PASSWORD)), drone["id"], drone_cr["id"],
                    "38 minutes still clears every current route's return-to-home margin per the Q3 telemetry — no objection from the ops side.")
    cast_vote(h(login("demo.stakeholder@example.com", PASSWORD)), drone["id"], drone_cr["id"], "approve",
              "Confirmed against current route data.")
    create_cr_task(h_pm, drone["id"], drone_cr["id"], "Update the customer-facing spec sheet once approved.",
                   assignee_id=demo_engineer["user_id"], due_date=(date.today() + timedelta(days=7)).isoformat())

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
    avionics_components = {"SN": create_component(h_pm, avionics["id"], "Sensors", "SN")}
    avionics_categories = create_categories_for_components(h_pm, avionics["id"], avionics_components, {"SN": ["PERF", "SAF", "FN"]})
    seed_project(h_pm, avionics, avionics_components, avionics_categories, AVIONICS_REQUIREMENTS, demo_admin["user_id"])

    print("Creating 'Solstice Cloud Platform'...")
    cloud = create_project(
        h_pm, org["id"], "Solstice Cloud Platform",
        "Fleet telemetry ingestion, live tracking, and reporting backend for the Falcon fleet.",
    )
    assign_project_role(h_pm, cloud["id"], demo_engineer["user_id"], "stakeholder")
    assign_project_role(h_pm, cloud["id"], demo_stakeholder["user_id"], "stakeholder")

    print("Demonstrating the generalized cross-project RBAC mechanisms (docs/decisions.md) — Falcon-3 and Solstice"
          " Cloud Platform are unrelated projects (no parent/child relationship), unlike Falcon-3/Avionics above...")
    # Generalized member-source: Falcon-3 additionally consumes stakeholders
    # (only — mirror_role, not every role) from the unrelated Solstice Cloud
    # Platform project, so demo_stakeholder's real stakeholder role on Cloud
    # also reaches Falcon-3 without a second, duplicate direct grant there.
    add_member_source(h_pm, drone["id"], cloud["id"], mirror_mode="mirror_role", mirror_filter_role="stakeholder")
    # Project-referencing group: Solstice Cloud Platform gets its own
    # explicit "Stakeholders" group (no default group exists to reach by
    # name any more — Phase C, follow-up UX batch, 2026-08-31), defined as
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
    create_stage(h_pm, cloud["id"], "Hardening")
    transition_stage(h_pm, cloud["id"], cloud_dev["id"], "review")

    print("Seeding Solstice Cloud Platform requirements...")
    cloud_reqs = seed_project(h_pm, cloud, cloud_components, cloud_categories, CLOUD_REQUIREMENTS, demo_admin["user_id"])

    print("Opening and approving a change request on Solstice Cloud Platform...")
    # A modify change request can only target an already-locked requirement
    # (2026-08 UX audit roadmap, "No requirement approval action; change
    # requests can target draft requirements") — already true here, since
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
    # 2026-08 UX audit roadmap item 514: once a requirement is locked
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
        assignee_id=demo_engineer["user_id"],
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

    print()
    print("Done. Demo personas (all password: DemoDemo123!):")
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


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
