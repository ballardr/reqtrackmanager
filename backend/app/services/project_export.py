"""
Module: services.project_export

Exports a project's full structure and history (components/categories/
stages/custom field definitions/groups, every requirement's full version
history, every change request with its versions/tasks/votes/comments,
baselines, review outcomes, and structural audit events) as a self-
contained, versioned zip bundle, and imports such a bundle back as a brand
new project — same organisation or a different one.

Every cross-reference inside the bundle uses a portable key instead of a
raw database id, since ids from the source database are meaningless in the
target one: requirements by `unique_code`, change requests by a synthetic
per-export `ref`, components/categories by prefix, stages/custom field
definitions by name, and every user reference by email (resolved on import
via `services.bundle_common.UserResolver`).

Deliberately out of scope (documented rather than silently dropped):
`Notification`/`NotificationPreference`/`Subscription` (per-user, per-
deployment inbox state that's meaningless once ids change) and `LoginEvent`
(security/auth log, not project content) are never included.
`ChangeRequestVersion.proposed_attachment_file_ids` references
organisation-resource files outside this project bundle's own file
enumeration (`RequirementFile`/`CommentFile` attachments only) and is
always imported as empty — re-attaching those is a manual follow-up.
`ProjectGroupMember` rows are never recreated on import at all — only the
group *structure* (name/roles) is. Blindly re-granting membership by email
match would let an account with no prior relationship to the target
organisation gain project access purely because its email happens to
match, which is a privilege-escalation risk, not a convenience worth the
exposure — especially for a cross-organisation import. Member emails are
still included in the export for a human to re-populate manually. The
importing user is always guaranteed project-manager access regardless
(the same guarantee `POST /projects` gives its own caller).
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.change_request import (
    ChangeRequest,
    ChangeRequestTask,
    ChangeRequestVersion,
    ChangeRequestVote,
    ReviewComment,
)
from app.models.custom_field import CustomFieldDefinition, CustomFieldEntityKind, CustomFieldType
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ChangeRequestVoteChoice,
    ProjectRole,
    RequirementLevel,
    RequirementReviewOutcome,
    RequirementStatus,
    ReviewTargetType,
    StageStatus,
)
from app.models.file import CommentFile, FileAsset, RequirementFile
from app.models.organization import Organization, ReportTemplate
from app.models.project import (
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectStage,
    UserProjectRole,
)
from app.models.requirement import (
    Baseline,
    BaselineItem,
    Requirement,
    RequirementKeyword,
    RequirementLink,
    RequirementReview,
    RequirementVersion,
)
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.services.audit import log_event
from app.services.bundle_common import (
    BundleImportWarnings,
    UserResolver,
    enforce_upload_size_limit,
    enforce_zip_uncompressed_size_limit,
    import_bundled_file,
)
from app.services.definitions import get_default_project_status_id, seed_action_types
from app.services.files import read_file
from app.services.rbac import get_effective_project_managers

PROJECT_BUNDLE_KIND = "project-export"
PROJECT_BUNDLE_FORMAT_VERSION = 1


def _j(value: Any) -> Any:
    """Renders a value for embedding in the bundle's JSON — datetimes/dates
    as ISO strings (parsed back with `datetime.fromisoformat`/`date.
    fromisoformat` on import), enums as their plain string value, else
    unchanged."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def collect_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """Assembles a project's structure/history as a plain dict (the exact
    content of a project bundle's `project.json`) plus every `FileAsset` its
    requirement/comment attachments reference.

    Split out from `build_project_bundle` so `services.org_export` can reuse
    this exact per-project logic when assembling an org bundle (each project
    entry inside an org bundle has this same shape) without going through
    "build one zip per project, then unzip it back out again."

    Returns:
        A `(project_json, file_assets_by_id)` pair.
    """
    stages = list(db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id).order_by(ProjectStage.sort_order)))
    components = list(
        db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project.id).order_by(ProjectComponent.sort_order))
    )
    categories = list(db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project.id)))
    definitions = list(
        db.scalars(select(CustomFieldDefinition).where(CustomFieldDefinition.project_id == project.id).order_by(CustomFieldDefinition.sort_order))
    )
    groups = list(db.scalars(select(ProjectGroup).where(ProjectGroup.project_id == project.id)))
    requirements = list(db.scalars(select(Requirement).where(Requirement.project_id == project.id).order_by(Requirement.unique_code)))
    req_ids = [r.id for r in requirements]
    change_requests = list(
        db.scalars(select(ChangeRequest).where(ChangeRequest.project_id == project.id).order_by(ChangeRequest.created_at)).all()
    )
    cr_ids = [cr.id for cr in change_requests]
    baselines = list(db.scalars(select(Baseline).where(Baseline.project_id == project.id)))

    stage_name_by_id = {s.id: s.name for s in stages}
    component_prefix_by_id = {c.id: c.prefix for c in components}
    category_by_id = {c.id: c for c in categories}
    # RequirementVersion.custom_fields/ChangeRequestVersion.custom_fields are
    # JSONB dicts keyed by the *stringified* definition id (see
    # models.requirement.RequirementVersion.custom_fields's docstring) — the
    # lookup below must match on that string form, not the UUID object
    # itself, or every value silently fails the `k in cf_name_by_id` check.
    cf_name_by_id = {str(d.id): d.name for d in definitions}
    req_code_by_id = {r.id: r.unique_code for r in requirements}
    cr_ref_by_id = {cr.id: f"CR-{i + 1}" for i, cr in enumerate(change_requests)}

    versions = list(
        db.scalars(select(RequirementVersion).where(RequirementVersion.requirement_id.in_(req_ids)))
        if req_ids else []
    )
    versions_by_req: dict[UUID, list[RequirementVersion]] = {}
    for v in versions:
        versions_by_req.setdefault(v.requirement_id, []).append(v)
    for vs in versions_by_req.values():
        vs.sort(key=lambda v: v.version_number)

    keywords_by_req: dict[UUID, list[str]] = {}
    if req_ids:
        for req_id, keyword in db.execute(
            select(RequirementKeyword.requirement_id, RequirementKeyword.keyword).where(RequirementKeyword.requirement_id.in_(req_ids))
        ).all():
            keywords_by_req.setdefault(req_id, []).append(keyword)

    links = list(db.scalars(select(RequirementLink).where(RequirementLink.source_requirement_id.in_(req_ids))) if req_ids else [])
    # Link types are exported/matched by name, not id — like every other
    # cross-tenant reference in this bundle (users by email, custom fields
    # by name), an id from the source deployment's
    # `requirement_link_type_definitions` table means nothing on import
    # (`apply_project_data` looks this back up by `forward_name` within the
    # *target* organisation's own link types).
    link_type_forward_name_by_id = {
        lt.id: lt.forward_name
        for lt in db.scalars(
            select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.organization_id == project.organization_id)
        )
    }

    attachments_by_req: dict[UUID, list[dict]] = {}
    file_assets_by_id: dict[UUID, FileAsset] = {}
    if req_ids:
        for req_file, asset, uploader in db.execute(
            select(RequirementFile, FileAsset, User)
            .join(FileAsset, FileAsset.id == RequirementFile.file_id)
            .join(User, User.id == RequirementFile.linked_by)
            .where(RequirementFile.requirement_id.in_(req_ids))
        ).all():
            file_assets_by_id[asset.id] = asset
            attachments_by_req.setdefault(req_file.requirement_id, []).append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": uploader.email,
            })

    requirement_comments_raw = list(
        db.scalars(select(ReviewComment).where(ReviewComment.target_type == ReviewTargetType.REQUIREMENT, ReviewComment.target_id.in_(req_ids)))
        if req_ids else []
    )
    cr_comments_raw = list(
        db.scalars(select(ReviewComment).where(ReviewComment.target_type == ReviewTargetType.CHANGE_REQUEST, ReviewComment.target_id.in_(cr_ids)))
        if cr_ids else []
    )
    comment_ids = [c.id for c in requirement_comments_raw + cr_comments_raw]
    comment_attachments_by_comment: dict[UUID, list[dict]] = {}
    if comment_ids:
        for comment_file, asset, uploader in db.execute(
            select(CommentFile, FileAsset, User)
            .join(FileAsset, FileAsset.id == CommentFile.file_id)
            .join(User, User.id == CommentFile.uploaded_by)
            .where(CommentFile.comment_id.in_(comment_ids))
        ).all():
            file_assets_by_id[asset.id] = asset
            comment_attachments_by_comment.setdefault(comment_file.comment_id, []).append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "uploaded_by_email": uploader.email,
            })

    cr_versions = list(db.scalars(select(ChangeRequestVersion).where(ChangeRequestVersion.change_request_id.in_(cr_ids))) if cr_ids else [])
    cr_versions_by_cr: dict[UUID, list[ChangeRequestVersion]] = {}
    for v in cr_versions:
        cr_versions_by_cr.setdefault(v.change_request_id, []).append(v)
    for vs in cr_versions_by_cr.values():
        vs.sort(key=lambda v: v.version_number)

    cr_tasks = list(db.scalars(select(ChangeRequestTask).where(ChangeRequestTask.change_request_id.in_(cr_ids))) if cr_ids else [])
    cr_tasks_by_cr: dict[UUID, list[ChangeRequestTask]] = {}
    for t in cr_tasks:
        cr_tasks_by_cr.setdefault(t.change_request_id, []).append(t)

    cr_votes = list(db.scalars(select(ChangeRequestVote).where(ChangeRequestVote.change_request_id.in_(cr_ids))) if cr_ids else [])
    cr_votes_by_cr: dict[UUID, list[ChangeRequestVote]] = {}
    for v in cr_votes:
        cr_votes_by_cr.setdefault(v.change_request_id, []).append(v)

    cr_comments_by_cr: dict[UUID, list[ReviewComment]] = {}
    for c in cr_comments_raw:
        cr_comments_by_cr.setdefault(c.target_id, []).append(c)

    baseline_ids = [b.id for b in baselines]
    baseline_items = list(db.scalars(select(BaselineItem).where(BaselineItem.baseline_id.in_(baseline_ids))) if baseline_ids else [])
    baseline_items_by_baseline: dict[UUID, list[BaselineItem]] = {}
    for item in baseline_items:
        baseline_items_by_baseline.setdefault(item.baseline_id, []).append(item)

    requirement_reviews = list(db.scalars(select(RequirementReview).where(RequirementReview.requirement_id.in_(req_ids))) if req_ids else [])
    audit_events = list(
        db.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id).order_by(AuditEvent.created_at)).all()
    )

    # A single deployment-wide user lookup for every *_id field encountered
    # above, rather than N+1 queries per row.
    user_ids: set[UUID] = set()
    for v in versions:
        user_ids |= {v.owner_id, v.created_by}
        if v.approval_authority_id:
            user_ids.add(v.approval_authority_id)
        if v.reviewer_id:
            user_ids.add(v.reviewer_id)
    for r in requirements:
        user_ids.add(r.creator_id)
        if r.archived_by:
            user_ids.add(r.archived_by)
        if r.completed_by:
            user_ids.add(r.completed_by)
    for link in links:
        user_ids.add(link.created_by)
    for cr in change_requests:
        user_ids.add(cr.creator_id)
        if cr.decided_by:
            user_ids.add(cr.decided_by)
    for v in cr_versions:
        user_ids.add(v.created_by)
        if v.proposed_reviewer_id:
            user_ids.add(v.proposed_reviewer_id)
    for t in cr_tasks:
        user_ids.add(t.created_by)
        if t.assignee_id:
            user_ids.add(t.assignee_id)
    for v in cr_votes:
        user_ids.add(v.user_id)
    for c in requirement_comments_raw + cr_comments_raw:
        user_ids.add(c.author_id)
    for b in baselines:
        user_ids.add(b.created_by)
    for rr in requirement_reviews:
        user_ids.add(rr.reviewed_by)
    for ev in audit_events:
        if ev.actor_id:
            user_ids.add(ev.actor_id)
    for group in groups:
        for member in db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == group.id)).all():
            if member.user_id:
                user_ids.add(member.user_id)
    user_ids.discard(None)
    email_by_user_id = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def email(user_id: UUID | None) -> str | None:
        return email_by_user_id.get(user_id) if user_id else None

    def custom_fields_by_name(values: dict[str, Any]) -> dict[str, Any]:
        return {cf_name_by_id[k]: v for k, v in (values or {}).items() if k in cf_name_by_id}

    def category_ref(category_id: UUID) -> tuple[str | None, str | None]:
        category = category_by_id.get(category_id)
        if category is None:
            return None, None
        return component_prefix_by_id.get(category.component_id), category.prefix

    def serialize_requirement_version(v: RequirementVersion) -> dict:
        return {
            "version_number": v.version_number, "valid_from": _j(v.valid_from), "valid_to": _j(v.valid_to),
            "name": v.name, "reasoning": v.reasoning, "clarification": v.clarification, "description": v.description,
            "status": v.status.value, "target_stage": stage_name_by_id.get(v.target_stage_id), "level": v.level.value,
            "owner_email": email(v.owner_id), "approval_authority_email": email(v.approval_authority_id),
            "sort_order": v.sort_order, "custom_fields": custom_fields_by_name(v.custom_fields),
            "change_request_ref": cr_ref_by_id.get(v.change_request_id) if v.change_request_id else None,
            "change_note": v.change_note, "review_date": _j(v.review_date), "review_lead_days": v.review_lead_days,
            "reviewer_email": email(v.reviewer_id), "created_by_email": email(v.created_by), "created_at": _j(v.created_at),
        }

    def serialize_comment(c: ReviewComment) -> dict:
        return {
            "author_email": email(c.author_id), "body": c.body, "created_at": _j(c.created_at), "edited_at": _j(c.edited_at),
            "attachments": comment_attachments_by_comment.get(c.id, []),
        }

    requirements_json = []
    for r in requirements:
        _, category_prefix = category_ref(r.category_id)
        requirements_json.append({
            "unique_code": r.unique_code, "component_prefix": component_prefix_by_id.get(r.component_id),
            "category_prefix": category_prefix, "creator_email": email(r.creator_id),
            "is_archived": r.is_archived, "archived_at": _j(r.archived_at), "archived_by_email": email(r.archived_by),
            # C-G-11 overlay marker (`models.requirement.Requirement.is_completed`),
            # round-tripped the same way as the sibling archive overlay above.
            "is_completed": r.is_completed, "completed_at": _j(r.completed_at), "completed_by_email": email(r.completed_by),
            "versions": [serialize_requirement_version(v) for v in versions_by_req.get(r.id, [])],
            "keywords": keywords_by_req.get(r.id, []), "attachments": attachments_by_req.get(r.id, []),
        })

    requirement_links_json = [
        {
            "source_unique_code": req_code_by_id.get(link.source_requirement_id),
            "target_unique_code": req_code_by_id.get(link.target_requirement_id),
            "link_type_forward_name": link_type_forward_name_by_id.get(link.link_type_id),
            "created_by_email": email(link.created_by),
        }
        for link in links if link.source_requirement_id in req_code_by_id and link.target_requirement_id in req_code_by_id
    ]

    requirement_comments_json = [
        {"requirement_unique_code": req_code_by_id[c.target_id], **serialize_comment(c)}
        for c in requirement_comments_raw if c.target_id in req_code_by_id
    ]

    change_requests_json = []
    for cr in change_requests:
        cr_versions_json = []
        for v in cr_versions_by_cr.get(cr.id, []):
            proposed_component_prefix = component_prefix_by_id.get(v.proposed_component_id) if v.proposed_component_id else None
            proposed_category = category_by_id.get(v.proposed_category_id) if v.proposed_category_id else None
            proposed_category_prefix = proposed_category.prefix if proposed_category else None
            cr_versions_json.append({
                "version_number": v.version_number, "proposed_name": v.proposed_name, "proposed_reasoning": v.proposed_reasoning,
                "proposed_clarification": v.proposed_clarification, "proposed_description": v.proposed_description,
                "proposed_component_prefix": proposed_component_prefix, "proposed_category_prefix": proposed_category_prefix,
                "proposed_target_stage": stage_name_by_id.get(v.proposed_target_stage_id) if v.proposed_target_stage_id else None,
                "proposed_level": v.proposed_level.value if v.proposed_level else None,
                "proposed_review_date": _j(v.proposed_review_date), "proposed_review_lead_days": v.proposed_review_lead_days,
                "proposed_reviewer_email": email(v.proposed_reviewer_id), "changed_fields": v.changed_fields, "reason": v.reason,
                "custom_fields": custom_fields_by_name(v.custom_fields),
                "created_by_email": email(v.created_by), "created_at": _j(v.created_at),
            })
        change_requests_json.append({
            "ref": cr_ref_by_id[cr.id], "requirement_unique_code": req_code_by_id.get(cr.requirement_id) if cr.requirement_id else None,
            "kind": cr.kind.value, "status": cr.status.value, "creator_email": email(cr.creator_id),
            "submitted_at": _j(cr.submitted_at), "decided_at": _j(cr.decided_at), "decided_by_email": email(cr.decided_by),
            "decision_note": cr.decision_note, "versions": cr_versions_json,
            "tasks": [
                {
                    "description": t.description, "assignee_email": email(t.assignee_id), "due_date": _j(t.due_date),
                    "is_done": t.is_done, "completed_at": _j(t.completed_at), "created_by_email": email(t.created_by),
                }
                for t in cr_tasks_by_cr.get(cr.id, [])
            ],
            "votes": [
                {"user_email": email(v.user_id), "vote": v.vote.value, "comment": v.comment, "voted_at": _j(v.voted_at)}
                for v in cr_votes_by_cr.get(cr.id, [])
            ],
            "comments": [serialize_comment(c) for c in cr_comments_by_cr.get(cr.id, [])],
        })

    baselines_json = [
        {
            "stage_name": stage_name_by_id.get(b.stage_id), "label": b.label, "created_by_email": email(b.created_by),
            "created_at": _j(b.created_at),
            "items": [
                {"unique_code": req_code_by_id.get(item.requirement_id), "version_number": next(
                    (v.version_number for v in versions_by_req.get(item.requirement_id, []) if v.id == item.requirement_version_id), None
                )}
                for item in baseline_items_by_baseline.get(b.id, []) if item.requirement_id in req_code_by_id
            ],
        }
        for b in baselines
    ]

    requirement_reviews_json = [
        {
            "unique_code": req_code_by_id.get(rr.requirement_id), "version_number": next(
                (v.version_number for v in versions_by_req.get(rr.requirement_id, []) if v.id == rr.requirement_version_id), None
            ),
            "reviewed_by_email": email(rr.reviewed_by), "reviewed_at": _j(rr.reviewed_at), "outcome": rr.outcome.value, "comment": rr.comment,
        }
        for rr in requirement_reviews if rr.requirement_id in req_code_by_id
    ]

    groups_json = []
    for group in groups:
        members = db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == group.id)).all()
        group_roles = db.scalars(
            select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == group.id)
        ).all()
        groups_json.append({
            "name": group.name, "roles": [r.value for r in group_roles],
            "member_emails": [email(m.user_id) for m in members if m.user_id and email(m.user_id)],
        })

    default_report_template_name = None
    if project.default_report_template_id:
        template = db.get(ReportTemplate, project.default_report_template_id)
        default_report_template_name = template.name if template else None

    project_json = {
        "source_name": project.name, "summary": project.summary,
        "allow_member_change_requests": project.allow_member_change_requests, "terminology": project.terminology,
        "review_reminder_lead_days_default": project.review_reminder_lead_days_default,
        "report_intro": project.report_intro, "report_chapters": project.report_chapters, "report_appendices": project.report_appendices,
        "default_report_template_name": default_report_template_name,
        "stages": [{"name": s.name, "sort_order": s.sort_order} for s in stages],
        "components": [
            {
                "name": c.name, "prefix": c.prefix, "sort_order": c.sort_order,
                "categories": [
                    {"name": cat.name, "prefix": cat.prefix, "sort_order": cat.sort_order}
                    for cat in categories if cat.component_id == c.id
                ],
            }
            for c in components
        ],
        "custom_field_definitions": [
            {
                "entity_kind": d.entity_kind.value, "name": d.name, "field_type": d.field_type.value,
                "options": d.options, "required": d.required, "sort_order": d.sort_order,
            }
            for d in definitions
        ],
        "groups": groups_json,
        "requirements": requirements_json,
        "requirement_links": requirement_links_json,
        "requirement_comments": requirement_comments_json,
        "change_requests": change_requests_json,
        "baselines": baselines_json,
        "requirement_reviews": requirement_reviews_json,
        "audit_events": [
            {
                "entity_type": ev.entity_type, "entity_id": ev.entity_id, "action": ev.action,
                "actor_email": email(ev.actor_id), "detail": ev.detail, "created_at": _j(ev.created_at),
            }
            for ev in audit_events
        ],
    }
    return project_json, file_assets_by_id


def build_project_bundle(db: Session, project: Project, exported_by: User) -> bytes:
    """Builds a project export bundle: a zip containing `manifest.json`
    (self-describing envelope), `project.json` (structure + full history),
    and `files/` (every requirement/comment attachment's raw bytes).

    Args:
        db: An active database session.
        project: The project to export.
        exported_by: The user performing the export (recorded in the manifest).

    Returns:
        The zip file's bytes.
    """
    org = db.get(Organization, project.organization_id)
    project_json, file_assets_by_id = collect_project_data(db, project)

    manifest = {
        "kind": PROJECT_BUNDLE_KIND, "format_version": PROJECT_BUNDLE_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(), "exported_by_email": exported_by.email,
        "project_name": project.name, "organization_name": org.name if org else None,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("project.json", json.dumps(project_json, indent=2))
        for asset in file_assets_by_id.values():
            zf.writestr(f"files/{asset.id}_{asset.filename}", read_file(asset))
    return buffer.getvalue()


def _read_bundle(zip_bytes: bytes, expected_kind: str) -> tuple[dict, dict, zipfile.ZipFile]:
    enforce_upload_size_limit(zip_bytes, what="Bundle upload")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        enforce_zip_uncompressed_size_limit(zf)
        manifest = json.loads(zf.read("manifest.json"))
        data = json.loads(zf.read("project.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.") from None
    if manifest.get("kind") != expected_kind:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Expected a {expected_kind!r} bundle, got {manifest.get('kind')!r}.")
    if manifest.get("format_version", 0) > PROJECT_BUNDLE_FORMAT_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This bundle was exported by a newer version of the application and can't be imported here.",
        )
    return manifest, data, zf


def new_project_from_bundle_data(
    db: Session, organization_id: UUID, name: str, summary: str | None, data: dict[str, Any],
) -> Project:
    """Builds the initial `Project` row (not yet added/flushed) for a
    bundle's `project.json` — the one piece of project creation that
    legitimately differs between callers (a standalone project import lets
    the caller override name/summary; an org import uses the bundle's own
    project name for every project it contains, unmodified).

    `status_id` always starts at `organization_id`'s default status (never
    read from the bundle) — a project's status is current lifecycle state,
    not portable structural configuration, matching `clone_project`'s same
    choice for template-based creation (see its module docstring)."""
    return Project(
        organization_id=organization_id, name=name, summary=summary if summary is not None else data.get("summary", ""),
        allow_member_change_requests=data.get("allow_member_change_requests", True),
        terminology=data.get("terminology") or {},
        review_reminder_lead_days_default=data.get("review_reminder_lead_days_default", 7),
        report_intro=data.get("report_intro", ""), report_chapters=data.get("report_chapters", []) or [],
        report_appendices=data.get("report_appendices", []) or [],
        status_id=get_default_project_status_id(db, organization_id),
    )


def apply_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes],
    current_user: User, users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Reconstructs a project's structure and full history from a bundle's
    `project.json` dict onto an already-created `Project` row (`project.id`
    must already exist — i.e. added and flushed).

    Split out from `import_project_bundle` so `services.org_export` can
    reuse this exact per-project reconstruction when importing an org
    bundle's several nested projects, without re-deriving it. Does not
    commit — the caller owns the transaction (a standalone project import
    commits once per project; an org import commits once for the whole org).

    Args:
        db: An active database session.
        project: The target project, already added/flushed (so `project.id`
            is real) with its own name/summary/settings already set by the
            caller — see `new_project_from_bundle_data`.
        data: The bundle's parsed `project.json`.
        file_bytes_by_ref: Every embedded attachment's bytes, keyed by the
            `file_ref` used in `data`'s attachment entries.
        current_user: The user performing the import (audit trail + the
            guaranteed-project-manager fallback + unresolved-reference fallback).
        users: A `UserResolver` shared across the whole import (an org
            import shares one across all its projects, so a user only needs
            to be looked up once even if referenced from several projects).
        warnings: Accumulates human-readable import warnings.
    """
    organization_id = project.organization_id

    # Default action types (Review, Test) — a bundle doesn't currently carry
    # its source project's action-type customisations across (unlike custom
    # field definitions below), so every imported project simply starts
    # with the same defaults a brand-new project would get. Matches
    # `routers/projects.py::create_project`'s own default-seeding call for
    # a manually-created (non-template) project.
    seed_action_types(db, project.id)
    template_name = data.get("default_report_template_name")
    if template_name:
        template = db.scalar(
            select(ReportTemplate).where(ReportTemplate.organization_id == organization_id, ReportTemplate.name == template_name)
        )
        if template is None:
            template = ReportTemplate(organization_id=organization_id, name=template_name, created_by=current_user.id)
            db.add(template)
            db.flush()
        project.default_report_template_id = template.id

    stage_id_by_name: dict[str, UUID] = {}
    for i, s in enumerate(data.get("stages", []) or [{"name": "Scoping", "sort_order": 0}]):
        stage = ProjectStage(
            project_id=project.id, name=s["name"], sort_order=s.get("sort_order", 0),
            status=StageStatus.SCOPING, is_current=(i == 0),
        )
        db.add(stage)
        db.flush()
        stage_id_by_name[s["name"]] = stage.id
    fallback_stage_id = next(iter(stage_id_by_name.values()))

    component_id_by_prefix: dict[str, UUID] = {}
    category_id_by_key: dict[tuple[str, str], UUID] = {}
    for c in data.get("components", []):
        component = ProjectComponent(project_id=project.id, name=c["name"], prefix=c["prefix"], sort_order=c.get("sort_order", 0))
        db.add(component)
        db.flush()
        component_id_by_prefix[c["prefix"]] = component.id
        for cat in c.get("categories", []):
            category = ProjectCategory(
                project_id=project.id, component_id=component.id, name=cat["name"], prefix=cat["prefix"], sort_order=cat.get("sort_order", 0)
            )
            db.add(category)
            db.flush()
            category_id_by_key[(c["prefix"], cat["prefix"])] = category.id

    cf_id_by_key: dict[tuple[str, str], UUID] = {}
    for d in data.get("custom_field_definitions", []):
        definition = CustomFieldDefinition(
            project_id=project.id, entity_kind=CustomFieldEntityKind(d["entity_kind"]), name=d["name"],
            field_type=CustomFieldType(d["field_type"]), options=d.get("options"), required=d.get("required", False),
            sort_order=d.get("sort_order", 0),
        )
        db.add(definition)
        db.flush()
        cf_id_by_key[(d["entity_kind"], d["name"])] = definition.id

    def remap_custom_fields(values_by_name: dict[str, Any] | None, entity_kind: str) -> dict[str, Any]:
        out = {}
        for field_name, value in (values_by_name or {}).items():
            definition_id = cf_id_by_key.get((entity_kind, field_name))
            if definition_id is not None:
                out[str(definition_id)] = value
        return out

    # Group *structure* (name/role) is recreated, but membership is
    # deliberately NOT replayed from `member_emails`, even though those
    # emails were resolved for every other reference in this bundle: doing
    # so would silently grant a real account project access purely because
    # its email happens to match — including, for a cross-organisation
    # import, an account with no prior relationship to the target
    # organisation at all. That's a privilege-escalation-via-import risk,
    # not a convenience worth the exposure. `member_emails` stays in the
    # export purely as a human-readable reference for whoever re-populates
    # membership by hand afterward. The importing user always ends up a
    # project manager regardless (see the `get_effective_project_managers` fallback
    # below), matching the same guarantee `create_project` gives its caller.
    for g in data.get("groups", []):
        # A bundle exported before Phase C (follow-up UX batch, 2026-08-31)
        # may still carry an `"is_default"` key from the old format —
        # ignored on import, same as any other retired field: `is_default`
        # no longer exists on `ProjectGroup` at all, and re-creating a
        # group from a bundle is always an ordinary, fully-manageable group
        # regardless of what it originally was.
        #
        # `"roles"` (PR7, docs/decisions.md) replaced the old single
        # required `"role"` key with a list — a group may now hold zero,
        # one, or several roles. A bundle exported before PR7 still carries
        # the old singular `"role"` key instead; read either shape so an
        # older export can still be imported without losing its group's
        # role, without needing to re-export it first.
        new_group = ProjectGroup(project_id=project.id, name=g["name"])
        db.add(new_group)
        db.flush()
        roles = g["roles"] if "roles" in g else ([g["role"]] if "role" in g else [])
        for role_value in roles:
            db.add(ProjectGroupRole(project_group_id=new_group.id, role=ProjectRole(role_value)))

    def import_file_ref(att: dict, uploaded_by_email_key: str) -> FileAsset | None:
        data_bytes = file_bytes_by_ref.get(att["file_ref"])
        if data_bytes is None:
            return None
        uploader_id = users.resolve(att.get(uploaded_by_email_key), required=False, context="Attachment uploader") or current_user.id
        return import_bundled_file(
            db, organization_id=organization_id, uploaded_by=uploader_id,
            filename=att["filename"], content_type=att.get("content_type") or "application/octet-stream", data=data_bytes,
        )

    requirement_id_by_code: dict[str, UUID] = {}
    version_id_by_code_and_number: dict[tuple[str, int], UUID] = {}
    max_seq = 0
    for r in data.get("requirements", []):
        component_id = component_id_by_prefix.get(r["component_prefix"])
        category_id = category_id_by_key.get((r["component_prefix"], r["category_prefix"]))
        if component_id is None or category_id is None:
            warnings.add(f"Requirement {r['unique_code']}: unknown component/category prefix — skipped entirely.")
            continue
        requirement = Requirement(
            project_id=project.id, component_id=component_id, category_id=category_id, unique_code=r["unique_code"],
            creator_id=users.resolve(r.get("creator_email"), required=True, context=f"Requirement {r['unique_code']} creator"),
            is_archived=r.get("is_archived", False), archived_at=_dt(r.get("archived_at")),
            archived_by=users.resolve(r.get("archived_by_email"), required=False, context=f"Requirement {r['unique_code']} archiver"),
            is_completed=r.get("is_completed", False), completed_at=_dt(r.get("completed_at")),
            completed_by=users.resolve(r.get("completed_by_email"), required=False, context=f"Requirement {r['unique_code']} completer"),
        )
        db.add(requirement)
        db.flush()
        requirement_id_by_code[r["unique_code"]] = requirement.id
        tail = r["unique_code"].rsplit("-", 1)[-1]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))

        for v in r.get("versions", []):
            version = RequirementVersion(
                requirement_id=requirement.id, version_number=v["version_number"],
                valid_from=_dt(v["valid_from"]) or datetime.now(UTC), valid_to=_dt(v.get("valid_to")),
                name=v["name"], reasoning=v.get("reasoning", ""), clarification=v.get("clarification", ""),
                description=v.get("description", ""), status=RequirementStatus(v["status"]),
                target_stage_id=stage_id_by_name.get(v.get("target_stage")) or fallback_stage_id,
                level=RequirementLevel(v["level"]),
                owner_id=users.resolve(v.get("owner_email"), required=True, context=f"Requirement {r['unique_code']} v{v['version_number']} owner"),
                approval_authority_id=users.resolve(
                    v.get("approval_authority_email"), required=False, context=f"Requirement {r['unique_code']} v{v['version_number']} approver"
                ),
                sort_order=v.get("sort_order", 0), custom_fields=remap_custom_fields(v.get("custom_fields"), "requirement"),
                change_note=v.get("change_note", ""), review_date=_date(v.get("review_date")), review_lead_days=v.get("review_lead_days"),
                reviewer_id=users.resolve(
                    v.get("reviewer_email"), required=False, context=f"Requirement {r['unique_code']} v{v['version_number']} reviewer"
                ),
                created_by=users.resolve(
                    v.get("created_by_email"), required=True, context=f"Requirement {r['unique_code']} v{v['version_number']} author"
                ),
                created_at=_dt(v["created_at"]) or datetime.now(UTC),
            )
            db.add(version)
            db.flush()
            version_id_by_code_and_number[(r["unique_code"], v["version_number"])] = version.id
        for kw in r.get("keywords", []):
            db.add(RequirementKeyword(requirement_id=requirement.id, keyword=kw))
        for att in r.get("attachments", []):
            asset = import_file_ref(att, "linked_by_email")
            if asset:
                db.add(RequirementFile(
                    requirement_id=requirement.id, file_id=asset.id,
                    linked_by=users.resolve(att.get("linked_by_email"), required=False, context="Attachment linker") or current_user.id,
                ))
    project.next_requirement_seq = max(project.next_requirement_seq, max_seq + 1)

    # Link types are matched by forward_name within the *target*
    # organisation's own `requirement_link_type_definitions` — like every
    # other cross-tenant reference in this bundle (users by email, custom
    # fields by name), a source-deployment link-type id means nothing here.
    # A bundle link whose type name has no match in the target organisation
    # (e.g. it was a custom, non-default type the target org never defined)
    # is skipped with a warning rather than guessing a fallback type, which
    # would silently misrepresent the link's asserted meaning.
    link_type_id_by_name = {
        lt.forward_name: lt.id
        for lt in db.scalars(
            select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.organization_id == organization_id)
        )
    }
    for link in data.get("requirement_links", []):
        source_id = requirement_id_by_code.get(link["source_unique_code"])
        target_id = requirement_id_by_code.get(link["target_unique_code"])
        link_type_id = link_type_id_by_name.get(link.get("link_type_forward_name"))
        if source_id and target_id and link_type_id is not None:
            db.add(RequirementLink(
                source_requirement_id=source_id, target_requirement_id=target_id, link_type_id=link_type_id,
                created_by=users.resolve(link.get("created_by_email"), required=True, context="Requirement link creator"),
            ))
        elif source_id and target_id:
            warnings.add(
                f"Requirement link {link.get('source_unique_code')} -> {link.get('target_unique_code')} "
                f"references a link type ({link.get('link_type_forward_name')!r}) that doesn't exist in the "
                "target organisation and was skipped."
            )

    def import_comment(c: dict, target_type: ReviewTargetType, target_id: UUID, uploaded_by_key: str) -> None:
        comment = ReviewComment(
            target_type=target_type, target_id=target_id,
            author_id=users.resolve(c.get("author_email"), required=True, context="Comment author"),
            body=c["body"], edited_at=_dt(c.get("edited_at")),
        )
        db.add(comment)
        db.flush()
        for att in c.get("attachments", []):
            asset = import_file_ref(att, uploaded_by_key)
            if asset:
                db.add(CommentFile(
                    comment_id=comment.id, file_id=asset.id,
                    uploaded_by=users.resolve(att.get(uploaded_by_key), required=False, context="Comment attachment uploader") or current_user.id,
                ))

    for c in data.get("requirement_comments", []):
        req_id = requirement_id_by_code.get(c["requirement_unique_code"])
        if req_id:
            import_comment(c, ReviewTargetType.REQUIREMENT, req_id, "uploaded_by_email")

    cr_id_by_ref: dict[str, UUID] = {}
    for cr in data.get("change_requests", []):
        requirement_id = requirement_id_by_code.get(cr["requirement_unique_code"]) if cr.get("requirement_unique_code") else None
        change_request = ChangeRequest(
            project_id=project.id, requirement_id=requirement_id, kind=ChangeRequestKind(cr["kind"]),
            status=ChangeRequestStatus(cr["status"]),
            creator_id=users.resolve(cr.get("creator_email"), required=True, context=f"Change request {cr['ref']} creator"),
            submitted_at=_dt(cr.get("submitted_at")), decided_at=_dt(cr.get("decided_at")),
            decided_by=users.resolve(cr.get("decided_by_email"), required=False, context=f"Change request {cr['ref']} decider"),
            decision_note=cr.get("decision_note", ""),
        )
        db.add(change_request)
        db.flush()
        cr_id_by_ref[cr["ref"]] = change_request.id

        for v in cr.get("versions", []):
            proposed_component_id = component_id_by_prefix.get(v["proposed_component_prefix"]) if v.get("proposed_component_prefix") else None
            proposed_category_id = (
                category_id_by_key.get((v["proposed_component_prefix"], v["proposed_category_prefix"]))
                if v.get("proposed_component_prefix") and v.get("proposed_category_prefix") else None
            )
            db.add(ChangeRequestVersion(
                change_request_id=change_request.id, version_number=v["version_number"],
                proposed_name=v.get("proposed_name"), proposed_reasoning=v.get("proposed_reasoning"),
                proposed_clarification=v.get("proposed_clarification"), proposed_description=v.get("proposed_description"),
                proposed_component_id=proposed_component_id, proposed_category_id=proposed_category_id,
                proposed_target_stage_id=stage_id_by_name.get(v["proposed_target_stage"]) if v.get("proposed_target_stage") else None,
                proposed_level=RequirementLevel(v["proposed_level"]) if v.get("proposed_level") else None,
                proposed_review_date=_date(v.get("proposed_review_date")), proposed_review_lead_days=v.get("proposed_review_lead_days"),
                proposed_reviewer_id=users.resolve(
                    v.get("proposed_reviewer_email"), required=False, context=f"Change request {cr['ref']} v{v['version_number']} proposed reviewer"
                ),
                proposed_attachment_file_ids=[], changed_fields=v.get("changed_fields", []) or [], reason=v.get("reason", ""),
                custom_fields=remap_custom_fields(v.get("custom_fields"), "change_request"),
                created_by=users.resolve(
                    v.get("created_by_email"), required=True, context=f"Change request {cr['ref']} v{v['version_number']} author"
                ),
                created_at=_dt(v["created_at"]) or datetime.now(UTC),
            ))
        for t in cr.get("tasks", []):
            db.add(ChangeRequestTask(
                change_request_id=change_request.id, description=t["description"],
                assignee_id=users.resolve(t.get("assignee_email"), required=False, context=f"Change request {cr['ref']} task assignee"),
                due_date=_date(t.get("due_date")), is_done=t.get("is_done", False), completed_at=_dt(t.get("completed_at")),
                created_by=users.resolve(t.get("created_by_email"), required=True, context=f"Change request {cr['ref']} task creator"),
            ))
        for v in cr.get("votes", []):
            db.add(ChangeRequestVote(
                change_request_id=change_request.id,
                user_id=users.resolve(v.get("user_email"), required=True, context=f"Change request {cr['ref']} vote"),
                vote=ChangeRequestVoteChoice(v["vote"]), comment=v.get("comment"), voted_at=_dt(v["voted_at"]) or datetime.now(UTC),
            ))
        for c in cr.get("comments", []):
            import_comment(c, ReviewTargetType.CHANGE_REQUEST, change_request.id, "uploaded_by_email")

    # Second pass: relink RequirementVersion.change_request_id now that
    # change requests exist (a version can reference a CR created later in
    # export order than the version itself, e.g. an approved CR's resulting
    # version).
    for r in data.get("requirements", []):
        for v in r.get("versions", []):
            cr_ref = v.get("change_request_ref")
            if not cr_ref:
                continue
            version_id = version_id_by_code_and_number.get((r["unique_code"], v["version_number"]))
            cr_id = cr_id_by_ref.get(cr_ref)
            if version_id and cr_id:
                db.get(RequirementVersion, version_id).change_request_id = cr_id

    for b in data.get("baselines", []):
        stage_id = stage_id_by_name.get(b["stage_name"])
        if stage_id is None:
            continue
        baseline = Baseline(
            project_id=project.id, stage_id=stage_id, label=b["label"],
            created_by=users.resolve(b.get("created_by_email"), required=True, context=f"Baseline '{b['label']}' creator"),
        )
        db.add(baseline)
        db.flush()
        for item in b.get("items", []):
            requirement_id = requirement_id_by_code.get(item["unique_code"])
            version_id = version_id_by_code_and_number.get((item["unique_code"], item["version_number"]))
            if requirement_id and version_id:
                db.add(BaselineItem(baseline_id=baseline.id, requirement_id=requirement_id, requirement_version_id=version_id))

    for rr in data.get("requirement_reviews", []):
        requirement_id = requirement_id_by_code.get(rr["unique_code"])
        version_id = version_id_by_code_and_number.get((rr["unique_code"], rr["version_number"]))
        if requirement_id and version_id:
            db.add(RequirementReview(
                requirement_id=requirement_id, requirement_version_id=version_id,
                reviewed_by=users.resolve(rr.get("reviewed_by_email"), required=True, context=f"Review of {rr['unique_code']}"),
                reviewed_at=_dt(rr["reviewed_at"]) or datetime.now(UTC), outcome=RequirementReviewOutcome(rr["outcome"]),
                comment=rr.get("comment"),
            ))

    # Replays the source project's structural audit trail as its own
    # events (rather than trying to preserve original ids/timestamps
    # verbatim) — it's the only durable record of some structural changes
    # (group/role/stage/component history), so dropping it on import would
    # be a real, silent loss of project history.
    for ev in data.get("audit_events", []):
        log_event(
            db, entity_type=ev["entity_type"], entity_id=ev["entity_id"], action=ev["action"],
            actor_id=users.resolve(ev.get("actor_email"), required=False, context="Audit event actor"),
            organization_id=organization_id, project_id=project.id, detail=ev.get("detail"),
        )

    if not get_effective_project_managers(db, project.id):
        db.add(UserProjectRole(user_id=current_user.id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))

    log_event(
        db, entity_type="project", entity_id=project.id, action="imported_from_bundle", actor_id=current_user.id,
        organization_id=organization_id, project_id=project.id, detail={"warning_count": len(warnings.messages)},
    )


def import_project_bundle(
    db: Session, *, organization_id: UUID, name: str, summary: str | None, zip_bytes: bytes, current_user: User,
) -> tuple[Project, list[str]]:
    """Creates a brand-new project in `organization_id` from an exported
    project bundle. Never merges into an existing project — a fresh project
    keeps unique_code/prefix collisions and partial-import states impossible.

    Returns:
        The new Project and a list of human-readable import warnings (e.g.
        user references that fell back to `current_user`).
    """
    _manifest, data, zf = _read_bundle(zip_bytes, PROJECT_BUNDLE_KIND)
    file_bytes_by_ref = {n.removeprefix("files/"): zf.read(n) for n in zf.namelist() if n.startswith("files/")}

    warnings = BundleImportWarnings()
    users = UserResolver(db, current_user, warnings)
    project = new_project_from_bundle_data(db, organization_id, name, summary, data)
    db.add(project)
    db.flush()

    apply_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)

    db.commit()
    db.refresh(project)
    return project, warnings.messages
