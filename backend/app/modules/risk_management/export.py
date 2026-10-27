"""
Module: modules.risk_management.export

This module's contribution to the core org/project bundle export/import
(`app.services.org_export`/`project_export`), registered through
`ModuleOrgBundleHooks`/`ModuleProjectBundleHooks` on `MODULE_DEFINITION` rather
than those core files importing this module.

- Org level: the Risk type vocabulary.
- Project level: the project's type overrides and local types; each Risk (its
  current content and status, evidence attachments and review history); and its
  treatment links to Requirements with the verdict on each.

Design decisions (all Decided by: Agent):
- A Risk travels as its *current* content and status only, with its original
  `RSK-nnn` code kept so treatment links and anything citing the code still
  read. Version history, comments and comment attachments are not carried: a
  bundle is a migration artefact, and the imported Risk starts at version 1
  attributed to the importer where the author cannot be matched. Reviews are
  carried in full because they are the audit record of what was assessed and
  when; their rating snapshot is stored data, not re-derived.
- Ratings are never exported, being derived. Levels are carried by *axis and
  name* and matched to the target organisation's `risk` scoring levels; one the
  target lacks (renamed or deleted) is left unset with a warning, so the
  imported Risk is "not rated" on that axis rather than silently re-rated.
  Scoring configuration (levels, bands, cell ratings) is not part of a bundle.
- Only treatment-family and impact links *to Requirements in the same project*
  travel (matched by requirement code, as the core requirement links are).
  Links to Actions, Decisions, other Risks or another project cannot, because
  those records are not in the project bundle; they are dropped on export and
  documented rather than imported half-resolved.
- A verdict travels with its link, including `needs_reassessment` and its
  reason, so a bundle does not quietly turn an unresolved doubt into trust.
- Cross-references use portable keys, never database ids: type names, level
  axis+name, requirement codes, user emails; an owner is `{type, email | name}`
  (`services.principals`), and one the target cannot match is left unset with a
  warning. Bundles written before groups existed carry `owner_email`, still read.
- Org-level merge skips a type the organisation already has, so re-import is
  idempotent. Org-level files cannot travel (the org hook receives no bytes).

Dependencies: `app.services.bundle_common`, `app.services.relationships`, this
module's models and service.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.sequence import ProjectSequenceCounter
from app.models.user import User
from app.modules.risk_management.enums import (
    RiskReviewOutcome,
    RiskStatus,
    TreatmentAssessmentStatus,
    TreatmentStrategy,
)
from app.modules.risk_management.models import (
    ProjectRiskType,
    Risk,
    RiskFile,
    RiskReview,
    RiskTreatmentAssessment,
    RiskTypeDefinition,
    RiskVersion,
)
from app.modules.risk_management.scoring import LEVEL_COLUMN_AXES, RISK_SCORING_SCHEME_KEY
from app.modules.risk_management.service import RISK_ARTEFACT_TYPE, RISK_TYPES
from app.services.bundle_common import BundleImportWarnings, UserResolver, export_file_links, import_bundled_file, prime_file_links
from app.services.link_type_scope import resolve_link_type_scope
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.relationships import create_link, get_links_from_many, get_links_to_many
from app.services.scoring import list_levels, seed_missing_scoring_levels
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags

_TEXT_FIELDS = ("title", "statement", "cause", "risk_event", "consequence", "acceptance_criteria")
_REQUIREMENT = "requirement"


def _j(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's Risk types."""
    types = db.scalars(
        select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == org.id).order_by(RiskTypeDefinition.sort_order)
    ).all()
    return {"risk_types": [{"name": t.name, "sort_order": t.sort_order, "is_active": t.is_active} for t in types]}


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates Risk types, skipping names the
    organisation already has (so a fresh org's seeded defaults are not doubled)."""
    existing = {t.name for t in db.scalars(select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == org.id))}
    for t in data.get("risk_types", []):
        if t["name"] in existing:
            continue
        db.add(RiskTypeDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", len(existing)),
            is_active=t.get("is_active", True),
        ))
        existing.add(t["name"])
    db.flush()


