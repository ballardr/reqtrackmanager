"""
Module: services.codes

Project codes and qualified record codes.

A project's record codes (`REQ-001`) repeat in every project, so a record seen
outside its own project is named with its project code in front:
`ACME-REQ-001`. This module owns the database side of that: assigning and
validating a project's own code against its organisation's policy, and
building and splitting qualified codes. The character rules are in
`app.code_rules`.

Design decisions:
- A project's code is its own, never built from its parents'; nesting is shown
  by breadcrumb, not by the code.
- A qualified code is split on its first hyphen. That is unambiguous because a
  project or organisation code never contains one (`code_rules.code_error`).
- A project code is never equal to its organisation's code, so a qualified code
  for an organisation-scoped record cannot be mistaken for a project's.
- The organisation row is locked while a code is generated, so two projects
  created at once cannot be given the same code.
- The stored `unique_code` of a record never changes; qualification is applied
  when a code is displayed or looked up.

Dependencies: `app.code_rules`, the `Organization` and `Project` models.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.code_rules import (
    CodePolicy,
    candidate_codes,
    code_error,
    default_code_for_name,
    normalise_code,
    policy_error,
)
from app.models.change_request import ChangeRequest
from app.models.enums import CORE_ARTEFACT_TYPES
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.modules.registry import get_all_registered_artefact_types, list_artefact_summaries
from app.services.change_request_summary import change_request_titles
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, get_effective_project_roles, permission_satisfied


def get_policy(org: Organization) -> CodePolicy:
    """The organisation's project-code policy (defaults filling any missing key)."""
    return CodePolicy.from_mapping(org.project_code_policy)


def set_policy(org: Organization, policy: CodePolicy) -> None:
    """Stores `policy` on `org`; existing project codes are left untouched.

    Raises:
        HTTPException: 400 if `policy` is not a usable policy.
    """
    message = policy_error(policy)
    if message is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)
    org.project_code_policy = policy.as_dict()


def _lock_organization(db: Session, organization_id: uuid.UUID) -> Organization:
    """Reads the organisation row `FOR UPDATE`, serialising code generation within it."""
    return db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()


def taken_codes(db: Session, org: Organization, *, exclude_project_id: uuid.UUID | None = None) -> set[str]:
    """Every code a new project in `org` may not use: its projects' codes and the organisation's own."""
    query = select(Project.code).where(Project.organization_id == org.id)
    if exclude_project_id is not None:
        query = query.where(Project.id != exclude_project_id)
    return {code.upper() for code in db.scalars(query)} | {org.code.upper()}


def validate_project_code(
    db: Session, org: Organization, raw: str, *, exclude_project_id: uuid.UUID | None = None
) -> str:
    """Checks a chosen project code against the organisation's policy and uniqueness.

    Args:
        db: An active database session.
        org: The project's organisation.
        raw: The code as typed.
        exclude_project_id: The project being edited, so its own current code is not a clash.

    Returns:
        The normalised (upper-case) code.

    Raises:
        HTTPException: 400 if the code breaks the policy; 409 if another project in the
            organisation, or the organisation itself, already uses it.
    """
    code = normalise_code(raw)
    message = code_error(code, get_policy(org))
    if message is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)
    if code in taken_codes(db, org, exclude_project_id=exclude_project_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"The project code {code} is already in use in this organisation.")
    return code


def generate_project_code(db: Session, organization_id: uuid.UUID, name: str) -> str:
    """The first code derived from `name` that conforms to the organisation's policy and is free.

    Used for automatic assignment, template cloning and import. Locks the organisation row
    until the caller's transaction ends.

    Raises:
        HTTPException: 409 if no free conforming code can be derived (for example a digits-only
            policy whose range is used up).
    """
    org = _lock_organization(db, organization_id)
    taken = taken_codes(db, org)
    for candidate in candidate_codes(name, get_policy(org)):
        if candidate not in taken:
            return candidate
    raise HTTPException(
        status.HTTP_409_CONFLICT, "No free project code could be generated; choose a longer maximum length in the code policy."
    )


def assign_project_code(db: Session, organization_id: uuid.UUID, name: str, requested: str | None) -> str:
    """The code for a project being created through the API, honouring the organisation's policy.

    Automatic assignment generates the code and rejects a supplied one; manual assignment
    requires one and validates it.

    Raises:
        HTTPException: 400 if a code is supplied under automatic assignment, is missing under
            manual assignment, or breaks the policy; 409 if it is taken.
    """
    org = _lock_organization(db, organization_id)
    if get_policy(org).assignment == "auto":
        if requested:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Project codes are assigned automatically in this organisation."
            )
        return generate_project_code(db, organization_id, name)
    if not requested:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project code is required in this organisation.")
    return validate_project_code(db, org, requested)


