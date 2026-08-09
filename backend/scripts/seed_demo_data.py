"""
Module: scripts.seed_demo_data

Seeds a realistic, presentable demo dataset — a fictional engineering
company ("Solstice Robotics") with two projects, requirements at varied
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


def create_project(headers: dict, org_id: str, name: str, summary: str) -> dict:
    r = httpx.post(
        f"{BASE}/projects", json={"organization_id": org_id, "name": name, "summary": summary},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return r.json()


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


def complete_requirement(headers: dict, project_id: str, requirement_id: str) -> None:
    r = httpx.post(f"{BASE}/projects/{project_id}/requirements/{requirement_id}/complete", headers=headers, timeout=30)
    r.raise_for_status()


def add_requirement_comment(headers: dict, project_id: str, requirement_id: str, body: str) -> dict:
    r = httpx.post(f"{BASE}/projects/{project_id}/requirements/{requirement_id}/comments", json={"body": body}, headers=headers, timeout=30)
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
    if component_id:
        body["proposed_component_id"] = component_id
    if category_id:
        body["proposed_category_id"] = category_id
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
                req = set_requirement_status(headers, project["id"], req, "approved")
                complete_requirement(headers, project["id"], req["id"])
                req["status"] = "completed"
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

    print("Creating 'Falcon-3 Inspection Drone'...")
    drone = create_project(
        h_pm, org["id"], "Falcon-3 Inspection Drone",
        "Autonomous multirotor platform for utility and infrastructure visual inspection.",
    )
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

    print("Approving the Scoping stage baseline for Falcon-3...")
    scoping_stage = httpx.get(f"{BASE}/projects/{drone['id']}/stages", headers=h_pm, timeout=30).json()[0]
    transition_stage(h_pm, drone["id"], scoping_stage["id"], "approved")

    print("Discussing a requirement on Falcon-3...")
    flight_time_req = drone_reqs["Provide a minimum flight time of 42 minutes at an 800g payload"]
    add_requirement_comment(
        h(login("demo.engineer@example.com", PASSWORD)), drone["id"], flight_time_req["id"],
        "Bench tests with the new obstacle-avoidance sensor payload are showing ~38 minutes, not 42 — "
        "filing a change request to true this up rather than let the two drift apart silently.",
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

    print("Creating 'Solstice Cloud Platform'...")
    cloud = create_project(
        h_pm, org["id"], "Solstice Cloud Platform",
        "Fleet telemetry ingestion, live tracking, and reporting backend for the Falcon fleet.",
    )
    assign_project_role(h_pm, cloud["id"], demo_engineer["user_id"], "stakeholder")
    assign_project_role(h_pm, cloud["id"], demo_stakeholder["user_id"], "stakeholder")
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
    print("  demo.admin@example.com       - org admin, project manager on both projects")
    print("  demo.engineer@example.com    - stakeholder on both projects")
    print("  demo.stakeholder@example.com - stakeholder on both projects")
    print()
    print(f"Organisation: {ORG_NAME}")
    print(f"  Falcon-3 Inspection Drone  ({len(drone_reqs)} requirements, 1 change request pending)")
    print(f"  Solstice Cloud Platform    ({len(cloud_reqs)} requirements, 1 approved + 1 pending change request)")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
