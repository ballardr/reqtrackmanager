"""
Module: modules.traceability.exceptions

The traceability exception: an approved departure of one record from one rule. Every write path, who may take it, and
the one transition function.

Responsibilities:
- Raise and edit a request (`create_exception`, `update_exception`) with one audit event each (keys and ids only).
- Move it between states (`transition`), checking who may, through the core lifecycle, approval and separation rules.
- Record a periodic review (`record_exception_review`), archive and restore (`set_archived`).
- Say what a person may do (`allowed_actions`) and which exceptions they may see (`readable`).
- Notify the people who decide and those who asked (`NOTIFICATION_TYPES`).

Design decisions:
- Anyone who may read the record's type may ask for an exception for it; asking grants nothing.
- Approval follows the approval policy seam: the `approve_traceability_exceptions` atom, the type's `approve_baseline`
  atom or a role the project's policy names. A rule of an Enforced profile needs the organisation-level right instead
  (`has_org_authority`), so a project cannot waive what its organisation enforces.
- A requester does not approve their own exception, unless they are an organisation administrator and the approval
  separation setting does not require another person; their approval then needs a comment and is marked self-approved.
  "Requester" is the person who raised the record, the named requester and every member of a requester group, all
  handled by the core separation rule. A requester cannot remove themselves from the requester field, which would
  otherwise lift that rule.
- An approved exception is locked: only its nominated approver and review date change. Anything else needs it revoked
  and requested again, so what is in force is exactly what was approved.
- An exception in force cannot be archived: removing cover is a revocation, with its comment and its authority.
- A nominated approver is told of the request and may record reviews; the nomination grants no approval right.
- Dates are calendar days judged against the caller's day.

Dependencies: `exception_cover`, `rules`, `models`, `services.lifecycles`, `services.approval_policy`,
`services.approval_separation`, `services.review_engine`, `services.record_summaries`, `services.principals`,
`services.notifications`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole, PrincipalType
from app.models.organization import UserOrgRole
from app.models.project import Project
from app.models.user import User
from app.modules.registry import NotificationTypeDefinition
from app.modules.traceability import exception_cover, rules
from app.modules.traceability._shared import (
    APPROVE_TRACEABILITY_EXCEPTIONS,
    EXCEPTION_ARTEFACT_TYPE,
    EXCEPTION_CODE_PREFIX,
    MANAGE_ORG_TRACEABILITY,
    MANAGE_PROJECT_TRACEABILITY,
)
from app.modules.traceability.enums import ExceptionStatus
from app.modules.traceability.models import (
    EXCEPTION_TITLE_MAX_LENGTH,
    TraceabilityException,
    TraceabilityExceptionComment,
)
from app.schemas.principal import PrincipalRef
from app.services import approval_policy, approval_separation, notifications, record_summaries, review_engine
from app.services.audit import log_event
from app.services.client_date import effective_today
from app.services.codes import qualify
from app.services.lifecycles import check_move
from app.services.long_text_core import NOTE_LIMIT
from app.services.permissions import encode_permission
from app.services.principals import (
    is_principal_member,
    principal_columns,
    principal_recipients,
    principal_ref,
    validate_principal,
)
from app.services.rbac import (
    get_effective_permissions,
    get_effective_project_managers,
    lock_row_for_update,
    permission_satisfied,
)
from app.services.sequences import generate_unique_code

REQUESTED_TYPE = "traceability_exception_requested"
DECIDED_TYPE = "traceability_exception_decided"
REVIEW_DUE_TYPE = "traceability_exception_review_due"
REVIEW_OVERDUE_TYPE = "traceability_exception_review_overdue"

NOTIFICATION_TYPES: tuple[NotificationTypeDefinition, ...] = (
    NotificationTypeDefinition(REQUESTED_TYPE, "Traceability exception requested", target_kinds=("record",)),
    NotificationTypeDefinition(DECIDED_TYPE, "Traceability exception approved, rejected or revoked", target_kinds=("record",)),
    NotificationTypeDefinition(REVIEW_DUE_TYPE, "Traceability exception review due soon", target_kinds=("record",)),
    NotificationTypeDefinition(REVIEW_OVERDUE_TYPE, "Traceability exception review overdue", target_kinds=("record",)),
)

#: Every legal move; `transition` and the registered lifecycle both read it.
TRANSITIONS: dict[ExceptionStatus, frozenset[ExceptionStatus]] = {
    ExceptionStatus.REQUESTED: frozenset({ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.WITHDRAWN}),
    ExceptionStatus.APPROVED: frozenset({ExceptionStatus.REVOKED}),
    ExceptionStatus.REJECTED: frozenset({ExceptionStatus.REQUESTED}),
    ExceptionStatus.WITHDRAWN: frozenset({ExceptionStatus.REQUESTED}),
    ExceptionStatus.REVOKED: frozenset({ExceptionStatus.REQUESTED}),
}

#: The moves that need a comment saying why.
_COMMENT_REQUIRED = frozenset({ExceptionStatus.REJECTED, ExceptionStatus.REVOKED})
#: The fields of an approved exception that may still change.
_EDITABLE_WHEN_APPROVED = frozenset({"approver", "review_date"})
_DECISION_VERB = {
    ExceptionStatus.APPROVED: "approved", ExceptionStatus.REJECTED: "rejected", ExceptionStatus.REVOKED: "revoked",
}


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


# --- who may ---------------------------------------------------------------------------------------


def _requester(exception: TraceabilityException) -> PrincipalRef | None:
    return principal_ref(exception.requester_type, exception.requester_id)


def _approver(exception: TraceabilityException) -> PrincipalRef | None:
    return principal_ref(exception.approver_type, exception.approver_id)


def is_requester(db: Session, exception: TraceabilityException, user_id: uuid.UUID) -> bool:
    """Whether the person raised the exception, is its named requester or is a member of its requester group."""
    return user_id == exception.creator_id or is_principal_member(db, _requester(exception), user_id)


def _held(db: Session, user: User, project: Project) -> set[str]:
    return get_effective_permissions(db, user.id, project_id=project.id)


def may_view_type(held: set[str], artefact_type: str) -> bool:
    """Whether the held permissions let a person read records of the type."""
    return permission_satisfied(held, encode_permission(artefact_type, "view"))


def may_manage(held: set[str]) -> bool:
    """Whether the held permissions let a person manage every exception of the project."""
    return permission_satisfied(held, MANAGE_PROJECT_TRACEABILITY) or permission_satisfied(
        held, encode_permission(EXCEPTION_ARTEFACT_TYPE, "manage")
    )


def has_org_authority(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    """Whether the person holds the exception right for the whole organisation (an organisation role, not a project one):
    the approval atom or the management of organisation traceability."""
    held = get_effective_permissions(db, user_id, organization_id=organization_id)
    return permission_satisfied(held, APPROVE_TRACEABILITY_EXCEPTIONS) or permission_satisfied(held, MANAGE_ORG_TRACEABILITY)


def may_decide(db: Session, user: User, project: Project, entry: rules.EffectiveRule | None) -> bool:
    """Whether the person may approve, reject or revoke exceptions to the rule, before the requester bar is applied."""
    if entry is not None and entry.enforced:
        return has_org_authority(db, user.id, project.organization_id)
    return approval_policy.may_approve(
        db, user, artefact_type=EXCEPTION_ARTEFACT_TYPE, organization_id=project.organization_id, project_id=project.id,
        default=permission_satisfied(_held(db, user, project), APPROVE_TRACEABILITY_EXCEPTIONS),
    )


def rule_entries(db: Session, project: Project) -> dict[uuid.UUID, rules.EffectiveRule]:
    """The project's rules in effect, by id."""
    return {e.rule.id: e for e in rules.effective_rules(db, project)}


