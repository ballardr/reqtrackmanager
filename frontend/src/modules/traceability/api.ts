/**
 * Module: modules/traceability/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for the Governance endpoints of
 * `backend/app/modules/traceability/{router,project_router,health_router}.py`: the organisation's governance profiles with
 * their lifecycle, approval, review and baseline policy, a project's view and choices of those profiles and its own policy,
 * and governance health with its settings. `organizationId` / `projectId` match the endpoint's scope.
 */
import { api } from "../../api/client";
import type {
  ApproverRole,
  BaselineFields,
  BaselineKind,
  BaselinePreview,
  BaselineSettings,
  ExemptionValues,
  Health,
  HealthDefault,
  HealthMode,
  HealthSettings,
  HealthSettingsValues,
  Profile,
  ProfileApproval,
  ProfileBaseline,
  ProfileCreateValues,
  ProfileDetail,
  ProfileLifecycle,
  ProfileReview,
  ProfileStageWorkflow,
  ProfileTarget,
  ProfileTargetKind,
  ProfileUpdateValues,
  ProjectApproval,
  ProjectBaseline,
  ProjectProfiles,
  ProjectReview,
  ReviewSettingsValues,
  StageWorkflowMode,
} from "./types";

const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/traceability`;
const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/traceability`;
const profileUrl = (organizationId: string, profileId: string) => `${orgBase(organizationId)}/profiles/${profileId}`;

/** The organisation's governance profiles and each profile's policy. */
export const profileApi = {
  list: (organizationId: string) => api.get<Profile[]>(`${orgBase(organizationId)}/profiles`),
  get: (organizationId: string, profileId: string) => api.get<ProfileDetail>(profileUrl(organizationId, profileId)),
  create: (organizationId: string, values: ProfileCreateValues) =>
    api.post<ProfileDetail>(`${orgBase(organizationId)}/profiles`, values),
  update: (organizationId: string, profileId: string, values: ProfileUpdateValues) =>
    api.patch<ProfileDetail>(profileUrl(organizationId, profileId), values),
  remove: (organizationId: string, profileId: string) => api.delete<void>(profileUrl(organizationId, profileId)),
  setTargets: (organizationId: string, profileId: string, targetKind: ProfileTargetKind, targets: ProfileTarget[]) =>
    api.put<ProfileDetail>(`${profileUrl(organizationId, profileId)}/targets`, { target_kind: targetKind, targets }),
  addExemption: (organizationId: string, profileId: string, values: ExemptionValues) =>
    api.post<ProfileDetail>(`${profileUrl(organizationId, profileId)}/exemptions`, values),
  removeExemption: (organizationId: string, profileId: string, projectId: string) =>
    api.delete<ProfileDetail>(`${profileUrl(organizationId, profileId)}/exemptions/${projectId}`),

  lifecycle: (organizationId: string, profileId: string) =>
    api.get<ProfileLifecycle>(`${profileUrl(organizationId, profileId)}/lifecycle`),
  setLifecycleRequired: (organizationId: string, profileId: string, artefactType: string, required: string[]) =>
    api.put<ProfileLifecycle>(`${profileUrl(organizationId, profileId)}/lifecycle/${artefactType}`, { required }),
  setLifecycleSkip: (organizationId: string, profileId: string, forbidden: boolean) =>
    api.put<ProfileLifecycle>(`${profileUrl(organizationId, profileId)}/lifecycle/skip`, { forbidden }),
  stageWorkflow: (organizationId: string, profileId: string) =>
    api.get<ProfileStageWorkflow>(`${profileUrl(organizationId, profileId)}/stage-workflow`),
  setStageWorkflow: (organizationId: string, profileId: string, workflowId: string, mode: StageWorkflowMode) =>
    api.put<ProfileStageWorkflow>(`${profileUrl(organizationId, profileId)}/stage-workflow`, { workflow_id: workflowId, mode }),
  clearStageWorkflow: (organizationId: string, profileId: string) =>
    api.delete<ProfileStageWorkflow>(`${profileUrl(organizationId, profileId)}/stage-workflow`),

  approval: (organizationId: string, profileId: string) =>
    api.get<ProfileApproval>(`${profileUrl(organizationId, profileId)}/approval`),
  setApprovalRoles: (organizationId: string, profileId: string, artefactType: string, roles: ApproverRole[]) =>
    api.put<ProfileApproval>(`${profileUrl(organizationId, profileId)}/approval/${artefactType}`, { roles }),

  review: (organizationId: string, profileId: string) =>
    api.get<ProfileReview>(`${profileUrl(organizationId, profileId)}/review`),
  setReview: (organizationId: string, profileId: string, artefactType: string, settings: ReviewSettingsValues) =>
    api.put<ProfileReview>(`${profileUrl(organizationId, profileId)}/review/${artefactType}`, settings),

  baseline: (organizationId: string, profileId: string) =>
    api.get<ProfileBaseline>(`${profileUrl(organizationId, profileId)}/baseline`),
  setBaseline: (organizationId: string, profileId: string, settings: BaselineSettings) =>
    api.put<ProfileBaseline>(`${profileUrl(organizationId, profileId)}/baseline`, settings),
  baselineFields: (organizationId: string, profileId: string, projectId: string) =>
    api.get<BaselineFields>(`${profileUrl(organizationId, profileId)}/baseline/fields?project_id=${projectId}`),
};

