"""
Module: models.enums

All fixed vocabularies used by the domain model. Ossa (v1) intentionally uses
a small, fixed set of organisation and project roles rather than a
customisable permission system (customisable roles/attributes are a Pelion
(v2) concern per docs/requirements.md).
"""

import enum


class OrgRole(str, enum.Enum):
    """Organisation-level permission roles (C-U-01)."""

    ORG_ADMIN = "org_admin"
    PROJECT_CREATOR = "project_creator"
    MEMBER = "member"


class ProjectRole(str, enum.Enum):
    """Project-level permission roles (C-U-03)."""

    PROJECT_MANAGER = "project_manager"
    PROJECT_ADMINISTRATOR = "project_administrator"
    STAKEHOLDER = "stakeholder"
    MEMBER = "member"


class StageStatus(str, enum.Enum):
    """Lifecycle states for a project stage (introduction, C-G-08).

    ARCHIVED is a terminal state a stage can be moved to manually (e.g. via
    `transition_stage`); it carries no special gating logic of its own —
    unlike APPROVED it doesn't write a baseline or require the project
    manager role, it's purely a display/filtering state.
    """

    SCOPING = "scoping"
    REVIEW = "review"
    APPROVED = "approved"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RequirementLevel(str, enum.Enum):
    """Whether a requirement's content is mandatory or advisory."""

    REQUIREMENT = "requirement"
    RECOMMENDED = "recommended"


class RequirementStatus(str, enum.Enum):
    """Lifecycle states for a requirement (C-G-11)."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ChangeRequestKind(str, enum.Enum):
    """Whether a change request proposes a new requirement or a modification."""

    NEW_REQUIREMENT = "new_requirement"
    MODIFY_REQUIREMENT = "modify_requirement"


class ChangeRequestStatus(str, enum.Enum):
    """Lifecycle states for a change request (introduction, C-G-03)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ReviewTargetType(str, enum.Enum):
    """What a discussion thread comment is attached to (C-R-01)."""

    REQUIREMENT = "requirement"
    CHANGE_REQUEST = "change_request"


class RequirementLinkType(str, enum.Enum):
    """Traceability relationship types between requirements (C-G-09)."""

    RELATES_TO = "relates_to"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