def readable(held: set[str], rows: Sequence[TraceabilityException]) -> list[TraceabilityException]:
    """The rows whose excepted record type the person may read, so an exception never names a record to someone who may
    not open it."""
    allowed = {t for t in {r.artefact_type for r in rows} if may_view_type(held, t)}
    return [r for r in rows if r.artefact_type in allowed]


def get_in_project(db: Session, project_id: uuid.UUID, exception_id: uuid.UUID, held: set[str]) -> TraceabilityException:
    """The project's exception with that id, when the person may read its record's type.

    Raises:
        HTTPException: 404 otherwise.
    """
    row = db.get(TraceabilityException, exception_id)
    if row is None or row.project_id != project_id or not may_view_type(held, row.artefact_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Traceability exception not found.")
    return row


def allowed_actions(
    db: Session, user: User, project: Project, exception: TraceabilityException, entry: rules.EffectiveRule | None,
) -> list[str]:
    """What the person may do to the exception now."""
    held = _held(db, user, project)
    own = is_requester(db, exception, user.id)
    manager = may_manage(held)
    if exception.is_archived:
        return ["unarchive"] if own or manager else []
    decides = may_decide(db, user, project, entry)
    state = exception.status
    actions: list[str] = []
    if own or manager:
        actions.append("edit")
    if state == ExceptionStatus.REQUESTED:
        if decides:
            if entry is not None and entry.active and (not own or _may_self_approve(db, user, project)):
                actions.append("approve")
            actions.append("reject")
        if own or manager:
            actions.append("withdraw")
    elif state == ExceptionStatus.APPROVED:
        if decides or own or manager:
            actions.append("revoke")
    elif own or manager:
        actions.append("resubmit")
    if state in (ExceptionStatus.REQUESTED, ExceptionStatus.APPROVED) and _may_review(db, user, exception, own, manager, decides):
        actions.append("review")
    if (own or manager) and exception_cover.no_cover_reason(exception, entry, effective_today()) is not None:
        actions.append("archive")
    return actions


def _may_self_approve(db: Session, user: User, project: Project) -> bool:
    return approval_separation.may_self_approve(
        db, user_id=user.id, artefact_type=EXCEPTION_ARTEFACT_TYPE, organization_id=project.organization_id,
        project_id=project.id,
    )


def _may_review(db: Session, user: User, exception: TraceabilityException, own: bool, manager: bool, decides: bool) -> bool:
    return own or manager or decides or is_principal_member(db, _approver(exception), user.id)


# --- validation ------------------------------------------------------------------------------------


def _clean_title(title: str | None, rule_name: str) -> str:
    cleaned = " ".join((title or "").split()) or f"Exception to {rule_name}"
    return cleaned[:EXCEPTION_TITLE_MAX_LENGTH]


def _clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if not cleaned:
        raise _unprocessable("An exception needs a reason.")
    return cleaned


def _check_future(value: date | None, name: str) -> None:
    if value is not None and value < effective_today():
        raise _unprocessable(f"The {name} cannot be in the past.")


def _check_review_date(db: Session, project: Project, review_date: date | None) -> None:
    """Refuses a past review date, or one later than the review policy's interval allows."""
    _check_future(review_date, "review date")
    if review_date is None:
        return
    policy = review_engine.review_policy(db, project.id, EXCEPTION_ARTEFACT_TYPE)
    try:
        review_engine.check_next_review_date(policy, effective_today(), review_date)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc


def _require_rule(db: Session, project: Project, rule_id: uuid.UUID) -> rules.EffectiveRule:
    entry = rules.get_rule_in_project(db, project, rule_id)
    if entry is None or not entry.active:
        raise _unprocessable("That rule is not in effect for this project.")
    return entry


def _require_record(db: Session, project: Project, artefact_type: str, artefact_id: uuid.UUID) -> None:
    summary = record_summaries.read_summaries(db, project.id, artefact_type, [artefact_id]).get(artefact_id)
    if summary is None or summary.is_archived or summary.project_id != project.id:
        raise _unprocessable("The project does not hold that record.")


# --- writes ----------------------------------------------------------------------------------------


def _log(db: Session, exception: TraceabilityException, action: str, actor_id: uuid.UUID, detail: dict[str, Any]) -> None:
    log_event(
        db, entity_type=EXCEPTION_ARTEFACT_TYPE, entity_id=exception.id, action=action, actor_id=actor_id,
        project_id=exception.project_id, detail=detail,
    )


def create_exception(
    db: Session, *, project: Project, actor: User, artefact_type: str, artefact_id: uuid.UUID, rule_id: uuid.UUID,
    title: str | None, reason: str, requester: PrincipalRef | None, approver: PrincipalRef | None,
    expires_on: date | None, review_date: date | None, notify: bool = True,
) -> TraceabilityException:
    """Raises a request for an exception.

    Args:
        db: Active session (not committed).
        project: The project.
        actor: The person raising it.
        artefact_type / artefact_id: A live record of the project.
        rule_id: A rule in effect for the project that applies to the record's type.
        title: Defaults to "Exception to <rule name>".
        reason: Why; must not be blank.
        requester: Defaults to the actor.
        approver: A nominated approver.
        expires_on: The last day covered, or `None`.
        review_date: The next review, or `None`.
        notify: `False` for a record import, which tells nobody.

    Returns:
        The stored request.

    Raises:
        HTTPException: 403 when the actor may not read the record's type; 422 for a rule, record, date or person that is
            not valid.
    """
    entry = _require_rule(db, project, rule_id)
    if entry.rule.source_type != artefact_type:
        raise _unprocessable("That rule does not apply to this type of record.")
    if not may_view_type(_held(db, actor, project), artefact_type):
        raise _forbidden("You may not read records of this type.")
    _require_record(db, project, artefact_type, artefact_id)
    cleaned_reason = _clean_reason(reason)
    _check_future(expires_on, "expiry date")
    _check_review_date(db, project, review_date)
    wanted = requester or PrincipalRef(type=PrincipalType.USER, id=actor.id)
    validate_principal(db, wanted, organization_id=project.organization_id, project_id=project.id, field="requester")
    validate_principal(db, approver, organization_id=project.organization_id, project_id=project.id, field="approver")
    exception = TraceabilityException(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, EXCEPTION_ARTEFACT_TYPE, EXCEPTION_CODE_PREFIX),
        creator_id=actor.id, title=_clean_title(title, entry.rule.name), artefact_type=artefact_type,
        artefact_id=artefact_id, rule_id=entry.rule.id, rule_name=entry.rule.name, reason=cleaned_reason,
        status=ExceptionStatus.REQUESTED, expires_on=expires_on, review_date=review_date,
        **principal_columns("requester", wanted), **principal_columns("approver", approver),
    )
    db.add(exception)
    db.flush()
    _log(db, exception, "created", actor.id, {
        "unique_code": exception.unique_code, "title": exception.title, "rule_id": str(entry.rule.id),
        "record_type": artefact_type, "record_id": str(artefact_id),
    })
    if notify:
        _notify_requested(db, project, exception, entry, actor)
    return exception