/** The organisation's default way of keeping governance health. */
export const healthDefaultApi = {
  get: (organizationId: string) => api.get<HealthDefault>(`${orgBase(organizationId)}/health-defaults`),
  set: (organizationId: string, mode: HealthMode, intervalHours: number) =>
    api.put<HealthDefault>(`${orgBase(organizationId)}/health-defaults`, { mode, interval_hours: intervalHours }),
};

/** A project's profiles, choices, policy and governance health. */
export const projectGovernanceApi = {
  profiles: (projectId: string) => api.get<ProjectProfiles>(`${projectBase(projectId)}/profiles`),
  /** Opts out of a Default profile (`false`), in to an Opt-in profile (`true`) or clears the choice (`null`). */
  setChoice: (projectId: string, profileId: string, optedIn: boolean | null) =>
    api.put<ProjectProfiles>(`${projectBase(projectId)}/profiles/${profileId}/choice`, { opted_in: optedIn }),

  approval: (projectId: string) => api.get<ProjectApproval>(`${projectBase(projectId)}/approval-policies`),
  /** Sets the project's own roles for a type; `null` follows the nearest ancestor project. */
  setApprovalRoles: (projectId: string, artefactType: string, roles: ApproverRole[] | null) =>
    api.put<ProjectApproval>(`${projectBase(projectId)}/approval-policies/${artefactType}`, { roles }),

  review: (projectId: string) => api.get<ProjectReview>(`${projectBase(projectId)}/review-policies`),
  /** Sets the project's own review settings for a type; `null` follows the nearest ancestor project. */
  setReview: (projectId: string, artefactType: string, settings: ReviewSettingsValues | null) =>
    api.put<ProjectReview>(`${projectBase(projectId)}/review-policies/${artefactType}`, { settings }),

  baseline: (projectId: string) => api.get<ProjectBaseline>(`${projectBase(projectId)}/baseline-policy`),
  /** Sets the project's own baseline policy; `null` follows the nearest ancestor project. */
  setBaseline: (projectId: string, settings: BaselineSettings | null) =>
    api.put<ProjectBaseline>(`${projectBase(projectId)}/baseline-policy`, { settings }),
  previewBaseline: (projectId: string, kind: BaselineKind, stageId?: string) =>
    api.get<BaselinePreview>(
      `${projectBase(projectId)}/baseline-checks?kind=${kind}${stageId ? `&stage_id=${stageId}` : ""}`,
    ),

  health: (projectId: string) => api.get<Health>(`${projectBase(projectId)}/health`),
  refreshHealth: (projectId: string) => api.post<Health>(`${projectBase(projectId)}/health/refresh`),
  healthSettings: (projectId: string) => api.get<HealthSettings>(`${projectBase(projectId)}/health/settings`),
  setHealthSettings: (projectId: string, values: HealthSettingsValues) =>
    api.put<HealthSettings>(`${projectBase(projectId)}/health/settings`, values),
};
