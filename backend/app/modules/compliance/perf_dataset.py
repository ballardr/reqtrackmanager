"""
Module: modules.compliance.perf_dataset

The dataset generators for the four compliance artefact types: the organisation's catalogue (standards, one
published version each, their requirements and required actions), each project's assignment of standards with one
assessment per requirement, required-action assessments, and evidence linked to assessments.

Responsibilities:
- `generate_compliance_requirements`: once per organisation (in its first project), write the catalogue and
  remember its ids in `ctx.org_state`.
- `generate_project_compliance`: assign a few standards to the project and write a `ProjectComplianceRequirement`
  for every requirement of each, with a mix of statuses and approval states.
- `generate_required_action_assessments`: one assessment per required action of an assigned requirement.
- `generate_evidence`: evidence records (with the project's `EVD` codes) linked to assessments.

Design decisions:
- Compliance volume follows the catalogue and the projects, not the requirement count (the dataset spec's
  `compliance` section): a project holds `standards_per_project * requirements_per_standard` assessments at any tier.
  Only evidence scales with the project's requirements.
- A compliance requirement and its project assessment have no human code (the documented exemption); evidence does.

Dependencies: `perf_dataset.records`, this module's models and enums.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.modules.compliance.enums import (
    ComplianceApprovalState,
    ComplianceStandardApplicabilityDefault,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)
from app.modules.compliance.models import (
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT,
    EVIDENCE_CODE_PREFIX,
    ComplianceActionTypeDefinition,
    ComplianceEvidence,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.records import Partner, RecordBatch, add_tags, at_between, created_at, link_to_earlier, pick_weighted

EVIDENCE = "compliance_evidence"
REQUIREMENT = "compliance_requirement"
PROJECT_REQUIREMENT = ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT
ASSESSMENT = "compliance_required_action_assessment"

_STATUS_MIX = (
    (ComplianceStatus.NOT_STARTED, 0.25), (ComplianceStatus.IN_PROGRESS, 0.2), (ComplianceStatus.COMPLIANT, 0.3),
    (ComplianceStatus.NON_COMPLIANT, 0.1), (ComplianceStatus.BLOCKED, 0.05), (ComplianceStatus.PENDING_REVIEW, 0.1),
)


def _delta(ctx: PerfProjectContext, start: dict[str, int]) -> dict[str, int]:
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def generate_compliance_requirements(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the organisation's catalogue once (in its first project) and publishes it in `ctx.org_state`.

    `ctx.org_state["compliance"]` is `{"versions": [version id], "requirements": {version id: [requirement id]},
    "required_actions": {requirement id: [required action id]}}`; every project's `ctx.shared[REQUIREMENT]` is the
    organisation's requirement ids.

    Args:
        ctx: The project's context.

    Returns:
        Rows written (empty for every project after the first of the organisation).
    """
    spec, rng, db = ctx.spec, ctx.rng, ctx.db
    if not spec.ratios.compliance:
        return {}
    catalogue = ctx.org_state.get("compliance")
    if catalogue is None:
        start = dict(ctx.counts)
        action_types = list(db.scalars(
            select(ComplianceActionTypeDefinition.id).where(ComplianceActionTypeDefinition.organization_id == ctx.organization_uuid)
        ))
        catalogue = {"versions": [], "requirements": {}, "required_actions": {}}
        standards, versions, requirements, actions = [], [], [], []
        for number in range(1, int(spec.ratios.compliance_setting("standards_per_org")) + 1):
            created, owner = created_at(rng, max_days=700), rng.choice(ctx.user_ids)
            standard_id, version_id = uuid_from(rng), uuid_from(rng)
            standards.append({
                "id": standard_id, "organization_id": ctx.organization_uuid, "reference": f"STD-{number:02d}",
                "name": f"Perf Standard {number}", "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=2),
                "issuing_organisation": "Perf Standards Body", "owner_type": "user", "owner_id": owner, "creator_id": owner,
                "is_archived": False, "archived_at": None, "archived_by": None,
                "applicability_default": ComplianceStandardApplicabilityDefault.OPT_IN, "created_at": created, "updated_at": created,
            })
            versions.append({
                "id": version_id, "standard_id": standard_id, "version_number": 1, "version_label": "1.0",
                "status": ComplianceStandardVersionStatus.PUBLISHED, "effective_date": created.date(),
                "change_note": "Initial version.", "summary": textgen.sentences(rng, 2), "created_by": owner,
                "published_at": created, "published_by": owner, "retired_at": None, "retired_by": None,
                "created_at": created, "updated_at": created,
            })
            catalogue["versions"].append(version_id)
            catalogue["requirements"][version_id] = []
            for order in range(int(spec.ratios.compliance_setting("requirements_per_standard"))):
                requirement_id = uuid_from(rng)
                catalogue["requirements"][version_id].append(requirement_id)
                requirements.append({
                    "id": requirement_id, "standard_version_id": version_id, "parent_requirement_id": None,
                    "cloned_from_requirement_id": None, "reference": f"{number}.{order + 1}", "name": textgen.title(rng),
                    "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
                    "reasoning": textgen.paragraphs(rng, empty_chance=0.3, short_max=2), "sort_order": order, "created_by": owner,
                    "clarification_count": 0, "last_clarified_at": None, "last_clarified_by": None, "last_clarification_note": "",
                    "created_at": created, "updated_at": created,
                })
                if action_types and rng.random() < spec.ratios.compliance_setting("required_action_fraction"):
                    action_id = uuid_from(rng)
                    catalogue["required_actions"][requirement_id] = [action_id]
                    actions.append({
                        "id": action_id, "requirement_id": requirement_id, "action_type_id": rng.choice(action_types),
                        "name": textgen.title(rng)[:120], "description": textgen.sentences(rng, 1),
                        "is_mandatory": rng.random() < 0.7, "sort_order": 0, "created_by": owner, "created_at": created, "updated_at": created,
                    })
        ctx.add_count("compliance_standards", insert_rows(db, ComplianceStandard, standards))
        ctx.add_count("compliance_standard_versions", insert_rows(db, ComplianceStandardVersion, versions))
        ctx.add_count("compliance_requirements", insert_rows(db, ComplianceRequirement, requirements))
        ctx.add_count("compliance_required_actions", insert_rows(db, ComplianceRequiredAction, actions))
        ctx.org_state["compliance"] = catalogue
        counts = _delta(ctx, start)
    else:
        counts = {}
    ctx.shared[REQUIREMENT] = [r for ids in catalogue["requirements"].values() for r in ids]
    return counts


