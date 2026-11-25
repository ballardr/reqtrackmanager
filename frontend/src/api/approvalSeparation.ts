/**
 * Module: api/approvalSeparation
 *
 * Types and calls for approval separation: whether the person who created a record may approve it, per record type
 * (`/projects/{id}/approval-separation`, `/orgs/{id}/approval-separation`).
 *
 * {@link ApprovalSeparationApi} is injectable so stories stay off the network.
 */
import { api } from "./client";
import type { LifecycleExemption, LifecycleSource } from "./lifecycles";

/** One record type's rule as it applies to a project. */
export interface ProjectSeparation {
  artefact_type: string;
  label: string;
  module_key: string;
  module_name: string;
  /** The project's own choice; `null` follows the nearest ancestor project (else the default). */
  own: boolean | null;
  chosen: boolean;
  source: LifecycleSource;
  /** The organisation requires a separate approver and binds this project. */
  required: boolean;
  /** The organisation requires one but this project is exempt. */
  exempt: boolean;
  /** A person other than the creator must approve now. */
  separate: boolean;
}

/** A project's rules and whether the caller may change them. */
export interface ProjectSeparations {
  can_manage: boolean;
  has_parent: boolean;
  types: ProjectSeparation[];
}

/** One record type's organisation-level view. */
export interface OrgSeparation {
  artefact_type: string;
  label: string;
  module_key: string;
  module_name: string;
  required: boolean;
  exemptions: LifecycleExemption[];
}

/** What a record's page shows about approval separation. */
export interface ApprovalStatus {
  /** The record's latest approval was given by the person who created it. */
  self_approved: boolean;
  approved_by_name: string | null;
  approved_at: string | null;
  /** The caller created the record and a separate approver is required, so approval is unavailable to them. */
  needs_other_approver: boolean;
}

/** Where a record lives: a project, or the organisation that owns it. */
export type ApprovalScope = { projectId: string } | { organizationId: string };

/** The calls the approval separation surfaces make; injectable for stories. */
export interface ApprovalSeparationApi {
  project(projectId: string): Promise<ProjectSeparations>;
  /** Sets the project's own choice for one type (`null` follows the nearest ancestor project). */
  setProject(projectId: string, artefactType: string, separate: boolean | null): Promise<ProjectSeparations>;
  organization(organizationId: string): Promise<OrgSeparation[]>;
  setRequired(organizationId: string, artefactType: string, required: boolean): Promise<OrgSeparation[]>;
  addExemption(organizationId: string, artefactType: string, projectId: string, includeChildren: boolean): Promise<OrgSeparation[]>;
  removeExemption(organizationId: string, artefactType: string, projectId: string): Promise<OrgSeparation[]>;
  /** A record's self-approval mark and whether the caller must find another approver. */
  status(scope: ApprovalScope, artefactType: string, recordId: string): Promise<ApprovalStatus>;
}

/** The live implementation of {@link ApprovalSeparationApi}. */
export const approvalSeparationApi: ApprovalSeparationApi = {
  project: (projectId) => api.get<ProjectSeparations>(`/api/v1/projects/${projectId}/approval-separation`),
  setProject: (projectId, artefactType, separate) =>
    api.put<ProjectSeparations>(`/api/v1/projects/${projectId}/approval-separation/${artefactType}`, { separate_approver: separate }),
  organization: (organizationId) => api.get<OrgSeparation[]>(`/api/v1/orgs/${organizationId}/approval-separation`),
  setRequired: (organizationId, artefactType, required) =>
    api.put<OrgSeparation[]>(`/api/v1/orgs/${organizationId}/approval-separation/${artefactType}`, { required }),
  addExemption: (organizationId, artefactType, projectId, includeChildren) =>
    api.post<OrgSeparation[]>(`/api/v1/orgs/${organizationId}/approval-separation/${artefactType}/exemptions`, {
      project_id: projectId, include_children: includeChildren,
    }),
  removeExemption: (organizationId, artefactType, projectId) =>
    api.delete<OrgSeparation[]>(`/api/v1/orgs/${organizationId}/approval-separation/${artefactType}/exemptions/${projectId}`),
  status: (scope, artefactType, recordId) =>
    api.get<ApprovalStatus>(
      "projectId" in scope
        ? `/api/v1/projects/${scope.projectId}/approval-separation/status/${artefactType}/${recordId}`
        : `/api/v1/orgs/${scope.organizationId}/approval-separation/status/${artefactType}/${recordId}`,
    ),
};
