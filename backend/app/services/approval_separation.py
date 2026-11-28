"""
Module: services.approval_separation

The one server rule for whether the person who created a record may approve it, per record type with an approval gate.

Responsibilities:
- Name the types the rule covers (`approval_gates`): every registered lifecycle with a gated state, plus the core
  requirement and change request.
- Resolve the rule for a project (`resolve_project_separations`, `resolve_separation`): the project's own choice, else
  the nearest ancestor project's, else the type's default (the creator may approve); an organisation requirement beats
  the choice unless the project is exempt.
- Enforce it at an approval (`enforce_approval`): the creator is refused when a separate approver is required; where
  the creator may approve, the record is marked self-approved (`RecordSelfApproval`) with one `self_approved` audit
  event, and a comment is required when the permission was set on purpose (`ResolvedSeparation.deliberate`).
- Write the three tiers (`set_project_separation`, `set_org_required`, `add_exemption`, `remove_exemption`), each with
  one audit event (type keys only), and carry the configuration in bundles and to a project made from a template.

Design decisions:
- The creator is the record's `creator_id`: every gated type has one and it is always a user, so a group is never the
  submitter. The approver is the acting user whatever route gave them the approval permission, so a member of a group
  that holds the approval permission is compared as themselves. Server administrators are not exempt.
- The default is "the creator may approve", which is what every type did before the setting existed (so it needs no
  comment, only the mark); an organisation or a project moves a type to "separate approver required". A project that
  chose "creator may approve", or is exempt from the organisation's requirement, has decided deliberately and its
  self-approvals need a comment.
- A project's stored choice is kept when the organisation requires the rule, so removing the requirement gives the
  project's own choice back. Resolution never loops per record.
- A record the organisation owns (no project) follows the organisation's requirement alone.
- A type whose lifecycle sets `self_approval_org_admins_only` narrows "the creator may approve" to a creator who is an
  organisation administrator, who always comments. The settings apply to it as to any type.
- A caller whose type counts more people than the creator as having submitted a record (a named requester) says so
  with `submitter`; such a person is held to the same rule as the creator.
- Turning the rule back on never undoes past approvals; the mark describes the latest approval only.

Dependencies: `modules.registry` (gates and labels), `services.lifecycles` (module availability),
`services.project_hierarchy` (ancestor chain), `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.lifecycle import (
    OrganizationApprovalSeparationExemption,
    OrganizationApprovalSeparationRequirement,
    ProjectApprovalSeparationSetting,
    RecordSelfApproval,
)
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_artefact_type_label,
    get_lifecycles,
    get_module_approval_gates,
    is_module_enabled_for_project,
)
from app.services.audit import log_event
from app.services.lifecycles import enabled_for_organization
from app.services.project_hierarchy import get_project_chain_ids
from app.services.rbac import get_effective_org_roles

AUDIT_ENTITY_TYPE = "approval_separation"
SELF_APPROVED_ACTION = "self_approved"
Source = Literal["project", "parent_project", "default"]

# Core types with an approval gate that no module registers a lifecycle for.
CORE_GATES: tuple[str, ...] = ("requirement", "change_request")


@dataclass(frozen=True)
class ApprovalGate:
    """A record type that has an approval gate.

    Attributes:
        artefact_type: The registered record type.
        label: Its singular display name.
        module_key: The module that registered it, `""` for a core type.
        org_admins_only: Only an organisation administrator may approve a record they submitted.
    """

    artefact_type: str
    label: str
    module_key: str
    org_admins_only: bool = False


@dataclass(frozen=True)
class ResolvedSeparation:
    """The rule for one record type as it applies to one project.

    Attributes:
        gate: The type.
        own: The project's own choice, or `None` when it has none.
        chosen: The choice the project resolves to (own, else the nearest ancestor's, else the default).
        source: Where `chosen` came from.
        required: Whether the organisation requires a separate approver.
        exempt: Whether the organisation's requirement does not bind this project.
    """

    gate: ApprovalGate
    own: bool | None
    chosen: bool
    source: Source
    required: bool
    exempt: bool

    @property
    def enforced(self) -> bool:
        """Whether the organisation's requirement binds the project."""
        return self.required and not self.exempt

    @property
    def deliberate(self) -> bool:
        """Whether the permission for the creator to approve was set on purpose (a project or ancestor choice, or an
        exemption from the organisation's requirement) rather than being the type's default."""
        return self.source != "default" or (self.required and self.exempt)

    @property
    def separate(self) -> bool:
        """Whether a person other than the creator must approve now."""
        return self.enforced or self.chosen


def approval_gates() -> dict[str, ApprovalGate]:
    """Every record type with an approval gate, by type: core types first, then each lifecycle with a gated state, then
    the types a module declares in `ModuleDefinition.approval_gates`."""
    gates = {t: ApprovalGate(t, get_artefact_type_label(t), "") for t in CORE_GATES}
    for artefact_type, (module_key, definition) in get_lifecycles().items():
        if definition.gated:
            gates.setdefault(
                artefact_type,
                ApprovalGate(artefact_type, definition.label, module_key, definition.self_approval_org_admins_only),
            )
    for artefact_type, (module_key, declared) in get_module_approval_gates().items():
        gates.setdefault(artefact_type, ApprovalGate(artefact_type, declared.label, module_key))
    return gates


def _gate_enabled_for_project(db: Session, gate: ApprovalGate, project_id: uuid.UUID) -> bool:
    """Whether the gated type's module (and the sub-component serving the type) is enabled for the project; a type a module
    declares only in `approval_gates` is served by the module as a whole."""
    if gate.module_key and artefact_type_module(gate.artefact_type) is None:
        return is_module_enabled_for_project(db, project_id, gate.module_key)
    return artefact_type_enabled_for_project(db, gate.artefact_type, project_id)


def _gate(artefact_type: str) -> ApprovalGate:
    """The gate of `artefact_type`.

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    gate = approval_gates().get(artefact_type)
    if gate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That record type has no approval gate.")
    return gate


def _exempt(rows: list[OrganizationApprovalSeparationExemption], project_id: uuid.UUID | None) -> bool:
    """Whether any exemption in `rows` (already limited to the project's chain) covers the project."""
    return project_id is not None and any(ex.project_id == project_id or ex.include_children for ex in rows)


def _source(depth: int) -> Source:
    """Where a choice found `depth` steps up the project chain comes from."""
    return "project" if depth == 0 else "parent_project"


def resolve_project_separations(db: Session, project: Project) -> list[ResolvedSeparation]:
    """The rule for every gated type of the project's enabled modules, in type-name order.

    Args:
        db: Active session (read only).
        project: The project.
    """
    chain = get_project_chain_ids(db, project.id)
    own_rows: dict[str, dict[uuid.UUID, bool]] = {}
    for row in db.scalars(
        select(ProjectApprovalSeparationSetting).where(ProjectApprovalSeparationSetting.project_id.in_(chain))
    ):
        own_rows.setdefault(row.artefact_type, {})[row.project_id] = row.separate_approver
    required = set(db.scalars(
        select(OrganizationApprovalSeparationRequirement.artefact_type).where(
            OrganizationApprovalSeparationRequirement.organization_id == project.organization_id
        )
    ))
    exemptions: dict[str, list[OrganizationApprovalSeparationExemption]] = {}
    if required:
        for ex in db.scalars(
            select(OrganizationApprovalSeparationExemption).where(
                OrganizationApprovalSeparationExemption.organization_id == project.organization_id,
                OrganizationApprovalSeparationExemption.project_id.in_(chain),
            )
        ):
            exemptions.setdefault(ex.artefact_type, []).append(ex)
    out: list[ResolvedSeparation] = []
    for artefact_type, gate in sorted(approval_gates().items()):
        if not _gate_enabled_for_project(db, gate, project.id):
            continue
        chosen = False
        source: Source = "default"
        for depth, project_id in enumerate(chain):
            if project_id in own_rows.get(artefact_type, {}):
                chosen, source = own_rows[artefact_type][project_id], _source(depth)
                break
        out.append(ResolvedSeparation(
            gate=gate, own=own_rows.get(artefact_type, {}).get(project.id), chosen=chosen, source=source,
            required=artefact_type in required, exempt=_exempt(exemptions.get(artefact_type, []), project.id),
        ))
    return out


def resolve_separation(
    db: Session, *, artefact_type: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> ResolvedSeparation:
    """The rule for one type in one project, or for a record the organisation owns (`project_id` `None`).

    Args:
        db: Active session (read only).
        artefact_type: A registered type with an approval gate.
        organization_id: The record's organisation.
        project_id: The record's project, `None` for a record with no project.

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    gate = _gate(artefact_type)
    required = db.scalar(
        select(OrganizationApprovalSeparationRequirement.id).where(
            OrganizationApprovalSeparationRequirement.organization_id == organization_id,
            OrganizationApprovalSeparationRequirement.artefact_type == artefact_type,
        )
    ) is not None
    if project_id is None:
        return ResolvedSeparation(gate=gate, own=None, chosen=False, source="default", required=required, exempt=False)
    chain = get_project_chain_ids(db, project_id)
    rows = {
        row.project_id: row.separate_approver
        for row in db.scalars(
            select(ProjectApprovalSeparationSetting).where(
                ProjectApprovalSeparationSetting.project_id.in_(chain),
                ProjectApprovalSeparationSetting.artefact_type == artefact_type,
            )
        )
    }
    chosen = False
    source: Source = "default"
    for depth, ancestor in enumerate(chain):
        if ancestor in rows:
            chosen, source = rows[ancestor], _source(depth)
            break
    exempt = required and _exempt(
        list(db.scalars(
            select(OrganizationApprovalSeparationExemption).where(
                OrganizationApprovalSeparationExemption.organization_id == organization_id,
                OrganizationApprovalSeparationExemption.artefact_type == artefact_type,
                OrganizationApprovalSeparationExemption.project_id.in_(chain),
            )
        )),
        project_id,
    )
    return ResolvedSeparation(
        gate=gate, own=rows.get(project_id), chosen=chosen, source=source, required=required, exempt=exempt,
    )


def record_context(db: Session, artefact_type: str, record_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None] | None:
    """Who created a record and where it lives.

    Args:
        db: Active session (read only).
        artefact_type: A registered type with an approval gate.
        record_id: The record.

    Returns:
        `(creator id, project id, organisation id)` (the organisation id is set only for a record the organisation
        owns), or `None` when the record does not exist.

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    from app.models.change_request import ChangeRequest
    from app.models.requirement import Requirement

    _gate(artefact_type)
    declared = get_module_approval_gates().get(artefact_type)
    if declared is not None:
        return declared[1].record_context(db, record_id)
    model = {"requirement": Requirement, "change_request": ChangeRequest}.get(artefact_type)
    if model is None:
        model = get_lifecycles()[artefact_type][1].record_model
    record = db.get(model, record_id)
    if record is None:
        return None
    return record.creator_id, record.project_id, getattr(record, "organization_id", None)


def _clear_mark(db: Session, artefact_type: str, record_id: uuid.UUID) -> None:
    """Deletes the self-approval mark of a record, if any."""
    db.execute(delete(RecordSelfApproval).where(
        RecordSelfApproval.artefact_type == artefact_type, RecordSelfApproval.record_id == record_id,
    ))


def enforce_approval(
    db: Session, *, user: User, artefact_type: str, record_id: uuid.UUID, creator_id: uuid.UUID,
    organization_id: uuid.UUID, project_id: uuid.UUID | None, comment: str | None, check_record: bool = True,
    submitter: bool = False,
) -> bool:
    """Applies the rules of the moment `user` approves a record; call after the approval permission is checked and
    before the record changes. Nothing is committed.

    Every approval path passes here, so the checks the project's baseline policy enables for approvals run here too
    (`services.baseline.check_record_approval`), once the separation rule has admitted the approver.

    Another person approving clears the record's self-approval mark. The creator approving is refused when a separate
    approver is required; otherwise it marks the record (`RecordSelfApproval`) with one `self_approved` audit event and,
    when the permission was set on purpose, needs a comment.

    Args:
        db: Active session.
        user: The person approving.
        artefact_type: The record's registered type (one with an approval gate).
        record_id: The record.
        creator_id: The record's creator.
        organization_id: The record's organisation.
        project_id: The record's project, `None` for a record the organisation owns.
        comment: The approver's comment, when the approval takes one.
        check_record: Whether to run the approval checks now. `False` for a stage baseline, which runs its own checks over
            everything it approves, and for a path that changes the record as it approves it and runs them afterwards.
        submitter: The person counts as having submitted the record although they did not create it.

    Returns:
        Whether this approval was a self-approval.

    Raises:
        HTTPException: 403 when a separate approver is required, or the type limits self-approval to organisation
            administrators and the person is not one; 400 when a deliberate or restricted self-approval has no comment; 409
            with `{message, failures[]}` when an approval check fails.
    """
    if user.id != creator_id and not submitter:
        if check_record:
            _run_approval_checks(db, user, artefact_type, record_id, project_id)
        _clear_mark(db, artefact_type, record_id)
        return False
    resolved = resolve_separation(db, artefact_type=artefact_type, organization_id=organization_id, project_id=project_id)
    label = resolved.gate.label.lower()
    did = "created" if user.id == creator_id else "requested"
    if resolved.gate.org_admins_only and not _is_org_admin(db, user.id, organization_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only an organisation administrator may approve a {label} that they {did} themselves.",
        )
    if resolved.separate:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"A different person must approve this {label}: a separate approver is required and you {did} it.",
        )
    if (resolved.deliberate or resolved.gate.org_admins_only) and not (comment or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A comment is required to approve a {label} that you {did} yourself.",
        )
    if check_record:
        _run_approval_checks(db, user, artefact_type, record_id, project_id)
    _clear_mark(db, artefact_type, record_id)
    db.add(RecordSelfApproval(
        artefact_type=artefact_type, record_id=record_id, organization_id=organization_id, project_id=project_id,
        approved_by=user.id, approved_at=datetime.now(UTC),
    ))
    db.flush()
    log_event(
        db, entity_type=artefact_type, entity_id=record_id, action=SELF_APPROVED_ACTION, actor_id=user.id,
        organization_id=organization_id, project_id=project_id, detail={"self_approved": True},
    )
    return True


def _run_approval_checks(db: Session, user: User, artefact_type: str, record_id: uuid.UUID, project_id: uuid.UUID | None) -> None:
    """The project's approval checks over one record. A record the organisation owns belongs to no project's policy."""
    project = None if project_id is None else db.get(Project, project_id)
    if project is None:
        return
    # Imported here: `services.baseline` imports this module for the separation rule of the drafts it approves.
    from app.services.baseline import check_record_approval

    check_record_approval(db, project, user, artefact_type, record_id)


def enforce_record_approval(
    db: Session, *, user: User, artefact_type: str, record: object, comment: str | None, submitter: bool = False,
) -> bool:
    """`enforce_approval` for a record object with `id`, `creator_id`, `project_id` (and `organization_id` when the
    organisation owns it), so a caller need not resolve the organisation itself.

    Returns:
        Whether this approval was a self-approval.

    Raises:
        HTTPException: As `enforce_approval`.
    """
    project_id = getattr(record, "project_id", None)
    if project_id is not None:
        project = db.get(Project, project_id)
        organization_id = None if project is None else project.organization_id
    else:
        organization_id = getattr(record, "organization_id", None)
    if organization_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found.")
    return enforce_approval(
        db, user=user, artefact_type=artefact_type, record_id=record.id,  # type: ignore[attr-defined]
        creator_id=record.creator_id,  # type: ignore[attr-defined]
        organization_id=organization_id, project_id=project_id, comment=comment, submitter=submitter,
    )


def _is_org_admin(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    """Whether the person is an administrator of the organisation, directly or through a group."""
    return OrgRole.ORG_ADMIN in get_effective_org_roles(db, user_id, organization_id)


def may_self_approve(
    db: Session, *, user_id: uuid.UUID, artefact_type: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> bool:
    """Whether a person who submitted a record of the type may approve it (permission to approve is checked apart).

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    resolved = resolve_separation(db, artefact_type=artefact_type, organization_id=organization_id, project_id=project_id)
    if resolved.separate:
        return False
    return not resolved.gate.org_admins_only or _is_org_admin(db, user_id, organization_id)


def approval_status(
    db: Session, *, user: User, artefact_type: str, record_id: uuid.UUID, creator_id: uuid.UUID,
    organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> dict:
    """What a record's page shows about approval separation.

    Returns:
        `{"self_approved": bool, "approved_by": user id or None, "approved_at": datetime or None,
        "needs_other_approver": bool}`; the last is true when `user` created the record and may not approve it, so the
        page can explain why approval is unavailable to them.
    """
    mark = db.scalar(select(RecordSelfApproval).where(
        RecordSelfApproval.artefact_type == artefact_type, RecordSelfApproval.record_id == record_id,
    ))
    needs_other = user.id == creator_id and not may_self_approve(
        db, user_id=user.id, artefact_type=artefact_type, organization_id=organization_id, project_id=project_id,
    )
    return {
        "self_approved": mark is not None, "approved_by": None if mark is None else mark.approved_by,
        "approved_at": None if mark is None else mark.approved_at, "needs_other_approver": needs_other,
    }


# --- configuration -----------------------------------------------------------------------------


def set_project_separation(
    db: Session, *, project: Project, artefact_type: str, separate: bool | None, actor_id: uuid.UUID,
) -> None:
    """Sets the project's own choice for one type (`None` follows the nearest ancestor project, else the default).

    Raises:
        HTTPException: 404 for a type without an approval gate; 409 when relaxing a type the organisation requires and
            the project is not exempt.
    """
    _gate(artefact_type)
    if separate is False and resolve_separation(
        db, artefact_type=artefact_type, organization_id=project.organization_id, project_id=project.id,
    ).enforced:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The organisation requires a separate approver for this record type.",
        )
    row = db.scalar(select(ProjectApprovalSeparationSetting).where(
        ProjectApprovalSeparationSetting.project_id == project.id,
        ProjectApprovalSeparationSetting.artefact_type == artefact_type,
    ))
    before = None if row is None else row.separate_approver
    if separate is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ProjectApprovalSeparationSetting(
            project_id=project.id, artefact_type=artefact_type, separate_approver=separate,
        ))
    else:
        row.separate_approver = separate
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=project.id, action="project_updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={"artefact_type": artefact_type, "from": before, "to": separate, "inherits": separate is None},
    )
    db.flush()


def set_org_required(
    db: Session, *, organization: Organization, artefact_type: str, required: bool, actor_id: uuid.UUID,
) -> None:
    """Sets whether the organisation requires a separate approver for one type in every project that is not exempt.

    Raises:
        HTTPException: 404 for a type without an approval gate.
    """
    _gate(artefact_type)
    row = db.scalar(select(OrganizationApprovalSeparationRequirement).where(
        OrganizationApprovalSeparationRequirement.organization_id == organization.id,
        OrganizationApprovalSeparationRequirement.artefact_type == artefact_type,
    ))
    if required and row is None:
        db.add(OrganizationApprovalSeparationRequirement(organization_id=organization.id, artefact_type=artefact_type))
    elif not required and row is not None:
        db.delete(row)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="organization_updated", actor_id=actor_id,
        organization_id=organization.id, detail={"artefact_type": artefact_type, "required": required},
    )
    db.flush()


def add_exemption(
    db: Session, *, organization: Organization, artefact_type: str, project: Project, include_children: bool,
    actor_id: uuid.UUID,
) -> None:
    """Exempts a project (optionally with its nested children) from the organisation's requirement for one type.

    Raises:
        HTTPException: 404 for a type without an approval gate; 422 for a project of another organisation.
    """
    _gate(artefact_type)
    if project.organization_id != organization.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The project belongs to another organisation.")
    row = db.scalar(select(OrganizationApprovalSeparationExemption).where(
        OrganizationApprovalSeparationExemption.organization_id == organization.id,
        OrganizationApprovalSeparationExemption.artefact_type == artefact_type,
        OrganizationApprovalSeparationExemption.project_id == project.id,
    ))
    if row is None:
        db.add(OrganizationApprovalSeparationExemption(
            organization_id=organization.id, artefact_type=artefact_type, project_id=project.id,
            include_children=include_children,
        ))
    else:
        row.include_children = include_children
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="exemption_added", actor_id=actor_id,
        organization_id=organization.id, project_id=project.id,
        detail={"artefact_type": artefact_type, "include_children": include_children},
    )
    db.flush()


def remove_exemption(
    db: Session, *, organization: Organization, artefact_type: str, project_id: uuid.UUID, actor_id: uuid.UUID,
) -> None:
    """Removes a project's exemption for one type.

    Raises:
        HTTPException: 404 when the project has no such exemption.
    """
    row = db.scalar(select(OrganizationApprovalSeparationExemption).where(
        OrganizationApprovalSeparationExemption.organization_id == organization.id,
        OrganizationApprovalSeparationExemption.artefact_type == artefact_type,
        OrganizationApprovalSeparationExemption.project_id == project_id,
    ))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project has no exemption.")
    db.delete(row)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="exemption_removed", actor_id=actor_id,
        organization_id=organization.id, project_id=project_id, detail={"artefact_type": artefact_type},
    )
    db.flush()


def organization_separations(db: Session, organization: Organization) -> list[dict]:
    """The organisation-level view: each gated type whose module the organisation has enabled.

    Returns:
        One dict per type (type-name order): `gate`, `required` and `exemptions` (`[(project id, include_children)]`
        in creation order).
    """
    required = set(db.scalars(
        select(OrganizationApprovalSeparationRequirement.artefact_type).where(
            OrganizationApprovalSeparationRequirement.organization_id == organization.id
        )
    ))
    exemptions: dict[str, list[tuple[uuid.UUID, bool]]] = {}
    for ex in db.scalars(
        select(OrganizationApprovalSeparationExemption).where(
            OrganizationApprovalSeparationExemption.organization_id == organization.id
        ).order_by(OrganizationApprovalSeparationExemption.created_at)
    ):
        exemptions.setdefault(ex.artefact_type, []).append((ex.project_id, ex.include_children))
    return [
        {"gate": gate, "required": artefact_type in required, "exemptions": exemptions.get(artefact_type, [])}
        for artefact_type, gate in sorted(approval_gates().items())
        if not gate.module_key or enabled_for_organization(db, organization.id, artefact_type, gate.module_key)
    ]


# --- bundles and templates ---------------------------------------------------------------------


def export_project(db: Session, project: Project) -> list[dict]:
    """The project's own choices as `[{"artefact_type", "separate_approver"}]`, in type order."""
    return [
        {"artefact_type": row.artefact_type, "separate_approver": row.separate_approver}
        for row in db.scalars(
            select(ProjectApprovalSeparationSetting).where(ProjectApprovalSeparationSetting.project_id == project.id)
            .order_by(ProjectApprovalSeparationSetting.artefact_type)
        )
    ]


def import_project(
    db: Session, project: Project, entries: list[dict] | None, warn: Callable[[str], None],
) -> None:
    """Applies bundle `entries` to `project`; a type without an approval gate is reported through `warn` and skipped.

    The choice is stored as written: an organisation requirement beats it when the rule is resolved, so an import can
    never relax a type the organisation requires. Not committed.
    """
    gates = approval_gates()
    for entry in entries or []:
        artefact_type = str(entry.get("artefact_type", ""))
        if artefact_type not in gates:
            warn(f"The approval settings for {artefact_type or 'an unnamed type'} were not imported: unknown record type.")
            continue
        value = bool(entry.get("separate_approver"))
        row = db.scalar(select(ProjectApprovalSeparationSetting).where(
            ProjectApprovalSeparationSetting.project_id == project.id,
            ProjectApprovalSeparationSetting.artefact_type == artefact_type,
        ))
        if row is None:
            db.add(ProjectApprovalSeparationSetting(
                project_id=project.id, artefact_type=artefact_type, separate_approver=value,
            ))
        else:
            row.separate_approver = value
    db.flush()


def copy_project(db: Session, source: Project, target: Project) -> None:
    """Copies `source`'s own choices to `target` (a project made from a template)."""
    import_project(db, target, export_project(db, source), lambda _message: None)


def export_org(db: Session, organization: Organization, project_ref_by_id: Mapping[uuid.UUID, str]) -> dict:
    """The organisation's requirements and exemptions as bundle sections.

    Returns:
        `{"approval_separation_requirements": [artefact type], "approval_separation_exemptions": [{"artefact_type",
        "project_ref", "include_children"}]}`, ordered by type.
    """
    rows = organization_separations(db, organization)
    return {
        "approval_separation_requirements": [r["gate"].artefact_type for r in rows if r["required"]],
        "approval_separation_exemptions": [
            {"artefact_type": r["gate"].artefact_type, "project_ref": project_ref_by_id[pid], "include_children": inc}
            for r in rows for pid, inc in r["exemptions"] if pid in project_ref_by_id
        ],
    }


def import_org(
    db: Session, organization: Organization, data: dict, project_id_by_ref: Mapping[str, uuid.UUID],
    actor_id: uuid.UUID, warn: Callable[[str], None],
) -> None:
    """Applies a bundle's requirements and exemptions to `organization`; a merge into an existing organisation uses
    the same call because both only add what is named.

    Args:
        db: Active session (not committed).
        organization: The target organisation.
        data: The bundle's `org.json`.
        project_id_by_ref: The imported projects by bundle reference (an exemption of a project that was not imported
            is skipped).
        actor_id: The acting user.
        warn: Receives a message for each entry that could not be applied.
    """
    for artefact_type in data.get("approval_separation_requirements") or []:
        try:
            set_org_required(
                db, organization=organization, artefact_type=str(artefact_type), required=True, actor_id=actor_id,
            )
        except HTTPException as error:
            warn(f"An approval requirement was not imported: {error.detail}")
    for entry in data.get("approval_separation_exemptions") or []:
        project_id = project_id_by_ref.get(str(entry.get("project_ref", "")))
        project = None if project_id is None else db.get(Project, project_id)
        if project is None:
            continue
        try:
            add_exemption(
                db, organization=organization, artefact_type=str(entry.get("artefact_type", "")), project=project,
                include_children=bool(entry.get("include_children")), actor_id=actor_id,
            )
        except HTTPException as error:
            warn(f"An approval exemption was not imported: {error.detail}")