def update_exception(
    db: Session, *, project: Project, exception: TraceabilityException, actor: User, changes: Mapping[str, Any],
) -> None:
    """Changes the fields named in `changes` (`title`, `reason`, `requester`, `approver`, `expires_on`, `review_date`).

    Raises:
        HTTPException: 403 when the actor is neither a requester nor a manager, or removes themselves from the requester;
            409 for an archived exception or a locked field of an approved one; 422 for a value that is not valid.
    """
    if not changes:
        return
    own = is_requester(db, exception, actor.id)
    if not own and not may_manage(_held(db, actor, project)):
        raise _forbidden("Only the requester or a Traceability Manager may change this exception.")
    lock_row_for_update(db, TraceabilityException, exception.id)
    db.refresh(exception)
    if exception.is_archived:
        raise _conflict("An archived exception cannot be changed; restore it first.")
    changed = _changed_values(exception, changes)
    if exception.status == ExceptionStatus.APPROVED and set(changed) - _EDITABLE_WHEN_APPROVED:
        raise _conflict("An approved exception is locked. Revoke it and request it again to change it.")
    if "title" in changed:
        exception.title = _clean_title(changed["title"], exception.rule_name)
    if "reason" in changed:
        exception.reason = _clean_reason(changed["reason"] or "")
    if "expires_on" in changed:
        _check_future(changed["expires_on"], "expiry date")
        exception.expires_on = changed["expires_on"]
    if "review_date" in changed:
        _check_review_date(db, project, changed["review_date"])
        exception.review_date = changed["review_date"]
    for field in ("requester", "approver"):
        if field not in changed:
            continue
        ref = changed[field]
        if field == "requester":
            if ref is None:
                raise _unprocessable("An exception needs a requester.")
            if (
                actor.id != exception.creator_id and is_principal_member(db, _requester(exception), actor.id)
                and not is_principal_member(db, ref, actor.id)
            ):
                raise _forbidden("A requester cannot remove themselves from the requester; another person must change it.")
        validate_principal(db, ref, organization_id=project.organization_id, project_id=project.id, field=field)
        for column, value in principal_columns(field, ref).items():
            setattr(exception, column, value)
    if changed:
        db.flush()
        _log(db, exception, "updated", actor.id, {"changed": sorted(changed)})