# --- Project level: export ---------------------------------------------------


def _level_refs(db: Session, project: Project) -> dict[UUID, dict[str, str]]:
    """`{level id: {"axis", "name"}}` for the organisation's `risk` scoring levels."""
    return {
        level.id: {"axis": axis, "name": level.name}
        for axis, levels in list_levels(db, project.organization_id, RISK_SCORING_SCHEME_KEY).items() for level in levels
    }


def _treatment_json(
    db: Session, project: Project, risk_id: UUID, req_code: dict[UUID, str], link_type_names: dict[UUID, str],
    verdicts: dict[UUID, RiskTreatmentAssessment], emails: dict[UUID, str], risk_links: list[ArtefactLink],
) -> list[dict[str, Any]]:
    """The risk's same-project links to Requirements, each with its verdict (if any)."""
    out = []
    for link in sorted(risk_links, key=lambda lk: lk.created_at):
        if link.link_type_id is None:
            continue
        risk_is_source = (link.source_type, link.source_id) == (RISK_ARTEFACT_TYPE, risk_id)
        far_type, far_id = (link.target_type, link.target_id) if risk_is_source else (link.source_type, link.source_id)
        if far_type != _REQUIREMENT or far_id not in req_code:
            continue
        entry: dict[str, Any] = {
            "link_type_forward_name": link_type_names.get(link.link_type_id),
            "risk_is_source": risk_is_source, "requirement_unique_code": req_code[far_id],
            "created_by_email": emails.get(link.created_by),
        }
        verdict = verdicts.get(link.id)
        if verdict is not None:
            entry["verdict"] = {
                "status": verdict.status.value, "rationale": verdict.rationale,
                "reassessment_reason": verdict.reassessment_reason, "assessed_by_email": emails.get(verdict.assessed_by),
                "assessed_at": _j(verdict.assessed_at),
            }
        out.append(entry)
    return out


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: the project's Risk types and Risks with
    attachments, reviews and requirement treatment links (archived Risks
    included: a bundle is a backup, readers filter)."""
    assets: dict[UUID, FileAsset] = {}
    levels = _level_refs(db, project)

    types_json = []
    own_rows = list(db.scalars(select(ProjectRiskType).where(ProjectRiskType.project_id == project.id)))
    own_org_types = {
        t.id: t for t in db.scalars(select(RiskTypeDefinition).where(
            RiskTypeDefinition.id.in_({r.org_type_id for r in own_rows if r.org_type_id is not None})
        ))
    } if own_rows else {}
    for row in own_rows:
        org_type = own_org_types.get(row.org_type_id) if row.org_type_id else None
        types_json.append({
            "org_type_name": org_type.name if org_type else None, "name_override": row.name_override,
            "display_order_override": row.display_order_override, "is_enabled": row.is_enabled,
        })

    pairs = db.execute(
        select(Risk, RiskVersion).join(RiskVersion, RiskVersion.risk_id == Risk.id)
        .where(Risk.project_id == project.id, RiskVersion.valid_to.is_(None)).order_by(Risk.unique_code)
    ).all()
    risk_ids = [r.id for r, _ in pairs]
    reviews_by_risk: dict[UUID, list[RiskReview]] = {}
    if risk_ids:
        for review in db.scalars(select(RiskReview).where(RiskReview.risk_id.in_(risk_ids)).order_by(RiskReview.reviewed_at)):
            reviews_by_risk.setdefault(review.risk_id, []).append(review)
    verdicts_by_link = {
        a.link_id: a for a in db.scalars(select(RiskTreatmentAssessment).where(RiskTreatmentAssessment.risk_id.in_(risk_ids)))
    } if risk_ids else {}
    req_code = {r.id: r.unique_code for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))}
    link_type_names = {
        t.id: t.forward_name
        for t in db.scalars(select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.organization_id == project.organization_id))
    }
    prime_record_tag_names(db, RISK_ARTEFACT_TYPE, risk_ids)
    prime_file_links(db, RiskFile, "risk_id", risk_ids)
    user_ids: set[UUID | None] = set()
    for risk, version in pairs:
        user_ids |= {risk.creator_id, risk.archived_by, version.created_by}
        user_ids |= {r.reviewed_by for r in reviews_by_risk.get(risk.id, [])}
    user_ids |= {a.assessed_by for a in verdicts_by_link.values()}
    links_by_risk: dict[UUID, list[ArtefactLink]] = {r: [] for r in risk_ids}
    for lk in get_links_from_many(db, RISK_ARTEFACT_TYPE, risk_ids):
        links_by_risk[lk.source_id].append(lk)
    for lk in get_links_to_many(db, RISK_ARTEFACT_TYPE, risk_ids):
        links_by_risk[lk.target_id].append(lk)
    user_ids |= {lk.created_by for links in links_by_risk.values() for lk in links}
    emails = _emails(db, user_ids)

    risks_json = []
    for risk, version in pairs:
        entry: dict[str, Any] = {
            "unique_code": risk.unique_code, **{f: getattr(version, f) for f in _TEXT_FIELDS},
            "type_name": RISK_TYPES.display_name(db, org_type_id=None, project_type_id=version.project_type_id),
            "treatment_strategy": version.treatment_strategy.value if version.treatment_strategy else None,
            "levels": {column: levels.get(getattr(version, column)) for column in LEVEL_COLUMN_AXES if getattr(version, column)},
            "status": version.status.value,
            "owner": principal_to_bundle(db, version.owner_type, version.owner_id), "review_date": _j(version.review_date),
            "created_by_email": emails.get(risk.creator_id), "created_at": _j(risk.created_at),
            "is_archived": risk.is_archived, "archived_at": _j(risk.archived_at), "archived_by_email": emails.get(risk.archived_by),
            "review_notified_for": {"due": _j(risk.review_due_notified_for), "overdue": _j(risk.review_overdue_notified_for)},
            "tags": record_tag_names(db, RISK_ARTEFACT_TYPE, risk.id),
        }
        entry["attachments"] = export_file_links(db, RiskFile, "risk_id", risk.id, assets)
        entry["reviews"] = [
            {
                "reviewed_by_email": emails.get(r.reviewed_by), "reviewed_at": _j(r.reviewed_at), "outcome": r.outcome.value,
                "notes": r.notes, "risk_status": r.risk_status.value, "inherent_rating_label": r.inherent_rating_label,
                "inherent_rating_score": r.inherent_rating_score, "residual_rating_label": r.residual_rating_label,
                "residual_rating_score": r.residual_rating_score, "effective_treatment_count": r.effective_treatment_count,
                "scheduled_for": _j(r.scheduled_for), "next_review_date": _j(r.next_review_date),
            }
            for r in reviews_by_risk.get(risk.id, [])
        ]
        entry["treatments"] = _treatment_json(
            db, project, risk.id, req_code, link_type_names, verdicts_by_link, emails, links_by_risk[risk.id]
        )
        risks_json.append(entry)
    return {
        "risk_project_types": types_json,
        "risk_hidden_org_types": RISK_TYPES.hidden_names(db, project.id, project.organization_id),
        "risks": risks_json,
    }, assets


# --- Project level: import ---------------------------------------------------


def _import_types(db: Session, project: Project, data: dict[str, Any], warnings: BundleImportWarnings) -> dict[str, ProjectRiskType]:
    """Recreates the project's type rows; returns the rows by effective name."""
    org_types = {t.name: t for t in db.scalars(select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == project.organization_id))}
    rows: dict[str, ProjectRiskType] = {}
    for t in data.get("risk_project_types", []):
        if t.get("org_type_name"):
            org_type = org_types.get(t["org_type_name"])
            if org_type is None:
                warnings.add(f"Risk type override for {t['org_type_name']!r} skipped — the organisation has no such type.")
                continue
            row = RISK_TYPES.get_or_create_project_type(db, project.id, project.organization_id, org_type.id)
            RISK_TYPES.set_override(
                db, row, name=t.get("name_override"), display_order=t.get("display_order_override"), is_enabled=t.get("is_enabled"),
            )
            rows[t.get("name_override") or org_type.name] = row
        else:
            row = RISK_TYPES.create_project_local(db, project.id, t["name_override"], display_order=t.get("display_order_override"))
            row.is_enabled = t.get("is_enabled", True)
            rows[t["name_override"]] = row
    return rows