def generate_project_compliance(ctx: PerfProjectContext) -> dict[str, int]:
    """Assigns standards to the project and writes one assessment per requirement of each."""
    rng, spec, db = ctx.rng, ctx.spec, ctx.db
    catalogue = ctx.org_state.get("compliance")
    if not spec.ratios.compliance or catalogue is None:
        return {}
    start = dict(ctx.counts)
    versions = catalogue["versions"]
    wanted = min(int(spec.ratios.compliance_setting("standards_per_project")), len(versions))
    offset = ctx.project.depth + len(ctx.org_state.setdefault("_assigned_projects", [])) % max(1, len(versions))
    ctx.org_state["_assigned_projects"].append(ctx.project.id)
    chosen = [versions[(offset + i) % len(versions)] for i in range(wanted)]
    assignments, assessments, ids = [], [], []
    assessment_requirement: dict[Any, Any] = {}
    for version_id in chosen:
        assigned = created_at(rng, max_days=400)
        assigner = rng.choice(ctx.user_ids)
        assignment_id = uuid_from(rng)
        assignments.append({
            "id": assignment_id, "project_id": ctx.project_uuid, "standard_version_id": version_id, "assigned_at": assigned,
            "assigned_by": assigner, "target_compliance_date": (assigned + timedelta(days=rng.randint(60, 400))).date(),
            "target_date_reminder_sent_at": None, "target_date_overdue_notified_at": None, "is_archived": False,
            "archived_at": None, "archived_by": None, "created_at": assigned, "updated_at": assigned,
        })
        for requirement_id in catalogue["requirements"][version_id]:
            status = pick_weighted(rng, _STATUS_MIX)
            assessed = status not in (ComplianceStatus.NOT_STARTED, ComplianceStatus.IN_PROGRESS)
            approved = status is ComplianceStatus.COMPLIANT and rng.random() < 0.6
            pcr_id = uuid_from(rng)
            ids.append(pcr_id)
            when = at_between(rng, assigned)
            person = rng.choice(ctx.user_ids)
            assessments.append({
                "id": pcr_id, "project_compliance_id": assignment_id, "requirement_id": requirement_id,
                "explicit_applicability": None, "justification": textgen.sentences(rng, 1) if assessed else "",
                "notes": textgen.paragraphs(rng, empty_chance=0.6, short_max=2), "compliance_status": status,
                "assessed_at": when if assessed else None, "assessed_by": person if assessed else None,
                "applicability_set_at": None, "applicability_set_by": None,
                "approval_state": ComplianceApprovalState.APPROVED if approved else (
                    ComplianceApprovalState.ASSESSED if assessed else ComplianceApprovalState.NOT_ASSESSED
                ),
                "approval_decided_at": when if approved else None, "approval_decided_by": rng.choice(ctx.user_ids) if approved else None,
                "decision_note": "", "created_at": assigned, "updated_at": when,
            })
            assessment_requirement[pcr_id] = requirement_id
    ctx.add_count("project_compliances", insert_rows(db, ProjectCompliance, assignments))
    ctx.add_count("project_compliance_requirements", insert_rows(db, ProjectComplianceRequirement, assessments))
    ctx.shared[PROJECT_REQUIREMENT] = ids
    ctx.org_state.setdefault("_pcr_requirement", {}).update(assessment_requirement)
    return _delta(ctx, start)


