"""
Module: modules.product_feedback.service

Business logic for Product Feedback: creating a request, editing it as a new version, the
lifecycle, archiving, list queries and the project submission policy.

Responsibilities:
- `create_request` / `apply_new_version`: a request and its version 1, and later versions that
  carry unchanged content forward.
- `transition_request` and `ALLOWED_TRANSITIONS`: the legal status moves and what each demands.
- `RecordOwner`: whether a record sits in a project or in the organisation's inbox.
- `validate_levels` / `version_levels`: a version's scoring levels (one per scheme axis, stored as
  `EnhancementRequestVersionScore` rows) belong to the organisation's scheme; read for many versions in one statement.
- `get_submission_policy` / `set_submission_policy`: who may submit in a project.

Design decisions:
- Nothing here commits or checks who may do it; the caller owns the transaction and the gate.
- A move to `DUPLICATE` is not a direct transition: only a merge sets it. Declining needs a reason.
- Content is never locked: a request stays editable at every status (each edit is a version).

Dependencies: `services.sequences` (codes), `services.audit` is used by the callers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.labels import request_status_label
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestVersion,
    EnhancementRequestVersionScore,
    ProjectFeedbackSettings,
)
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME, REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.scoring_filter import ScoredFilter, keep_by_scoring
from app.services.current_versions import current_versions
from app.services.scoring_custom import effective_scheme
from app.services.sequences import code_owner, generate_unique_code

PRODUCT_FEEDBACK_MODULE_KEY = "product_feedback"
REQUEST_ARTEFACT_TYPE = "enhancement_request"
REQUEST_CODE_PREFIX = "ENH"
REQUEST_SUBCOMPONENT_KEY = "enhancement_request"
ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY = "organization_requests"

#: The content fields a version carries (everything an edit may change except the status and the scoring
#: levels, which are rows of their own: `version_levels`).
REQUEST_CONTENT_FIELDS = (
    "title", "description", "owner_type", "owner_id", "decline_reason",
)

_S = EnhancementRequestStatus

#: Legal status moves. `DUPLICATE` is reached only by a merge, and a request leaves it only by unmerging, so
#: neither direction is a direct transition.
ALLOWED_TRANSITIONS: dict[EnhancementRequestStatus, frozenset[EnhancementRequestStatus]] = {
    _S.NEW: frozenset({_S.UNDER_REVIEW, _S.DECLINED}),
    _S.UNDER_REVIEW: frozenset({_S.NEW, _S.ACCEPTED, _S.DECLINED}),
    _S.ACCEPTED: frozenset({_S.UNDER_REVIEW, _S.DELIVERED, _S.DECLINED}),
    _S.DELIVERED: frozenset({_S.ACCEPTED}),
    _S.DECLINED: frozenset({_S.NEW}),
    _S.DUPLICATE: frozenset(),
}


def validate_levels(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, levels: dict[str, uuid.UUID | None],
) -> None:
    """Checks each given level is a level of this organisation on the right axis of the `enhancement_request`
    scoring scheme as it applies to the request's project (or the organisation, for the inbox), so an axis the
    project cannot see, or has hidden, is refused.

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        project_id: The request's project, or `None` for an inbox request.
        levels: Axis key -> level id (`None` entries, which clear an axis, are skipped).

    Raises:
        ValueError: If an axis is not one the request can use, or a level belongs to another organisation, scheme
            or axis.
    """
    scheme = effective_scheme(db, organization_id, REQUEST_SCORING_SCHEME, project_id)
    for axis_key, level_id in levels.items():
        if scheme.axis(axis_key) is None:
            raise ValueError(f"'{axis_key}' is not a scoring axis of enhancement requests.")
        if level_id is None:
            continue
        level = db.get(ScoringLevel, level_id)
        if (
            level is None or level.organization_id != organization_id
            or level.scheme_key != REQUEST_SCORING_SCHEME_KEY or level.axis_key != axis_key
        ):
            raise ValueError(f"This is not a valid {axis_key} level for this organisation.")


def version_levels(db: Session, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, uuid.UUID]]:
    """The scoring levels of many versions, `{version id: {axis key: level id}}`, in one statement. A version
    with no levels is present with an empty mapping."""
    out: dict[uuid.UUID, dict[str, uuid.UUID]] = {version_id: {} for version_id in version_ids}
    if not out:
        return out
    for version_id, axis_key, level_id in db.execute(
        select(
            EnhancementRequestVersionScore.version_id, EnhancementRequestVersionScore.axis_key,
            EnhancementRequestVersionScore.level_id,
        ).where(EnhancementRequestVersionScore.version_id.in_(list(out)))
    ):
        out[version_id][axis_key] = level_id
    return out


def _write_levels(db: Session, version_id: uuid.UUID, levels: dict[str, uuid.UUID]) -> None:
    """Adds one score row per axis of `levels` to a new version (not flushed)."""
    for axis_key, level_id in levels.items():
        db.add(EnhancementRequestVersionScore(version_id=version_id, axis_key=axis_key, level_id=level_id))


@dataclass(frozen=True)
class RecordOwner:
    """Who owns a request being created or edited: a project, or (without `project_id`) the organisation.

    Attributes:
        organization_id: The owning organisation (also the project's organisation).
        project_id: The owning project, or `None` for an organisation-owned request.
    """

    organization_id: uuid.UUID
    project_id: uuid.UUID | None = None

    @classmethod
    def of_project(cls, project: Project) -> RecordOwner:
        """The owner of a project's own request."""
        return cls(project.organization_id, project.id)

    @property
    def is_project(self) -> bool:
        return self.project_id is not None

    @property
    def scope(self) -> EnhancementRequestScope:
        return EnhancementRequestScope.PROJECT if self.is_project else EnhancementRequestScope.ORGANIZATION

    @property
    def audit_organization_id(self) -> uuid.UUID | None:
        """The organisation to place an audit event under: set only for an organisation-owned request (a
        project-owned one is placed by its project)."""
        return None if self.is_project else self.organization_id


def get_current_version(db: Session, request_id: uuid.UUID) -> EnhancementRequestVersion:
    """The current (`valid_to IS NULL`) version of a request.

    Raises:
        ValueError: If none exists (a data-integrity fault).
    """
    version = db.scalar(select(EnhancementRequestVersion).where(
        EnhancementRequestVersion.request_id == request_id, EnhancementRequestVersion.valid_to.is_(None),
    ))
    if version is None:
        raise ValueError(f"Enhancement request {request_id} has no current version.")
    return version


def create_request(db: Session, holder: RecordOwner, creator: User, **content: Any) -> EnhancementRequest:
    """Creates a request and its version 1 in `NEW`.

    Args:
        db: Active session; the caller commits.
        holder: The owning project, or the organisation.
        creator: The acting user.
        **content: Any `REQUEST_CONTENT_FIELDS`, and `levels` (axis key -> level id; the caller has validated
            it); `title` is required.

    Returns:
        The new request (flushed, not committed).
    """
    owner = code_owner(
        db, is_org_scope=not holder.is_project, organization_id=holder.organization_id, project_id=holder.project_id,
    )
    request = EnhancementRequest(
        scope=holder.scope,
        organization_id=None if holder.is_project else holder.organization_id,
        project_id=holder.project_id, creator_id=creator.id,
        unique_code=generate_unique_code(db, owner, REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX),
    )
    db.add(request)
    db.flush()
    now = datetime.now(UTC)
    levels = {axis: level_id for axis, level_id in (content.get("levels") or {}).items() if level_id is not None}
    content = {k: v for k, v in content.items() if k in REQUEST_CONTENT_FIELDS}
    version = EnhancementRequestVersion(
        request_id=request.id, version_number=1, valid_from=now, valid_to=None, status=_S.NEW,
        change_note="Initial creation.", created_by=creator.id, created_at=now, **content,
    )
    db.add(version)
    db.flush()
    _write_levels(db, version.id, levels)
    db.flush()
    return request


def apply_new_version(
    db: Session, request: EnhancementRequest, current_version: EnhancementRequestVersion, actor: User,
    *, changes: dict[str, Any], change_note: str = "",
) -> EnhancementRequestVersion:
    """Closes `current_version` and inserts a new one with `changes` applied over the carried-forward content.

    A key present in `changes` is applied even when `None`, so nullable fields can be cleared; absent keys are
    carried forward. `status` is a valid key. `levels` (axis key -> level id) is merged over the current
    version's levels: an axis it names is set, or cleared when `None`; the others are carried forward.
    """
    now = datetime.now(UTC)
    current_version.valid_to = now
    values = {f: getattr(current_version, f) for f in (*REQUEST_CONTENT_FIELDS, "status")}
    values.update({k: v for k, v in changes.items() if k in (*REQUEST_CONTENT_FIELDS, "status")})
    levels = dict(version_levels(db, [current_version.id])[current_version.id])
    for axis_key, level_id in (changes.get("levels") or {}).items():
        if level_id is None:
            levels.pop(axis_key, None)
        else:
            levels[axis_key] = level_id
    new_version = EnhancementRequestVersion(
        request_id=request.id, version_number=current_version.version_number + 1, valid_from=now, valid_to=None,
        change_note=change_note, created_by=actor.id, created_at=now, **values,
    )
    db.add(new_version)
    db.flush()
    _write_levels(db, new_version.id, levels)
    db.flush()
    return new_version


def transition_request(
    db: Session, request: EnhancementRequest, current: EnhancementRequestVersion, target: EnhancementRequestStatus,
    actor: User, *, comment: str = "",
) -> EnhancementRequestVersion:
    """Moves a request to `target` as a new version.

    Declining stores `comment` as the decline reason; a request moved out of `DECLINED` clears it.

    Raises:
        ValueError: For an illegal move, a direct move to `DUPLICATE`, an archived request, or declining
            without a reason.
    """
    if request.is_archived:
        raise ValueError("An archived request cannot change status; unarchive it first.")
    if target == _S.DUPLICATE:
        raise ValueError("A request becomes a duplicate by being merged into another request.")
    if target not in ALLOWED_TRANSITIONS[current.status]:
        raise ValueError(
            f"Cannot move a request from '{request_status_label(current.status.value)}' to "
            f"'{request_status_label(target.value)}'."
        )
    changes: dict[str, Any] = {"status": target}
    if target == _S.DECLINED:
        if not comment.strip():
            raise ValueError("A reason is required to decline a request.")
        changes["decline_reason"] = comment.strip()
    elif current.status == _S.DECLINED:
        changes["decline_reason"] = ""
    note = comment.strip() or (
        f"Status: {request_status_label(current.status.value)} -> {request_status_label(target.value)}."
    )
    return apply_new_version(db, request, current, actor, changes=changes, change_note=note)


def archive_request(request: EnhancementRequest, actor: User) -> None:
    """Soft-archives a request."""
    request.is_archived = True
    request.archived_at = datetime.now(UTC)
    request.archived_by = actor.id


def unarchive_request(request: EnhancementRequest) -> None:
    """Reverses `archive_request`."""
    request.is_archived = False
    request.archived_at = None
    request.archived_by = None


def list_project_requests(db: Session, project_id: uuid.UUID, *, include_archived: bool = False) -> list[EnhancementRequest]:
    """The project's own requests in identifier order (oldest first); archived ones only when asked."""
    query = select(EnhancementRequest).where(EnhancementRequest.project_id == project_id)
    if not include_archived:
        query = query.where(EnhancementRequest.is_archived.is_(False))
    return list(db.scalars(query.order_by(EnhancementRequest.created_at, EnhancementRequest.unique_code)).all())


def list_organization_requests(
    db: Session, organization_id: uuid.UUID, *, include_archived: bool = False
) -> list[EnhancementRequest]:
    """The organisation's own (inbox) requests in identifier order; archived ones only when asked."""
    query = select(EnhancementRequest).where(
        EnhancementRequest.organization_id == organization_id,
        EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
    )
    if not include_archived:
        query = query.where(EnhancementRequest.is_archived.is_(False))
    return list(db.scalars(query.order_by(EnhancementRequest.created_at, EnhancementRequest.unique_code)).all())


#: Statuses the list's "Open only" view keeps (mirrors `REQUEST_OPEN_STATUSES` in the frontend types).
REQUEST_OPEN_STATUSES = frozenset({_S.NEW, _S.UNDER_REVIEW, _S.ACCEPTED})


def filter_requests(
    db: Session, holder: RecordOwner, requests: list[EnhancementRequest], *,
    status: EnhancementRequestStatus | None = None, open_only: bool = False, search: str | None = None,
    scored: ScoredFilter | None = None, missing_axis: str | None = None, scoring_model: Sequence[str] | None = None,
) -> list[EnhancementRequest]:
    """The requests a list's filters keep, in their given order: one status, only open ones, a
    case-insensitive match on the code, title or description, and/or their scoring state. The list endpoints,
    the record-table export and the MCP list tools share this, so a filter added here reaches all of them.

    Args:
        db: Active session (read only).
        holder: The project (or organisation inbox) the requests belong to.
        requests: Candidate requests of that one owner.
        status: Keep only this status.
        open_only: Keep only `REQUEST_OPEN_STATUSES`.
        search: Keep only requests whose code, title or description contains this text.
        scored: Keep only requests scored, or not scored, under the first of `scoring_model` (else the default).
        missing_axis: Keep only requests with no level on this scoring axis.
        scoring_model: The model keys chosen when viewing.
    """
    requests = keep_by_scoring(
        db, holder.organization_id, holder.project_id, requests,
        scored=scored, missing_axis=missing_axis, model_keys=scoring_model,
    )
    if not requests or (status is None and not open_only and not search):
        return requests
    versions = current_versions(db, EnhancementRequestVersion, "request_id", [r.id for r in requests])
    needle = search.casefold() if search else None
    kept = []
    for request in requests:
        version = versions[request.id]
        if status is not None and version.status != status:
            continue
        if open_only and version.status not in REQUEST_OPEN_STATUSES:
            continue
        if needle and needle not in f"{request.unique_code} {version.title} {version.description}".casefold():
            continue
        kept.append(request)
    return kept


def get_submission_policy(db: Session, project_id: uuid.UUID) -> SubmissionPolicy:
    """The project's submission policy (`MEMBERS` until an administrator sets one)."""
    row = db.scalar(select(ProjectFeedbackSettings).where(ProjectFeedbackSettings.project_id == project_id))
    return row.submission_policy if row is not None else SubmissionPolicy.MEMBERS


def set_submission_policy(db: Session, project_id: uuid.UUID, policy: SubmissionPolicy) -> ProjectFeedbackSettings:
    """Sets the project's submission policy, creating its settings row on first use (the caller commits)."""
    row = db.scalar(select(ProjectFeedbackSettings).where(ProjectFeedbackSettings.project_id == project_id))
    if row is None:
        row = ProjectFeedbackSettings(project_id=project_id, submission_policy=policy)
        db.add(row)
    else:
        row.submission_policy = policy
    db.flush()
    return row


def resolve_request_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """The project owning a file attached to a project request (or its comment); `None` for an unknown file
    or an organisation request's file (organisation shared resources are authorised by membership)."""
    from app.modules.product_feedback._shared import REQUEST_ATTACHMENTS
    from app.services.module_attachments import resolve_file_project_id

    return resolve_file_project_id(db, REQUEST_ATTACHMENTS, EnhancementRequest, file_id)