def _changed_values(exception: TraceabilityException, changes: Mapping[str, Any]) -> dict[str, Any]:
    """The entries of `changes` that differ from what is stored, so sending a form back unchanged writes nothing."""
    current: dict[str, Any] = {
        "title": exception.title, "reason": exception.reason, "requester": _requester(exception),
        "approver": _approver(exception), "expires_on": exception.expires_on, "review_date": exception.review_date,
    }
    out = {}
    for key, value in changes.items():
        if key in ("title", "reason") and isinstance(value, str):
            value = value.strip()
        if current[key] != value:
            out[key] = value
    return out


def transition(
    db: Session, *, project: Project, exception: TraceabilityException, target: ExceptionStatus, actor: User,
    comment: str = "", via_mcp: bool = False,
) -> None:
    """Moves an exception to `target`, the one function every action goes through.

    Raises:
        HTTPException: 403 when the actor may not make the move (including a requester approving who may not); 409 for a move the
            lifecycle does not allow, or an approval of something that can no longer be covered; 422 for a missing comment.
    """
    lock_row_for_update(db, TraceabilityException, exception.id)
    db.refresh(exception)
    if exception.is_archived:
        raise _conflict("An archived exception cannot change state; restore it first.")
    previous = exception.status
    try:
        check_move(db, project.id, EXCEPTION_ARTEFACT_TYPE, previous.value, target.value, record_id=exception.id)
    except ValueError as exc:
        raise _conflict(str(exc)) from exc
    comment = comment.strip()
    if len(comment) > NOTE_LIMIT:
        raise _unprocessable("The comment is too long.")
    entry = None if exception.rule_id is None else rules.get_rule_in_project(db, project, exception.rule_id)
    require_may_move(db, project, exception, entry, target, actor)
    if target in _COMMENT_REQUIRED and not comment:
        raise _unprocessable("A comment saying why is required.")
    if target in (ExceptionStatus.APPROVED, ExceptionStatus.REQUESTED):
        if entry is None or not entry.active:
            raise _conflict("The rule is no longer in effect for this project.")
        _require_record(db, project, exception.artefact_type, exception.artefact_id)
    if target == ExceptionStatus.APPROVED and entry is not None:
        if exception_cover.is_expired(exception, effective_today()):
            raise _conflict("The expiry date has passed; change it before approving.")
        approval_separation.enforce_record_approval(
            db, user=actor, artefact_type=EXCEPTION_ARTEFACT_TYPE, record=exception, comment=comment,
            submitter=is_requester(db, exception, actor.id),
        )
        exception.approved_fingerprint = exception_cover.rule_fingerprint(entry.rule)
        exception.org_approved = has_org_authority(db, actor.id, project.organization_id)
        exception.rule_name = entry.rule.name
    if target in _DECISION_VERB:
        exception.decided_by_id, exception.decided_at = actor.id, datetime.now(UTC)
        exception.decision_comment = comment
    elif target == ExceptionStatus.REQUESTED:
        exception.decided_by_id = exception.decided_at = exception.approved_fingerprint = None
        exception.decision_comment, exception.org_approved = "", False
    exception.status = target
    db.flush()
    detail: dict[str, Any] = {"from": previous.value, "to": target.value}
    if comment:
        detail["comment"] = comment
    if via_mcp:
        detail["via"] = "mcp"
    _log(db, exception, "status_changed", actor.id, detail)
    if target == ExceptionStatus.REQUESTED and entry is not None:
        _notify_requested(db, project, exception, entry, actor)
    elif target in _DECISION_VERB:
        _notify_decided(db, project, exception, target, actor)