def _type_row(
    db: Session, project: Project, name: str | None, local_rows: dict[str, ProjectRiskType], org_types: dict[str, RiskTypeDefinition],
) -> ProjectRiskType | None:
    """The project type row to give a risk of type `name`: a type imported above, else a passthrough of the org type."""
    if not name:
        return None
    if name in local_rows:
        return local_rows[name]
    org_type = org_types.get(name)
    return RISK_TYPES.get_or_create_project_type(db, project.id, project.organization_id, org_type.id) if org_type else None


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's Risk types and
    Risks (keeping their codes), with attachments, reviews and requirement
    treatment links. Anything that cannot be matched in the target (a type, a
    scoring level, a requirement, a link type) is skipped or left unset with a
    warning, never guessed."""
    if not data.get("risks") and not data.get("risk_project_types") and not data.get("risk_hidden_org_types"):
        return
    organization_id = project.organization_id
    seed_missing_scoring_levels(db, organization_id)
    local_rows = _import_types(db, project, data, warnings)
    org_types = {t.name: t for t in db.scalars(select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == organization_id))}
    level_ids = {
        (axis, level.name): level.id
        for axis, levels in list_levels(db, organization_id, RISK_SCORING_SCHEME_KEY).items() for level in levels
    }
    requirement_ids = {r.unique_code: r.id for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))}
    link_type_ids = {s.link_type.forward_name: s.link_type.id for s in resolve_link_type_scope(db, project) if s.shadowed_by is None}
    max_seq = 0
    now = datetime.now(UTC)

    seen_codes: set[str] = set()
    for entry in data.get("risks", []):
        code = entry["unique_code"]
        if code in seen_codes:
            warnings.add(f"Risk {code} appears more than once in the bundle — the later copy was skipped.")
            continue
        seen_codes.add(code)
        creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"Risk {code} creator")
        archived = bool(entry.get("is_archived"))
        archiver_id = users.resolve(entry.get("archived_by_email"), required=False, context=f"Risk {code} archiver")
        notified = entry.get("review_notified_for") or {}
        risk = Risk(
            project_id=project.id, unique_code=code, creator_id=creator_id, is_archived=archived,
            archived_at=_dt(entry.get("archived_at")),
            archived_by=(archiver_id or creator_id) if archived else None,
            review_due_notified_for=_date(notified.get("due")), review_overdue_notified_for=_date(notified.get("overdue")),
        )
        db.add(risk)
        db.flush()
        tail = code.rsplit("-", 1)[-1]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))

        type_row = _type_row(db, project, entry.get("type_name"), local_rows, org_types)
        if entry.get("type_name") and type_row is None:
            warnings.add(f"Risk {code}: type {entry['type_name']!r} not found — left untyped.")
        levels: dict[str, UUID | None] = {}
        for column, ref in (entry.get("levels") or {}).items():
            level_id = level_ids.get((ref["axis"], ref["name"])) if ref else None
            if level_id is None:
                warnings.add(f"Risk {code}: scoring level {ref['name']!r} ({ref['axis']}) not found — left unset.")
            levels[column] = level_id
        db.add(RiskVersion(
            risk_id=risk.id, version_number=1, valid_from=now, valid_to=None, title=entry["title"],
            **{f: entry.get(f, "") for f in _TEXT_FIELDS if f != "title"}, project_type_id=type_row.id if type_row else None,
            treatment_strategy=TreatmentStrategy(entry["treatment_strategy"]) if entry.get("treatment_strategy") else None,
            status=RiskStatus(entry.get("status", "identified")),
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=organization_id, project_id=project.id, users=users,
                warnings=warnings, context=f"Risk {code} owner", required=False,
            ),
            review_date=_date(entry.get("review_date")), change_note="Imported from bundle.", created_by=creator_id, created_at=now,
            **{c: levels.get(c) for c in LEVEL_COLUMN_AXES},
        ))
        db.flush()
        restore_record_tags(
            db, organization_id=organization_id, record_project_id=project.id, actor_id=creator_id,
            artefact_type=RISK_ARTEFACT_TYPE, artefact_id=risk.id, names=entry.get("tags"),
        )

        for att in entry.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = users.resolve(att.get("linked_by_email"), required=False, context="Risk attachment uploader") or current_user.id
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(RiskFile(risk_id=risk.id, file_id=asset.id, linked_by=uploader_id, created_at=now))

        for rv in entry.get("reviews", []):
            db.add(RiskReview(
                risk_id=risk.id, risk_version_number=1,
                reviewed_by=users.resolve(rv.get("reviewed_by_email"), required=False, context=f"Risk {code} reviewer") or current_user.id,
                reviewed_at=_dt(rv["reviewed_at"]) or now, outcome=RiskReviewOutcome(rv["outcome"]), notes=rv["notes"],
                risk_status=RiskStatus(rv["risk_status"]), inherent_rating_label=rv.get("inherent_rating_label"),
                inherent_rating_score=rv.get("inherent_rating_score"), residual_rating_label=rv.get("residual_rating_label"),
                residual_rating_score=rv.get("residual_rating_score"),
                effective_treatment_count=rv.get("effective_treatment_count", 0), scheduled_for=_date(rv.get("scheduled_for")),
                next_review_date=_date(rv.get("next_review_date")),
            ))

        for t in entry.get("treatments", []):
            requirement_id = requirement_ids.get(t["requirement_unique_code"])
            link_type_id = link_type_ids.get(t.get("link_type_forward_name"))
            if requirement_id is None or link_type_id is None:
                warnings.add(
                    f"Risk {code}: link to requirement {t['requirement_unique_code']} "
                    f"({t.get('link_type_forward_name')!r}) skipped — the requirement or link type is not available here."
                )
                continue
            ends = (
                {"source_type": RISK_ARTEFACT_TYPE, "source_id": risk.id, "target_type": _REQUIREMENT, "target_id": requirement_id}
                if t["risk_is_source"] else
                {"source_type": _REQUIREMENT, "source_id": requirement_id, "target_type": RISK_ARTEFACT_TYPE, "target_id": risk.id}
            )
            link: ArtefactLink = create_link(
                db, **ends, link_type_id=link_type_id, project_id=project.id, enforce_rules=False,  # replaying existing data
                created_by=users.resolve(t.get("created_by_email"), required=False, context=f"Risk {code} link creator") or current_user.id,
            )
            verdict = t.get("verdict")
            if verdict:
                db.add(RiskTreatmentAssessment(
                    link_id=link.id, risk_id=risk.id, status=TreatmentAssessmentStatus(verdict["status"]),
                    assessed_by=users.resolve(verdict.get("assessed_by_email"), required=False, context=f"Risk {code} assessor") or current_user.id,
                    assessed_at=_dt(verdict.get("assessed_at")) or now, rationale=verdict.get("rationale", ""),
                    reassessment_reason=verdict.get("reassessment_reason", ""),
                ))
    db.flush()

    # Hidden last: a risk above may use a type the project hides, which needs its row created first.
    for name in RISK_TYPES.hide_by_names(db, project.id, organization_id, data.get("risk_hidden_org_types", [])):
        warnings.add(f"Hidden risk type {name!r} skipped — the organisation has no such type.")

    # Keep new Risks from reusing an imported code.
    counter = db.scalar(select(ProjectSequenceCounter).where(
        ProjectSequenceCounter.project_id == project.id, ProjectSequenceCounter.artefact_type == RISK_ARTEFACT_TYPE,
    ))
    if counter is None:
        db.add(ProjectSequenceCounter(project_id=project.id, artefact_type=RISK_ARTEFACT_TYPE, next_seq=max_seq + 1))
    else:
        counter.next_seq = max(counter.next_seq, max_seq + 1)
    db.flush()