def generate_required_action_assessments(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes an assessment for each required action of an assessed requirement, some completed."""
    rng, db = ctx.rng, ctx.db
    catalogue = ctx.org_state.get("compliance")
    requirement_of = ctx.org_state.get("_pcr_requirement", {})
    if catalogue is None:
        return {}
    start = dict(ctx.counts)
    rows, ids = [], []
    for pcr_id in ctx.shared.get(PROJECT_REQUIREMENT, []):
        for action_id in catalogue["required_actions"].get(requirement_of.get(pcr_id), []):
            done = rng.random() < 0.4
            assignee = rng.choice(ctx.user_ids) if rng.random() < 0.7 else None
            created = created_at(rng, max_days=300)
            row_id = uuid_from(rng)
            ids.append(row_id)
            rows.append({
                "id": row_id, "project_compliance_requirement_id": pcr_id, "required_action_id": action_id,
                "assignee_type": "user" if assignee else None, "assignee_id": assignee,
                "due_date": (created + timedelta(days=rng.randint(10, 120))).date() if rng.random() < 0.6 else None,
                "due_reminder_sent_at": None, "overdue_notified_at": None, "is_completed": done,
                "completed_at": created + timedelta(days=5) if done else None,
                "completed_by": rng.choice(ctx.user_ids) if done else None,
                "notes": textgen.sentences(rng, 1) if done else "", "created_at": created, "updated_at": created,
            })
    ctx.add_count("compliance_required_action_assessments", insert_rows(db, ComplianceRequiredActionAssessment, rows))
    ctx.shared[ASSESSMENT] = ids
    return _delta(ctx, start)


def generate_evidence(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's evidence, linked (untyped) to assessments and required-action assessments."""
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(EVIDENCE, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, EVIDENCE, EVIDENCE_CODE_PREFIX, ComplianceEvidence)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng, max_days=400)
        title = textgen.title(rng)
        issued = (created - timedelta(days=rng.randint(0, 200))).date()
        archived = rng.random() < 0.03
        batch.add(
            {"title": title, "description": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
             "issuing_organisation": "Perf Auditor" if rng.random() < 0.6 else None, "issued_date": issued,
             "expiry_date": issued + timedelta(days=rng.randint(180, 900)) if rng.random() < 0.7 else None,
             "provided_by": creator, "provided_at": created, "notes": textgen.paragraphs(rng, empty_chance=0.6, short_max=1),
             "expiry_reminder_sent_at": None, "expiry_notified_at": None, "is_archived": archived,
             "archived_at": created + timedelta(days=90) if archived else None, "archived_by": creator if archived else None},
            creator=creator, at=created, title=title,
        )
    batch.write()
    add_tags(ctx, batch)
    link_to_earlier(
        ctx, batch,
        [Partner(PROJECT_REQUIREMENT, 0.7, untyped=True), Partner(ASSESSMENT, 0.3, untyped=True)],
    )
    return _delta(ctx, start)