def require_may_move(
    db: Session, project: Project, exception: TraceabilityException, entry: rules.EffectiveRule | None,
    target: ExceptionStatus, actor: User,
) -> None:
    """The permission each move needs.

    Raises:
        HTTPException: 403.
    """
    own = is_requester(db, exception, actor.id)
    manager = may_manage(_held(db, actor, project))
    if target in (ExceptionStatus.APPROVED, ExceptionStatus.REJECTED):
        if not may_decide(db, actor, project, entry):
            raise _forbidden(
                "This rule is enforced by the organisation, so only an organisation-level approver may decide its exceptions."
                if entry is not None and entry.enforced else "You may not decide traceability exceptions in this project."
            )
    elif target == ExceptionStatus.REVOKED:
        if not (own or manager or may_decide(db, actor, project, entry)):
            raise _forbidden("You may not revoke this exception.")
    elif not (own or manager):
        raise _forbidden("Only the requester or a Traceability Manager may do this.")


def record_exception_review(
    db: Session, *, project: Project, exception: TraceabilityException, actor: User, next_review_date: date | None,
    notes: str,
) -> None:
    """Records a periodic review and sets the date of the next one.

    Raises:
        HTTPException: 403 when the actor may not review it; 409 for an exception that is not requested or approved, or is
            archived; 422 for a next date that is not in the future or breaks the review policy's interval.
    """
    entry = None if exception.rule_id is None else rules.get_rule_in_project(db, project, exception.rule_id)
    own = is_requester(db, exception, actor.id)
    if not _may_review(db, actor, exception, own, may_manage(_held(db, actor, project)), may_decide(db, actor, project, entry)):
        raise _forbidden("You may not review this exception.")
    lock_row_for_update(db, TraceabilityException, exception.id)
    db.refresh(exception)
    if exception.is_archived or exception.status not in (ExceptionStatus.REQUESTED, ExceptionStatus.APPROVED):
        raise _conflict("Only a requested or approved exception is reviewed.")
    today = effective_today()
    if next_review_date is not None and next_review_date <= today:
        raise _unprocessable("The next review date must be in the future.")
    policy = review_engine.review_policy(db, project.id, EXCEPTION_ARTEFACT_TYPE)
    try:
        review_engine.check_next_review_date(policy, today, next_review_date)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    exception.review_date = next_review_date
    if notes.strip():
        db.add(TraceabilityExceptionComment(exception_id=exception.id, author_id=actor.id, body=notes.strip()))
    db.flush()
    _log(db, exception, "reviewed", actor.id, {
        "next_review_date": None if next_review_date is None else next_review_date.isoformat(),
    })


