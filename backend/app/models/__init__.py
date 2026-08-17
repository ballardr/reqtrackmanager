"""
Module: models

Imports every ORM model so that `Base.metadata` is fully populated for
Alembic autogeneration and for `Base.metadata.create_all()` in tests.
"""

from app.models.action_type import ActionTypeDefinition
from app.models.audit import AuditEvent, LoginEvent
from app.models.change_request import (
    ChangeRequest,
    ChangeRequestTask,
    ChangeRequestVersion,
    ChangeRequestVote,
    ReviewComment,
)
from app.models.custom_field import CustomFieldDefinition
from app.models.engagement import CommentReaction, Subscription
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.notification import Notification, NotificationPreference
from app.models.organization import (
    Organization,
    OrgGroup,
    OrgGroupMember,
    PendingInvite,
    ReportTemplate,
    ServerSettings,
    UserOrgRole,
)
from app.models.pat import PersonalAccessToken
from app.models.project import (
    FavoriteProject,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectStage,
    StageReviewResponse,
    UserProjectRole,
)
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement import (
    Baseline,
    BaselineItem,
    Requirement,
    RequirementKeyword,
    RequirementLink,
    RequirementReview,
    RequirementVersion,
)
from app.models.requirement_action import RequirementAction, RequirementActionLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User

__all__ = [
    "ActionTypeDefinition",
    "AuditEvent",
    "LoginEvent",
    "ChangeRequest",
    "ChangeRequestTask",
    "ChangeRequestVersion",
    "ChangeRequestVote",
    "ReviewComment",
    "CustomFieldDefinition",
    "CommentReaction",
    "Subscription",
    "FileAsset",
    "RequirementFile",
    "RequirementActionFile",
    "CommentFile",
    "Notification",
    "NotificationPreference",
    "Organization",
    "OrgGroup",
    "OrgGroupMember",
    "PendingInvite",
    "ReportTemplate",
    "ServerSettings",
    "UserOrgRole",
    "PersonalAccessToken",
    "FavoriteProject",
    "Project",
    "ProjectCategory",
    "ProjectComponent",
    "ProjectGroup",
    "ProjectGroupMember",
    "ProjectStage",
    "ProjectStatusDefinition",
    "StageReviewResponse",
    "UserProjectRole",
    "Baseline",
    "BaselineItem",
    "Requirement",
    "RequirementKeyword",
    "RequirementLink",
    "RequirementLinkTypeDefinition",
    "RequirementAction",
    "RequirementActionLink",
    "RequirementReview",
    "RequirementVersion",
    "User",
]
