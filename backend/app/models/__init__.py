"""
Module: models

Imports every ORM model so that `Base.metadata` is fully populated for
Alembic autogeneration and for `Base.metadata.create_all()` in tests.
"""

from app.models.action_type import ActionTypeDefinition
from app.models.audit import AuditEvent, LoginEvent
from app.models.change_request import (
    ChangeRequest,
    ChangeRequestProposedLink,
    ChangeRequestTask,
    ChangeRequestVersion,
    ChangeRequestVote,
    ReviewComment,
)
from app.models.credential_reset import CredentialResetToken
from app.models.custom_field import CustomFieldDefinition
from app.models.custom_role import (
    CustomRoleDefinition,
    CustomRolePermission,
    GroupCustomRoleGrant,
    UserCustomRoleGrant,
)
from app.models.definition_suppression import ProjectDefinitionSuppression
from app.models.engagement import CommentReaction, Subscription
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.generated_report import GeneratedReport
from app.models.module import OrganizationModuleEnablement, OrganizationModuleEntitlement, ServerModuleDefault
from app.models.module_role import GroupModuleRole, ModuleRoleDefinitionRow, UserModuleRole
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
    OrgGroupProjectRole,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    ProjectStage,
    StageReviewResponse,
    UserProjectRole,
)
from app.models.project_status import ProjectStatusDefinition
from app.models.record_policy import OrganizationRecordSensitivityOverride, ServerRecordSensitivityDefault
from app.models.relationship import ArtefactLink
from app.models.report_folder import ReportFolder
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.report_pack import ReportPack, ReportPackSetOverride, ReportPackVariableSet, ReportPackVersion
from app.models.report_placement import ReportPlacement
from app.models.report_snippet import SavedReportSnippet
from app.models.requirement import (
    Baseline,
    BaselineItem,
    Requirement,
    RequirementReview,
    RequirementVersion,
)
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ArtefactTypeLinkRuleEntry,
    ProjectLinkTypeVisibility,
    RequirementLinkTypeDefinition,
)
from app.models.scoring import ScoringBand, ScoringCellRating, ScoringLevel, ScoringModelDefault
from app.models.sequence import OrganizationSequenceCounter, ProjectSequenceCounter
from app.models.server_role import UserServerRole
from app.models.tag import ArtefactTag, Tag
from app.models.user import User

__all__ = [
    "ActionTypeDefinition",
    "ArtefactTag",
    "Tag",
    "AuditEvent",
    "LoginEvent",
    "ChangeRequest",
    "ChangeRequestTask",
    "ChangeRequestProposedLink",
    "ChangeRequestVersion",
    "ChangeRequestVote",
    "ReviewComment",
    "CredentialResetToken",
    "CustomFieldDefinition",
    "CustomRoleDefinition",
    "CustomRolePermission",
    "GroupCustomRoleGrant",
    "UserCustomRoleGrant",
    "CommentReaction",
    "Subscription",
    "FileAsset",
    "GeneratedReport",
    "RequirementFile",
    "RequirementActionFile",
    "CommentFile",
    "Notification",
    "NotificationPreference",
    "Organization",
    "OrgGroup",
    "OrgGroupMember",
    "PendingInvite",
    "ReportLayout",
    "ReportLayoutVersion",
    "ReportPack",
    "SavedReportSnippet",
    "ReportPackSetOverride",
    "ReportPackVariableSet",
    "ReportPackVersion",
    "ReportFolder",
    "ReportPlacement",
    "ReportTemplate",
    "ServerSettings",
    "UserOrgRole",
    "PersonalAccessToken",
    "OrganizationRecordSensitivityOverride",
    "ServerRecordSensitivityDefault",
    "FavoriteProject",
    "OrgGroupProjectRole",
    "Project",
    "ProjectCategory",
    "ProjectComponent",
    "ProjectGroup",
    "ProjectGroupMember",
    "ProjectGroupRole",
    "ProjectMemberSource",
    "ProjectStage",
    "ProjectStatusDefinition",
    "StageReviewResponse",
    "UserProjectRole",
    "ArtefactLink",
    "Baseline",
    "BaselineItem",
    "Requirement",
    "ArtefactTypeLinkRule",
    "ArtefactTypeLinkRuleEntry",
    "ProjectDefinitionSuppression",
    "ProjectLinkTypeVisibility",
    "RequirementLinkTypeDefinition",
    "RequirementAction",
    "RequirementReview",
    "RequirementVersion",
    "OrganizationSequenceCounter",
    "ProjectSequenceCounter",
    "ScoringBand",
    "ScoringCellRating",
    "ScoringLevel",
    "ScoringModelDefault",
    "UserServerRole",
    "OrganizationModuleEntitlement",
    "OrganizationModuleEnablement",
    "ServerModuleDefault",
    "GroupModuleRole",
    "ModuleRoleDefinitionRow",
    "UserModuleRole",
    "User",
]
