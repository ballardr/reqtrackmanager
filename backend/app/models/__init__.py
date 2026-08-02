"""
Module: models

Imports every ORM model so that `Base.metadata` is fully populated for
Alembic autogeneration and for `Base.metadata.create_all()` in tests.
"""

from app.models.audit import AuditEvent, LoginEvent
from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.custom_field import CustomFieldDefinition
from app.models.engagement import CommentReaction, Subscription
from app.models.file import FileAsset, RequirementFile
from app.models.notification import Notification, NotificationPreference
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import (
    FavoriteProject,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectStage,
    UserProjectRole,
)
from app.models.requirement import (
    Baseline,
    BaselineItem,
    Requirement,
    RequirementKeyword,
    RequirementLink,
    RequirementVersion,
)
from app.models.user import User

__all__ = [
    "AuditEvent",
    "LoginEvent",
    "ChangeRequest",
    "ChangeRequestVersion",
    "ReviewComment",
    "CustomFieldDefinition",
    "CommentReaction",
    "Subscription",
    "FileAsset",
    "RequirementFile",
    "Notification",
    "NotificationPreference",
    "Organization",
    "OrgGroup",
    "OrgGroupMember",
    "UserOrgRole",
    "FavoriteProject",
    "Project",
    "ProjectCategory",
    "ProjectComponent",
    "ProjectGroup",
    "ProjectGroupMember",
    "ProjectStage",
    "UserProjectRole",
    "Baseline",
    "BaselineItem",
    "Requirement",
    "RequirementKeyword",
    "RequirementLink",
    "RequirementVersion",
    "User",
]