def change_project_code(db: Session, project: Project, requested: str) -> str:
    """Validates a new code for an existing project; only allowed under manual assignment.

    Returns:
        The normalised code (unchanged input is returned as is, without re-checking the policy,
        because a policy change never rewrites existing codes).

    Raises:
        HTTPException: 400 if codes are assigned automatically or the code breaks the policy;
            409 if it is taken.
    """
    org = _lock_organization(db, project.organization_id)
    if normalise_code(requested) == project.code:
        return project.code
    if get_policy(org).assignment == "auto":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Project codes are assigned automatically in this organisation.")
    return validate_project_code(db, org, requested, exclude_project_id=project.id)


def organization_code_for(name: str) -> str:
    """The code a new organisation called `name` gets (its initials)."""
    return default_code_for_name(name)


def qualify(project_code: str, unique_code: str) -> str:
    """`ACME`, `REQ-001` -> `ACME-REQ-001`."""
    return f"{project_code}-{unique_code}"


def split_qualified(qualified: str) -> tuple[str, str] | None:
    """Splits `ACME-REQ-001` into `("ACME", "REQ-001")` on the first hyphen, upper-casing both;
    `None` if there is nothing on either side."""
    head, sep, rest = qualified.strip().upper().partition("-")
    if not sep or not head or not rest:
        return None
    return head, rest


def find_project_by_code(db: Session, organization_id: uuid.UUID, project_code: str) -> Project | None:
    """The project in `organization_id` whose code is `project_code` (case-insensitive), if any."""
    return db.scalar(
        select(Project).where(Project.organization_id == organization_id, Project.code == project_code.upper())
    )


@dataclass(frozen=True)
class CodedRecord:
    """A record found by its qualified code.

    Attributes:
        artefact_type: The registered artefact type, e.g. `requirement`, `decision`.
        id: The record's id.
        project_id: The project that owns it.
        qualified_code: The code as displayed outside the project, e.g. `ACME-REQ-001`.
        label: The record's summary label (`REQ-001 Title`).
    """

    artefact_type: str
    id: uuid.UUID
    project_id: uuid.UUID
    qualified_code: str
    label: str


_CODE_PREFIX = re.compile(r"^[A-Z]{2,5}-\d{3,4}\s+")


def label_title(label: str) -> str:
    """A summary label without its leading record code (`"NEED-001 Title"` -> `"Title"`).

    Bundles refer to a record by its title: a code is numbered afresh on import, so it cannot
    identify the record in the target project.
    """
    return _CODE_PREFIX.sub("", label, count=1)


def _label_code(label: str) -> str:
    """The leading code of a summary label (`"FND-001 Title"` -> `"FND-001"`)."""
    return label.split(" ", 1)[0].upper()


def find_record_by_qualified_code(
    db: Session, user_id: uuid.UUID, organization_id: uuid.UUID, qualified: str
) -> CodedRecord | None:
    """Resolves `ACME-REQ-001` to the record it names, for a user who may see it.

    The project is found by its code within the organisation; the record by its own code
    among that project's requirements, actions and every registered type that offers a
    summary. A record is returned only if the user is a member of its project, holds `view`
    on its type there, and its module is enabled for the project, so an inaccessible record
    and a missing one look the same (`None`).

    Args:
        db: An active database session.
        user_id: The caller.
        organization_id: The organisation the code is looked up in.
        qualified: The qualified code, any case.

    Returns:
        The record, or `None` when the code is malformed, names no project, or no visible
        record carries it.
    """
    parts = split_qualified(qualified)
    if parts is None:
        return None
    project_code, unique_code = parts
    project = find_project_by_code(db, organization_id, project_code)
    if project is None or not get_effective_project_roles(db, user_id, project.id):
        return None
    held = get_effective_permissions(db, user_id, project_id=project.id)

    def result(artefact_type: str, record_id: uuid.UUID, label: str) -> CodedRecord | None:
        if not permission_satisfied(held, encode_permission(artefact_type, "view")):
            return None
        return CodedRecord(artefact_type, record_id, project.id, qualify(project.code, unique_code), label)

    requirement = db.execute(
        select(Requirement.id).where(Requirement.project_id == project.id, Requirement.unique_code == unique_code)
    ).scalar_one_or_none()
    if requirement is not None:
        return result("requirement", requirement, unique_code)
    action = db.execute(
        select(RequirementAction.id, RequirementAction.title).where(
            RequirementAction.project_id == project.id, RequirementAction.unique_code == unique_code
        )
    ).first()
    if action is not None:
        return result("requirement_action", action.id, f"{unique_code} {action.title}")
    change_request = db.scalar(
        select(ChangeRequest).where(ChangeRequest.project_id == project.id, ChangeRequest.unique_code == unique_code)
    )
    if change_request is not None:
        title = change_request_titles(db, [change_request])[change_request.id]
        return result("change_request", change_request.id, f"{unique_code} {title}")
    for artefact_type in sorted(get_all_registered_artefact_types() - CORE_ARTEFACT_TYPES):
        for summary in list_artefact_summaries(db, project.id, artefact_type):
            if summary.project_id == project.id and _label_code(summary.label) == unique_code:
                return result(artefact_type, summary.id, summary.label)
    return None
