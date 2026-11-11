"""
Module: scripts.seed_template_projects

Seeds four example template projects in the demo organisation: Software delivery, Compliance readiness, Research and
discovery and Hardware design (an IoT data logger). Each shows a different shape of project setup.

Responsibilities:
- Create each template through the real HTTP API with the helpers of `seed_demo_data`, so the usual validation,
  versioning and audit apply.
- Give every template its own enabled modules, stage workflow with phase kinds, component phases, Pain Point
  vocabulary, action, decision and risk types, scoring model, overview dashboard and starter drafts.
- Be idempotent by skipping: a template whose project name exists is left unchanged.

Design decisions:
- Starter records are left as drafts (a template copies records back to fresh drafts, never an approval).
- Every template has its own workflow so the example workflows differ by phase kinds, not only by name.
- Components and categories are the only per-requirement structure; the specs below are plain data and one generic
  builder applies them, so a further template is a spec, not new code.

External dependencies: `httpx` and the helpers of `seed_demo_data`.

Run from `tests/container` (after `seed_demo_data.py`, which also calls it):
    docker compose exec backend python scripts/seed_template_projects.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import httpx
import seed_demo_data as base

MODULES = ("decisions", "context_strategy", "risk_management", "stakeholders", "compliance")


@dataclass
class TemplateSpec:
    """The plain data one template project is built from.

    Attributes:
        name: Project name (ends with "template").
        summary: One sentence shown in the project list.
        modules_off: Module keys switched off in the project.
        workflow: Stage workflow name and its `(phase, kind)` pairs, in order.
        stages: Stage names; each follows the workflow.
        components: Component prefix -> (name, category keys of `seed_demo_data.CATEGORY_DEFS`).
        hide_pain_point_types: Organisation default Pain Point types hidden in the project.
        pain_point_types: Project-only Pain Point types and their definitions.
        action_types: Project-only action types.
        decision_types: Project-only decision types.
        risk_types: Project-only risk types.
        scoring_model: Pain Point default scoring model key, or None for the platform default.
        custom_fields: `(name, options)` of list custom fields on requirements.
        widgets: The project's overview dashboard widgets.
        requirements: `(name, reasoning, component prefix, category key)` starter drafts.
    """

    name: str
    summary: str
    modules_off: tuple[str, ...]
    workflow: tuple[str, list[tuple[str, str]]]
    stages: tuple[str, ...]
    components: dict[str, tuple[str, list[str]]]
    hide_pain_point_types: list[str]
    pain_point_types: dict[str, str]
    action_types: tuple[str, ...]
    decision_types: tuple[str, ...]
    risk_types: tuple[str, ...]
    scoring_model: str | None
    custom_fields: tuple[tuple[str, list[str]], ...]
    widgets: list[dict]
    requirements: tuple[tuple[str, str, str, str], ...]


def _tile(widget_id: str, title: str, record_type: str, width: int = 3) -> dict:
    return {
        "id": widget_id,
        "type": "metric_tile",
        "title": title,
        "width": width,
        "height": 2,
        "visible": True,
        "config": {"metric": "record_count", "params": {"record_type": record_type}},
    }


def _text(widget_id: str, title: str, markdown: str, width: int = 6) -> dict:
    return {"id": widget_id, "type": "text", "title": title, "width": width, "height": 3, "visible": True, "config": {"markdown": markdown}}


SOFTWARE = TemplateSpec(
    name="Software delivery template",
    summary="Starting point for a software product: a release train through code review, with Reliability, Performance and Technical debt types",
    modules_off=("compliance", "stakeholders"),
    workflow=(
        "Release train",
        [
            ("Backlog", "open"),
            ("Build", "open"),
            ("Code review", "review"),
            ("Release candidate", "locked"),
            ("Released", "closed"),
        ],
    ),
    stages=("Version 1.0", "Version 1.1"),
    components={
        "API": ("Service API", ["FN", "PERF", "SEC"]),
        "WEB": ("Web client", ["FN", "PERF"]),
        "PLT": ("Platform", ["REL", "SEC"]),
    },
    hide_pain_point_types=["Market", "Operator"],
    pain_point_types={
        "Reliability": "The product fails, loses data or is unavailable for the people who depend on it.",
        "Performance": "A task is slower than the people doing it can accept.",
        "Technical debt": "The way the code is built slows every later change.",
    },
    action_types=("Spike", "Technical debt", "Release task"),
    decision_types=("Technology choice", "Release policy"),
    risk_types=("Dependency",),
    scoring_model="wsjf",
    custom_fields=(("Target release", ["1.0", "1.1", "Later"]),),
    widgets=[
        {
            "id": "completion",
            "type": "gauge",
            "title": "Release readiness",
            "width": 3,
            "height": 4,
            "visible": True,
            "config": {"metric": "requirement_completed_percent", "minimum": 0, "maximum": 100, "warning": 60, "critical": 30, "direction": "below"},
        },
        _tile("pain-points", "Pain Points raised", "pain_point"),
        _tile("decisions", "Decisions recorded", "decision"),
        {"id": "stages", "type": "stage_progress", "title": "Stage progress", "width": 6, "height": 4, "visible": True, "config": {}},
        _text(
            "note",
            "How this template is meant to be used",
            "Each **stage** is a release. Move a stage to *Code review* before it is locked as a release candidate.",
        ),
    ],
    requirements=(
        (
            "Respond to a read request in under 300 ms at the 95th percentile",
            "Slow reads are the most common cause of abandoned sessions.",
            "API",
            "PERF",
        ),
        (
            "Reject a request with an invalid token before any record is read",
            "Authorisation checks that run late leak the existence of records.",
            "API",
            "SEC",
        ),
        ("Show the last saved state after a lost connection", "People lose work when a screen silently discards edits.", "WEB", "FN"),
        ("Restore the service from backup within 4 hours", "A stated recovery time makes the backup test meaningful.", "PLT", "REL"),
    ),
)

COMPLIANCE = TemplateSpec(
    name="Compliance readiness template",
    summary="Starting point for preparing an audit against an information security standard: gap analysis, remediation and evidence.",
    modules_off=("product_feedback", "stakeholders"),
    workflow=(
        "Audit readiness",
        [
            ("Gap analysis", "open"),
            ("Remediation", "open"),
            ("Evidence review", "review"),
            ("Audit window", "locked"),
            ("Certified", "closed"),
        ],
    ),
    stages=("Readiness assessment", "Audit"),
    components={
        "POL": ("Policies", ["REG", "FN"]),
        "TEC": ("Technical controls", ["SEC", "REL"]),
        "PPL": ("People", ["REG"]),
    },
    hide_pain_point_types=["Market", "User", "Operator"],
    pain_point_types={
        "Control gap": "A control the standard requires is missing or not operating.",
        "Evidence gap": "A control operates, but nothing shows it to an auditor.",
    },
    action_types=("Remediation", "Evidence request", "Policy review"),
    decision_types=("Risk acceptance", "Scope"),
    risk_types=("Control failure",),
    scoring_model=None,
    custom_fields=(("Control owner team", ["Engineering", "People", "Facilities", "Security"]),),
    widgets=[
        {"id": "standards", "type": "compliance:standards_status", "title": "Standards", "width": 12, "height": 2, "visible": True, "config": {}},
        _tile("evidence", "Evidence records", "compliance_evidence"),
        _tile("risks", "Risks identified", "risk"),
        _tile("decisions", "Risk acceptances and scope decisions", "decision"),
        {"id": "stages", "type": "stage_progress", "title": "Stage progress", "width": 6, "height": 4, "visible": True, "config": {}},
        _text(
            "note",
            "How this template is meant to be used",
            "Assess every criterion of the assigned standard, raise a Risk for each gap and record accepted risks as Decisions.",
        ),
    ],
    requirements=(
        (
            "Review every information security policy once a year",
            "A policy that is not reviewed describes a company that no longer exists.",
            "POL",
            "REG",
        ),
        ("Revoke a leaver's access within one working day", "Access that outlives employment is the most common audit finding.", "TEC", "SEC"),
        ("Log every change to production configuration", "An audit trail is the only evidence that changes were authorised.", "TEC", "REL"),
        ("Train every employee on security awareness at joining and yearly", "Untrained staff are the usual route into an incident.", "PPL", "REG"),
    ),
)

RESEARCH = TemplateSpec(
    name="Research and discovery template",
    summary="Starting point for learning from people before building: personas, stakeholders, needs, engagements and open questions.",
    modules_off=("risk_management", "compliance"),
    workflow=(
        "Research cycle",
        [
            ("Planning", "open"),
            ("Fieldwork", "open"),
            ("Synthesis", "review"),
            ("Playback", "locked"),
            ("Closed", "closed"),
        ],
    ),
    stages=("Discovery round 1", "Discovery round 2"),
    components={"DSC": ("Discovery", ["FN"]), "SYN": ("Synthesis", ["FN"])},
    hide_pain_point_types=["Market"],
    pain_point_types={"Workaround": "People use a spreadsheet, a paper form or another tool to do what the product should do."},
    action_types=("Interview", "Analysis", "Playback"),
    decision_types=("Research method", "Scope"),
    risk_types=(),
    scoring_model=None,
    custom_fields=(("Evidence strength", ["Anecdote", "Repeated", "Measured"]),),
    widgets=[
        _tile("needs", "Needs captured", "stakeholder_need"),
        _tile("engagements", "Engagements logged", "engagement"),
        _tile("questions", "Open questions", "open_question"),
        _tile("pain-points", "Pain Points", "pain_point"),
        {
            "id": "types",
            "type": "status_chart",
            "title": "Records by type",
            "width": 6,
            "height": 4,
            "visible": True,
            "config": {"metric": "records_by_type", "chart": "bar"},
        },
        _text(
            "note",
            "How this template is meant to be used",
            "Log each conversation as an **engagement**, record what was learned as findings and answer the open questions before deciding.",
        ),
    ],
    requirements=(
        (
            "Interview at least five people from each persona before a decision on scope",
            "Fewer than five conversations repeat one person's view.",
            "DSC",
            "FN",
        ),
        ("Record the consent given for every recorded session", "Recordings without consent cannot be shared with the team.", "DSC", "FN"),
        ("Play findings back to participants within two weeks", "Participants who never hear back stop taking part.", "SYN", "FN"),
    ),
)

HARDWARE = TemplateSpec(
    name="Hardware design template",
    summary="Starting point for an embedded hardware product such as an IoT data logger: design gates, prototypes, supply risk and verification.",
    modules_off=("product_feedback", "compliance"),
    workflow=(
        "Hardware design gates",
        [
            ("Concept", "open"),
            ("Schematic design", "open"),
            ("Design review", "review"),
            ("Prototype build", "locked"),
            ("Validation", "on_hold"),
            ("Production release", "closed"),
        ],
    ),
    stages=("Prototype A", "Production"),
    components={
        "SNS": ("Sensor front end", ["PERF", "FN"]),
        "PWR": ("Power", ["PERF", "SAF"]),
        "FW": ("Firmware", ["FN", "REL"]),
        "RF": ("Connectivity", ["PERF", "REG"]),
        "ENC": ("Enclosure", ["SAF", "REG"]),
    },
    hide_pain_point_types=["Market", "User"],
    pain_point_types={
        "Field failure": "A unit stops logging, loses data or drifts out of calibration after deployment.",
        "Power budget": "The unit runs out of energy sooner than its target life.",
    },
    action_types=("Prototype build", "Bench test", "Supplier query"),
    decision_types=("Component selection", "Supplier"),
    risk_types=("Single source",),
    scoring_model=None,
    custom_fields=(("Verification method", ["Test", "Inspection", "Analysis", "Demonstration"]),),
    widgets=[
        {
            "id": "completion",
            "type": "gauge",
            "title": "Design completion",
            "width": 3,
            "height": 4,
            "visible": True,
            "config": {"metric": "requirement_completed_percent", "minimum": 0, "maximum": 100, "warning": 50, "critical": 25, "direction": "below"},
        },
        {
            "id": "power",
            "type": "metric_tile",
            "title": "Power requirements",
            "width": 3,
            "height": 2,
            "visible": True,
            "config": {"metric": "record_count", "params": {"record_type": "requirement", "filters": {"component": ["PWR"]}}},
        },
        _tile("risks", "Risks identified", "risk"),
        {"id": "stages", "type": "stage_progress", "title": "Stage progress", "width": 6, "height": 4, "visible": True, "config": {}},
        _text(
            "note",
            "How this template is meant to be used",
            "Each requirement names how it is verified. Raise a **Risk** for every part with a single source before the design review.",
        ),
    ],
    requirements=(
        (
            "Log one temperature and humidity sample every 5 minutes for 24 months",
            "The logging interval and life together size the memory and the battery.",
            "SNS",
            "PERF",
        ),
        (
            "Hold temperature accuracy within 0.5 °C from −20 °C to 60 °C",
            "Accuracy outside the stated range makes the log unusable as evidence.",
            "SNS",
            "PERF",
        ),
        ("Run for 24 months on one primary cell", "A replaced battery is a site visit for every unit.", "PWR", "PERF"),
        ("Disconnect the battery safely on a short circuit", "A shorted cell in a sealed enclosure is a fire risk.", "PWR", "SAF"),
        (
            "Store samples through a power loss and upload them when the link returns",
            "A gap in the log is the failure customers notice first.",
            "FW",
            "REL",
        ),
        (
            "Update firmware over the air and keep the previous image on failure",
            "A failed update must not leave a unit that cannot be reached.",
            "FW",
            "FN",
        ),
        (
            "Keep a link budget of 10 dB at the edge of coverage",
            "A margin absorbs the loss of an enclosure and of a hand placed over the antenna.",
            "RF",
            "PERF",
        ),
        ("Meet the radio regulations of every market it is sold in", "A product that cannot be sold in a market has no market.", "RF", "REG"),
        ("Keep the sensor dry at IP67", "Condensation is the usual cause of drift in a humidity sensor.", "ENC", "SAF"),
    ),
)

SPECS: tuple[TemplateSpec, ...] = (SOFTWARE, COMPLIANCE, RESEARCH, HARDWARE)


def project_exists(headers: dict, org_id: str, name: str) -> bool:
    """Tells whether a project of this name exists in the organisation.

    Args:
        headers: Authorization headers.
        org_id: The organisation's id.
        name: The project name.

    Returns:
        True when a project with exactly this name is listed.
    """
    found = httpx.get(
        f"{base.BASE}/projects",
        headers=headers,
        params={"organization_id": org_id, "search": name, "include_templates": True},
        timeout=30,
    ).json()
    return any(project["name"] == name for project in found)


def add_vocabulary(headers: dict, project_id: str, kind: str, names: tuple[str, ...]) -> None:
    """Adds project-only action, decision or risk types.

    Args:
        headers: Authorization headers of the project manager.
        project_id: The project's id.
        kind: `action`, `decision` or `risk`.
        names: The type names to add.

    Raises:
        httpx.HTTPStatusError: If a type is refused.
    """
    url = {
        "action": f"{base.BASE}/projects/{project_id}/action-types",
        "decision": f"{base.BASE}/projects/{project_id}/modules/decisions/decision-types",
        "risk": f"{base.BASE}/projects/{project_id}/modules/risk_management/risk-types",
    }[kind]
    for name in names:
        httpx.post(url, json={"name": name}, headers=headers, timeout=30).raise_for_status()


def set_overview_layout(headers: dict, project_id: str, widgets: list[dict]) -> None:
    """Replaces the project's overview with these widgets (the project's own layout).

    Args:
        headers: Authorization headers of the project manager.
        project_id: The project's id.
        widgets: The widgets, in order.

    Raises:
        httpx.HTTPStatusError: If the layout is refused.
    """
    layout = httpx.get(f"{base.BASE}/projects/{project_id}/overview-layout", headers=headers, timeout=30)
    layout.raise_for_status()
    saved = httpx.put(
        f"{base.BASE}/projects/{project_id}/overview-layout",
        json={"scope": layout.json()["scope"], "widgets": widgets},
        headers=headers,
        timeout=30,
    )
    saved.raise_for_status()


def build_template(headers: dict, org: dict, spec: TemplateSpec) -> dict:
    """Creates one template project from its spec, with its starter requirements and the configuration around them.

    Args:
        headers: Authorization headers of the organisation administrator.
        org: The demo organisation.
        spec: What to create.

    Returns:
        The created project.

    Raises:
        httpx.HTTPStatusError: If any API call is refused.
    """
    project = base.create_project(headers, org["id"], spec.name, spec.summary, is_template=True)
    project_id = project["id"]
    for module_key in spec.modules_off:
        base.set_project_module(headers, project_id, module_key, False)
    base.hide_pain_point_types(headers, project_id, spec.hide_pain_point_types)
    base.add_pain_point_types(headers, project_id, spec.pain_point_types)
    add_vocabulary(headers, project_id, "action", spec.action_types)
    add_vocabulary(headers, project_id, "decision", spec.decision_types)
    if "risk_management" not in spec.modules_off:
        add_vocabulary(headers, project_id, "risk", spec.risk_types)
    if spec.scoring_model:
        base.set_project_scoring_default_model(headers, project_id, "pain_point", spec.scoring_model)
    for field_name, options in spec.custom_fields:
        base.create_custom_field(headers, project_id, "requirement", field_name, "list", options)
    workflow = base.create_org_workflow(headers, org["id"], *spec.workflow)
    for stage_name in spec.stages:
        base.create_stage(headers, project_id, stage_name, workflow["id"])
    base.enable_component_phases(headers, project_id)
    components = {prefix: base.create_component(headers, project_id, name, prefix) for prefix, (name, _) in spec.components.items()}
    categories = base.create_categories_for_components(
        headers,
        project_id,
        components,
        {prefix: keys for prefix, (_, keys) in spec.components.items()},
    )
    for name, reasoning, prefix, category_key in spec.requirements:
        base.create_requirement(
            headers,
            project_id,
            name=name,
            reasoning=reasoning,
            component_id=components[prefix]["id"],
            category_id=categories[prefix][category_key]["id"],
        )
    set_overview_layout(headers, project_id, spec.widgets)
    return project


def seed_software(headers: dict, project: dict, owner_id: str) -> None:
    """Adds the starter drafts of the Software delivery template: a decision, an action and a Pain Point.

    Args:
        headers: Authorization headers of the project manager.
        project: The template project.
        owner_id: The user who owns the starter records.
    """
    project_id = project["id"]
    decision_types = base.list_decision_types(headers, project_id)
    base.create_decision(
        headers,
        project_id,
        title="Choose the primary data store",
        decision_statement="Which database holds the product's records.",
        decision_type_id=decision_types["Technology choice"]["id"],
        owner_id=owner_id,
        options_considered="A relational database; a document database.",
    )
    action_types = {t["name"]: t for t in httpx.get(f"{base.BASE}/projects/{project_id}/action-types", headers=headers, timeout=30).json()}
    requirement = httpx.get(f"{base.BASE}/projects/{project_id}/requirements", headers=headers, timeout=30).json()[0]
    base.create_and_link_action(
        headers,
        project_id,
        requirement["id"],
        title="Measure read latency on the staging data set",
        description="Record the 95th percentile of the main read request before the first release candidate.",
        action_type_id=action_types["Spike"]["id"],
        assignee={"type": "user", "id": owner_id},
    )
    types = base.list_effective_pain_point_types(headers, project_id)
    base.create_pain_point(
        headers,
        project_id,
        pain_point_type_id=types["Technical debt"]["id"],
        title="Every change needs a manual deployment step",
        description="A release takes half a day because two steps are not automated.",
        source="Team retrospective",
        priority="medium",
    )


def seed_compliance(headers: dict, org: dict, project: dict, owner_id: str) -> None:
    """Adds the starter drafts of the Compliance readiness template: an example standard assigned to it, a risk and evidence.

    Args:
        headers: Authorization headers of the project manager.
        org: The demo organisation.
        project: The template project.
        owner_id: The user who owns the starter records.
    """
    project_id = project["id"]
    standard = base.create_compliance_standard(
        headers,
        org["id"],
        reference="ISB-1",
        name="Information security baseline (example)",
        description="A short example standard in the shape of SOC 2 or ISO 27001: groups of criteria, each assessed per project.",
    )
    version = base.list_compliance_versions(headers, org["id"], standard["id"])[0]
    for group_reference, group_name, criteria in (
        ("ISB-1.1", "Access control", ("Access is granted by role", "Access is removed when a person leaves")),
        ("ISB-1.2", "Operations", ("Changes to production are approved and logged", "Backups are tested")),
    ):
        group = base.create_compliance_requirement(
            headers,
            org["id"],
            standard["id"],
            version["id"],
            name=group_name,
            reference=group_reference,
            reasoning=f"Group {group_reference} of the example baseline.",
        )
        for index, name in enumerate(criteria, start=1):
            base.create_compliance_requirement(
                headers,
                org["id"],
                standard["id"],
                version["id"],
                name=name,
                reference=f"{group_reference}.{index}",
                reasoning=f"Criterion {group_reference}.{index} of the example baseline.",
                parent_requirement_id=group["id"],
            )
    base.publish_compliance_version(headers, org["id"], standard["id"], version["id"])
    base.assign_compliance_standard(headers, org["id"], project_id, standard["id"], version["id"])
    risk_types = base.list_effective_risk_types(headers, project_id)
    base.create_risk(
        headers,
        project_id,
        base.get_risk_levels(headers, project_id),
        risk_type_id=risk_types["Control failure"]["id"],
        owner={"type": "user", "id": owner_id},
        title="Leaver access is revoked late",
        statement="Access of a person who leaves stays active for days, which fails the access-removal criterion.",
        risk_event="A leaver's account is used after the last working day.",
    )
    base.create_compliance_evidence(
        headers, project_id, title="Access review record", notes="Quarterly export of accounts and roles, signed by the control owner."
    )


def seed_research(headers: dict, org: dict, project: dict, owner_id: str) -> None:
    """Adds the starter drafts of the Research and discovery template: persona, stakeholder, need, question and engagement.

    Args:
        headers: Authorization headers of the project manager.
        org: The demo organisation.
        project: The template project.
        owner_id: The user who owns the starter records.
    """
    project_id = project["id"]
    base.enable_research_extras(headers, org["id"])
    owner = {"type": "user", "id": owner_id}
    persona = base.create_project_persona(
        headers,
        project_id,
        name="Frequent user",
        role_title="Daily user of the product",
        description="Uses the product every working day and knows its workarounds.",
        goals="Finish the task without a second tool.",
        needs="A fast, predictable path through the main task.",
        frequency_of_use="Daily",
        weight=1.0,
        owner=owner,
    )
    stakeholder = base.create_stakeholder(
        headers,
        project_id=project_id,
        represents=(persona["id"],),
        name="Alex Example",
        owner=owner,
        stakeholder_type_id=base.get_stakeholder_type_id(headers, project_id=project_id, name="End user"),
        role="Team lead",
        interests="Less rework for the team.",
        contact_info="alex.example@example.com",
        target_cadence="monthly",
    )
    need = base.create_need(
        headers,
        project_id,
        holders=(("stakeholder", stakeholder["id"]), ("persona", persona["id"])),
        name="See what changed since yesterday",
        owner=owner,
        description="At the start of the day I must see what others changed, without opening every record.",
    )
    base.create_open_question(
        headers,
        project_id,
        question="Do people want a daily summary or a live feed of changes?",
        context="Two interviews asked for a summary; one asked for notifications.",
        evidence="Three interviews so far.",
        priority="medium",
    )
    base.create_engagement(
        headers,
        project_id,
        title="Interview: team lead",
        channel="interview",
        engagement_date="2026-11-02",
        summary="Alex described the morning routine of checking each record for changes.",
        notes="Recording kept with consent.",
        stakeholder_ids=[stakeholder["id"]],
        prompts=(("What do you do first each morning?", "Opens the team's board and looks for red items."),),
        findings=(
            {
                "title": "The morning check is manual",
                "description": "The team lead scans every record for changes.",
                "outcomes": (("raised", "stakeholder_need", need["id"]),),
            },
        ),
    )


def seed_hardware(headers: dict, project: dict, owner_id: str) -> None:
    """Adds the starter drafts of the Hardware design template: a decision, a risk, an action and a Pain Point.

    Args:
        headers: Authorization headers of the project manager.
        project: The template project.
        owner_id: The user who owns the starter records.
    """
    project_id = project["id"]
    decision_types = base.list_decision_types(headers, project_id)
    base.create_decision(
        headers,
        project_id,
        title="Select the microcontroller",
        decision_statement="Which microcontroller runs the logger firmware.",
        decision_type_id=decision_types["Component selection"]["id"],
        owner_id=owner_id,
        options_considered="A low-power Arm core; a RISC-V core with a built-in radio.",
    )
    risk_types = base.list_effective_risk_types(headers, project_id)
    base.create_risk(
        headers,
        project_id,
        base.get_risk_levels(headers, project_id),
        risk_type_id=risk_types["Single source"]["id"],
        owner={"type": "user", "id": owner_id},
        title="The humidity sensor has one supplier",
        statement="A shortage of the one qualified sensor stops production until a replacement is qualified.",
        risk_event="The supplier extends its lead time beyond 20 weeks.",
    )
    action_types = {t["name"]: t for t in httpx.get(f"{base.BASE}/projects/{project_id}/action-types", headers=headers, timeout=30).json()}
    requirement = next(
        r
        for r in httpx.get(f"{base.BASE}/projects/{project_id}/requirements", headers=headers, timeout=30).json()
        if r["name"].startswith("Run for 24 months")
    )
    base.create_and_link_action(
        headers,
        project_id,
        requirement["id"],
        title="Measure the sleep current on the first prototype",
        description="Record the average current over one logging cycle at 25 °C and compare it with the battery budget.",
        action_type_id=action_types["Bench test"]["id"],
        assignee={"type": "user", "id": owner_id},
    )
    types = base.list_effective_pain_point_types(headers, project_id)
    base.create_pain_point(
        headers,
        project_id,
        pain_point_type_id=types["Power budget"]["id"],
        title="Cold weather halves the battery life",
        description="Primary cells deliver far less energy near −20 °C, which shortens the logging life in unheated sites.",
        source="Field trial notes",
        priority="high",
    )


def seed_template_projects(headers: dict, org: dict, *, owner_id: str) -> dict[str, bool]:
    """Creates the four example template projects in the demo organisation, skipping any that exist.

    Args:
        headers: Authorization headers of the organisation administrator, who manages every template.
        org: The demo organisation.
        owner_id: The administrator's user id (owner of the starter records).

    Returns:
        Template name -> whether it was created now (False when it already existed).

    Raises:
        httpx.HTTPStatusError: If any API call is refused.
    """
    for module_key in MODULES:
        base.enable_module(headers, org["id"], module_key)
    created: dict[str, bool] = {}
    for spec in SPECS:
        if project_exists(headers, org["id"], spec.name):
            print(f"{spec.name!r} already exists. Skipping.")
            created[spec.name] = False
            continue
        print(f"Creating {spec.name!r}...")
        project = build_template(headers, org, spec)
        if spec is SOFTWARE:
            seed_software(headers, project, owner_id)
        elif spec is COMPLIANCE:
            seed_compliance(headers, org, project, owner_id)
        elif spec is RESEARCH:
            seed_research(headers, org, project, owner_id)
        else:
            seed_hardware(headers, project, owner_id)
        created[spec.name] = True
    return created


def main() -> int:
    """Seeds the templates into an organisation already created by `seed_demo_data`.

    Returns:
        0 on success, 1 when the demo organisation does not exist.
    """
    h_admin = base.h(base.login(base.ADMIN_EMAIL, base.ADMIN_PASSWORD))
    org = next((o for o in httpx.get(f"{base.BASE}/orgs", headers=h_admin, timeout=30).json() if o["name"] == base.ORG_NAME), None)
    if org is None:
        print(f"Organisation {base.ORG_NAME!r} not found; run seed_demo_data.py first.", file=sys.stderr)
        return 1
    headers = base.h(base.login("demo.admin@example.com", base.PASSWORD))
    users = {u["email"]: u for u in httpx.get(f"{base.BASE}/orgs/{org['id']}/users", headers=headers, timeout=30).json()}
    seed_template_projects(headers, org, owner_id=users["demo.admin@example.com"]["user_id"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.request.method} {exc.request.url} -> {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise
