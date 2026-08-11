"""
Module: schemas.project

Request/response models for projects, stages, components, categories,
project groups, and project role assignments (C-G-04, C-G-07, C-G-08,
C-U-03, C-U-11).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator

from app.models.enums import ProjectRole, StageReviewResponseChoice, StageStatus

# Fixed, documented set of overridable terminology keys (C-C-03). Not a
# freeform key-value store — terminology only covers these nouns.
TERMINOLOGY_KEYS = {"project", "stage", "component", "category", "requirement", "change_request"}


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str
    summary: str = ""
    template_project_id: UUID | None = None  # C-E-05: create from an existing template project
    terminology: dict[str, str] = {}
    is_template: bool = False

    @field_validator("terminology")
    @classmethod
    def _validate_terminology_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Rejects any terminology key outside the fixed `TERMINOLOGY_KEYS` set (C-C-03)."""
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"Unknown terminology keys: {sorted(unknown)}. Allowed: {sorted(TERMINOLOGY_KEYS)}")
        return value


class ProjectOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    summary: str
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False
    is_template: bool = False
    allow_member_change_requests: bool = True
    terminology: dict[str, str] = {}


class ProjectImportResult(BaseModel):
    """Outcome of importing a project bundle (`POST /projects/import`) —
    the new project plus any human-readable warnings about references
    (typically users) that couldn't be matched in the target deployment
    and were remapped/dropped instead, so data loss during import is
    visible rather than silent."""

    project: ProjectOut
    warnings: list[str] = []


class ProjectUpdate(BaseModel):
    """Project settings update (name/summary, C-U-13 toggle, C-E-05 template flag)."""

    name: str | None = None
    summary: str | None = None
    allow_member_change_requests: bool | None = None
    is_template: bool | None = None


class TerminologyUpdate(BaseModel):
    """Per-project terminology overrides (C-C-03)."""

    terminology: dict[str, str]

    @field_validator("terminology")
    @classmethod
    def _validate_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Rejects any terminology key outside the fixed `TERMINOLOGY_KEYS` set (C-C-03)."""
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"Unknown terminology keys: {sorted(unknown)}. Allowed: {sorted(TERMINOLOGY_KEYS)}")
        return value


class ProjectListItemOut(ProjectOut):
    """Project list view row (U-E-03): includes stage and role context."""

    current_stage_name: str | None = None
    current_stage_status: StageStatus | None = None
    my_roles: list[ProjectRole] = []
    is_favorite: bool = False
    organization_name: str = ""
    requirement_count: int = 0


class ProjectStageCreate(BaseModel):
    name: str


class ProjectStageUpdate(BaseModel):
    name: str


class ProjectStageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    status: StageStatus
    sort_order: int
    is_current: bool
    approved_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    review_deadline: datetime | None = None


class StageReviewDeadlineSet(BaseModel):
    review_deadline: datetime | None = None


class StageReviewResponseCreate(BaseModel):
    response: StageReviewResponseChoice
    comment: str | None = None


class StageReviewResponseOut(BaseModel):
    id: UUID
    stage_id: UUID
    user_id: UUID
    response: StageReviewResponseChoice
    comment: str | None = None
    responded_at: datetime


class StageCompleteRequest(BaseModel):
    cascade_to_requirements: bool = False


class ComponentCreate(BaseModel):
    name: str
    prefix: str


class ComponentUpdate(BaseModel):
    name: str
    prefix: str


class ComponentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    prefix: str
    sort_order: int


class CategoryCreate(BaseModel):
    name: str
    prefix: str
    component_id: UUID


class CategoryUpdate(BaseModel):
    name: str
    prefix: str


class CategoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    component_id: UUID
    name: str
    prefix: str
    sort_order: int


class MoveDirection(BaseModel):
    direction: str  # "up" or "down"


class ProjectGroupCreate(BaseModel):
    name: str
    role: ProjectRole


class ProjectGroupMemberAdd(BaseModel):
    user_id: UUID | None = None
    org_group_id: UUID | None = None


class ProjectGroupOut(BaseModel):
    id: UUID
    name: str
    role: ProjectRole
    is_default: bool
    member_user_ids: list[UUID]
    member_org_group_ids: list[UUID]


class UserProjectRoleAssign(BaseModel):
    user_id: UUID
    role: ProjectRole


class UserProjectRoleAssignByEmail(BaseModel):
    """Adds a project member by email — may resolve to an existing account
    (in or outside the project's organisation) or, if
    `Organization.external_user_policy` permits, a brand-new invited
    account. See `routers/projects.py::assign_project_role_by_email`."""

    email: EmailStr
    role: ProjectRole


class AssignByEmailOut(BaseModel):
    """Outcome of `assign_project_role_by_email` — the frontend shows a
    different message for each:
      - "added": an existing account was granted the role immediately.
      - "invited": a new account has no account yet; an email with a
        signup link was sent, and the role is granted once they sign up.
      - "sso_provisioned": the target org is SSO-only, so the account and
        role were both created immediately; the invitee just needs to sign
        in via SSO to start using it.
    """

    outcome: str


class StageProgressOut(BaseModel):
    """A single project stage's requirement-completion progress, for the
    dashboard's per-stage progress bars."""

    stage_id: UUID
    name: str
    status: StageStatus
    requirement_count: int
    completed_percent: float


class ProjectMetricsOut(BaseModel):
    """Project overview dashboard metrics (U-P-05).

    `requirements_by_status`/`stage_progress` back the dashboard's chart
    views; they group by the project's actual status/stage model rather
    than a separate "release version" concept, since ReqTrackManager tracks
    requirement lifecycle status and project stages, not independent
    parallel release versions (see docs/decisions.md).

    `file_count` is the requirement's explicitly-listed metric ("number of
    files in project, if files are implemented") — counts distinct
    `FileAsset` rows attached to a requirement in this project, i.e.
    requirement attachments, not organisation-wide shared resources (which
    aren't scoped to a single project).
    """

    requirement_count: int
    requirement_completed_percent: float
    change_requests_proposed: int
    change_requests_approved: int
    change_requests_rejected: int
    file_count: int = 0
    requirements_by_status: dict[str, int] = {}
    stage_progress: list[StageProgressOut] = []