def set_archived(db: Session, *, project: Project, exception: TraceabilityException, actor: User, archived: bool) -> None:
    """Archives or restores an exception.

    Raises:
        HTTPException: 403 when the actor is neither a requester nor a manager; 409 when archiving one that is in force.
    """
    if not is_requester(db, exception, actor.id) and not may_manage(_held(db, actor, project)):
        raise _forbidden("Only the requester or a Traceability Manager may do this.")
    lock_row_for_update(db, TraceabilityException, exception.id)
    db.refresh(exception)
    if exception.is_archived == archived:
        return
    if archived:
        entry = None if exception.rule_id is None else rules.get_rule_in_project(db, project, exception.rule_id)
        if exception_cover.no_cover_reason(exception, entry, effective_today()) is None:
            raise _conflict("This exception is in force. Revoke it before archiving it.")
    exception.is_archived = archived
    exception.archived_at = datetime.now(UTC) if archived else None
    exception.archived_by = actor.id if archived else None
    db.flush()
    _log(db, exception, "archived" if archived else "unarchived", actor.id, {})


# --- notifications ---------------------------------------------------------------------------------


def _org_admin_ids(db: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(select(UserOrgRole.user_id).where(
        UserOrgRole.organization_id == organization_id, UserOrgRole.role == OrgRole.ORG_ADMIN,
    )))


def _send(
    db: Session, project: Project, exception: TraceabilityException, user_ids: set[uuid.UUID], *, kind: str, title: str,
    body: str, actor_id: uuid.UUID,
) -> None:
    """Notifies each person who may read the record's type; the actor is never told."""
    code = qualify(project.code, exception.unique_code)
    for user in db.scalars(select(User).where(User.id.in_(user_ids), User.is_active.is_(True))) if user_ids else ():
        if not may_view_type(get_effective_permissions(db, user.id, project_id=project.id), exception.artefact_type):
            continue
        notifications.notify(
            db, user, notification_type=kind, title=f"{code}: {title}", body=body, project_id=project.id,
            entity_type=EXCEPTION_ARTEFACT_TYPE, entity_id=str(exception.id), actor_id=actor_id,
        )


def _notify_requested(
    db: Session, project: Project, exception: TraceabilityException, entry: rules.EffectiveRule, actor: User,
) -> None:
    """Tells the nominated approver, else the organisation's administrators for an enforced rule, else the project
    managers."""
    recipients = principal_recipients(db, [_approver(exception)])
    if not recipients:
        recipients = (
            _org_admin_ids(db, project.organization_id) if entry.enforced else get_effective_project_managers(db, project.id)
        )
    _send(
        db, project, exception, recipients, kind=REQUESTED_TYPE, title="exception requested",
        body=f'"{exception.title}" asks for an exception to the traceability rule "{entry.rule.name}".', actor_id=actor.id,
    )


def _notify_decided(
    db: Session, project: Project, exception: TraceabilityException, target: ExceptionStatus, actor: User,
) -> None:
    recipients = principal_recipients(db, [_requester(exception), principal_ref("user", exception.creator_id)])
    verb = _DECISION_VERB[target]
    _send(
        db, project, exception, recipients, kind=DECIDED_TYPE, title=f"exception {verb}",
        body=f'"{exception.title}" was {verb}.', actor_id=actor.id,
    )
