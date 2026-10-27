"""
Module: modules.risk_management.perf_dataset

The dataset generator for the `risk` artefact type: risks with their version history (ratings drawn from the
organisation's scoring levels), treatment links from requirements with verdicts, periodic reviews, comments, tags,
and links to other records.

Responsibilities:
- Write `risks`, `risk_versions`, `risk_treatment_assessments`, `risk_reviews`, `risk_comments`, treatment and
  cross-type `artefact_links`, tags and audit events, and the project's `risk` sequence counter.

Design decisions:
- Ratings use the real scoring levels of the organisation (seeded when the module is enabled), so rating
  computation reads the same rows it does in production use.
- A treatment link is a requirement that "Mitigates" the risk, the same family the application's treatment
  listing reads; a share carry a verdict (effective, ineffective, needs reassessment).

Dependencies: `perf_dataset.records`, this module's models, `services.scoring`, `services.link_types`.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.relationship import ArtefactLink
from app.modules.risk_management.enums import RiskReviewOutcome, RiskStatus, TreatmentAssessmentStatus, TreatmentStrategy
from app.modules.risk_management.models import (
    ProjectRiskType,
    Risk,
    RiskComment,
    RiskReview,
    RiskTreatmentAssessment,
    RiskTypeDefinition,
    RiskVersion,
)
from app.modules.risk_management.scoring import LEVEL_COLUMN_AXES, RISK_SCORING_SCHEME_KEY
from app.modules.risk_management.service import RISK_ARTEFACT_TYPE, RISK_CODE_PREFIX
from app.modules.risk_management.treatment import MITIGATES_FORWARD
from app.services.link_types import get_org_link_type
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.core import extra_versions
from app.services.perf_dataset.records import (
    RecordBatch,
    add_comments,
    add_tags,
    at_between,
    created_at,
    link_to_earlier,
    pick_weighted,
    project_type_ids,
)
from app.services.scoring import list_levels

_STATUS_MIX = (
    (RiskStatus.IDENTIFIED, 0.2), (RiskStatus.ASSESSED, 0.2), (RiskStatus.TREATMENT_PLANNED, 0.1),
    (RiskStatus.TREATMENT_IN_PROGRESS, 0.15), (RiskStatus.MITIGATED, 0.1), (RiskStatus.ACCEPTED, 0.1),
    (RiskStatus.CLOSED, 0.1), (RiskStatus.REALISED, 0.05),
)
_VERDICT_MIX = (
    (None, 0.4), (TreatmentAssessmentStatus.EFFECTIVE, 0.35), (TreatmentAssessmentStatus.INEFFECTIVE, 0.1),
    (TreatmentAssessmentStatus.NEEDS_REASSESSMENT, 0.15),
)


def generate_risks(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's risks and everything hanging off them.

    Args:
        ctx: The project's context; needs `ctx.shared["requirement"]` (treatment links) and, for cross-type links,
            the earlier types' ids.

    Returns:
        Rows written by table name.
    """
    rng, db = ctx.rng, ctx.db
    requirements = ctx.shared.get("requirement", [])
    count = ctx.spec.ratios.count_for("risk", len(requirements))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    levels = {axis: [lv.id for lv in rows] for axis, rows in list_levels(db, ctx.organization_uuid, RISK_SCORING_SCHEME_KEY).items()}
    risk_types = project_type_ids(ctx, ProjectRiskType, RiskTypeDefinition)
    mitigates = get_org_link_type(db, ctx.organization_uuid, MITIGATES_FORWARD)
    batch = RecordBatch.start(ctx, RISK_ARTEFACT_TYPE, RISK_CODE_PREFIX, Risk)
    links: list[dict] = []
    assessments: list[dict] = []
    reviews: list[dict] = []
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        final_status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        record_id = batch.new_id()
        title = textgen.title(rng)
        batch.add(
            {"id": record_id, "is_archived": archived, "archived_at": created + timedelta(days=60) if archived else None,
             "archived_by": creator if archived else None, "review_due_notified_for": None, "review_overdue_notified_for": None},
            creator=creator, at=created, title=title,
        )
        extra = extra_versions(rng, ctx.spec.ratios.versions_per_requirement)
        valid_from = created
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.8 else None
        review_date = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 700)) if rng.random() < 0.5 else None
        type_id = rng.choice(risk_types) if risk_types and rng.random() < 0.8 else None
        strategy = rng.choice(list(TreatmentStrategy)) if rng.random() < 0.6 else None
        chosen = {
            column: rng.choice(levels[axis]) if levels.get(axis) and rng.random() < 0.85 else None
            for column, axis in LEVEL_COLUMN_AXES.items()
        }
        statement = textgen.paragraphs(rng, empty_chance=0.05, short_max=2)
        cause = textgen.paragraphs(rng, empty_chance=0.2, short_max=2)
        for number in range(1, extra + 2):
            last = number == extra + 1
            author = creator if number == 1 else rng.choice(ctx.user_ids)
            next_from = valid_from + timedelta(hours=rng.uniform(1, 24 * 30))
            if number > 1:
                title = textgen.title(rng) if rng.random() < 0.4 else title
                cause = textgen.paragraphs(rng, empty_chance=0.2, short_max=2)
                batch.audit_event(record_id, "updated", author, valid_from, {"change_note": "Reassessed."})
            batch.satellite(RiskVersion, {
                "id": batch.new_id(), "risk_id": record_id, "version_number": number, "valid_from": valid_from,
                "valid_to": None if last else next_from, "title": title, "statement": statement, "cause": cause,
                "risk_event": textgen.sentences(rng, 1), "consequence": textgen.sentences(rng, rng.randint(1, 2)),
                "project_type_id": type_id, "treatment_strategy": strategy,
                "acceptance_criteria": textgen.paragraphs(rng, empty_chance=0.6, short_max=1), **chosen,
                "status": final_status if last else RiskStatus.IDENTIFIED,
                "owner_type": "user" if owner else None, "owner_id": owner, "review_date": review_date,
                "change_note": "Initial creation." if number == 1 else "Reassessed.", "created_by": author, "created_at": valid_from,
            })
            valid_from = next_from
        if review_date and rng.random() < 0.4:
            reviewed = at_between(rng, created)
            reviews.append({
                "id": uuid_from(rng), "risk_id": record_id, "risk_version_number": extra + 1, "reviewed_by": rng.choice(ctx.user_ids),
                "reviewed_at": reviewed, "outcome": rng.choice(list(RiskReviewOutcome)), "notes": textgen.sentences(rng, 2),
                "risk_status": final_status, "inherent_rating_label": None, "inherent_rating_score": None,
                "residual_rating_label": None, "residual_rating_score": None, "effective_treatment_count": 0,
                "scheduled_for": review_date, "next_review_date": review_date + timedelta(days=180),
            })
        if mitigates is not None and requirements:
            for requirement_id in rng.sample(requirements, min(rng.choice((0, 1, 1, 2, 3)), len(requirements))):
                link_id, author, at = uuid_from(rng), rng.choice(ctx.user_ids), at_between(rng, created)
                links.append({
                    "id": link_id, "source_type": "requirement", "source_id": requirement_id, "target_type": RISK_ARTEFACT_TYPE,
                    "target_id": record_id, "link_type_id": mitigates.id, "source_project_id": None, "target_project_id": None,
                    "created_by": author, "created_at": at, "updated_at": at,
                })
                verdict = pick_weighted(rng, _VERDICT_MIX)
                if verdict is not None:
                    assessments.append({
                        "id": uuid_from(rng), "link_id": link_id, "risk_id": record_id, "status": verdict, "assessed_by": author,
                        "assessed_at": at + timedelta(days=2), "rationale": textgen.sentences(rng, 1),
                        "reassessment_reason": textgen.sentences(rng, 1) if verdict is TreatmentAssessmentStatus.NEEDS_REASSESSMENT else "",
                        "created_at": at, "updated_at": at,
                    })
    batch.write()
    ctx.add_count("artefact_links", insert_rows(db, ArtefactLink, links))
    ctx.add_count("risk_treatment_assessments", insert_rows(db, RiskTreatmentAssessment, assessments))
    ctx.add_count("risk_reviews", insert_rows(db, RiskReview, reviews))
    add_comments(ctx, batch, RiskComment, "risk_id")
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement_action", 0.3), ("change_request", 0.1)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}

