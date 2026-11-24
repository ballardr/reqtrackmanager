/**
 * Module: api/lifecycles
 *
 * Types and calls for lifecycle configuration: the optional states a project uses, the states an organisation
 * requires and the projects it exempts (`/projects/{id}/lifecycles`, `/orgs/{id}/lifecycles`).
 *
 * {@link LifecyclesApi} is injectable so stories stay off the network.
 */
import { api } from "./client";

/** One state of a record type's path. */
export interface LifecycleState {
  key: string;
  label: string;
  /** A project may turn it off. */
  optional: boolean;
  /** Moving into it needs a permission or a second person's decision. */
  gated: boolean;
}

/** Where a project's choice comes from. */
export type LifecycleSource = "project" | "parent_project" | "default";

/** One record type's lifecycle as it applies to a project. */
export interface ProjectLifecycle {
  artefact_type: string;
  label: string;
  module_key: string;
  module_name: string;
  path: LifecycleState[];
  off_path: LifecycleState[];
  /** The project's own turned-off states; `null` follows the nearest ancestor project (else every state on). */
  own_disabled: string[] | null;
  /** The states that are off here. */
  disabled: string[];
  /** The states the organisation requires and that bind this project. */
  required: string[];
  exempt: boolean;
  source: LifecycleSource;
  /** Every state's legal next states with the turned-off states stepped over. */
  transitions: Record<string, string[]>;
}

/** A project's lifecycles and whether the caller may change them. */
export interface ProjectLifecycles {
  can_manage: boolean;
  has_parent: boolean;
  lifecycles: ProjectLifecycle[];
}

/** A project the organisation's requirement does not bind. */
export interface LifecycleExemption {
  project_id: string;
  project_name: string;
  project_code: string;
  include_children: boolean;
}

/** One record type's organisation-level view. */
export interface OrgLifecycle {
  artefact_type: string;
  label: string;
  module_key: string;
  module_name: string;
  /** The optional states the organisation may require. */
  states: LifecycleState[];
  required: string[];
  exemptions: LifecycleExemption[];
}

/** The calls the lifecycle surfaces make; injectable for stories. */
export interface LifecyclesApi {
  project(projectId: string): Promise<ProjectLifecycles>;
  /** Sets the project's own turned-off states for one type (`null` follows the nearest ancestor project). */
  setProject(projectId: string, artefactType: string, disabled: string[] | null): Promise<ProjectLifecycles>;
  organization(organizationId: string): Promise<OrgLifecycle[]>;
  setRequired(organizationId: string, artefactType: string, required: string[]): Promise<OrgLifecycle[]>;
  addExemption(organizationId: string, artefactType: string, projectId: string, includeChildren: boolean): Promise<OrgLifecycle[]>;
  removeExemption(organizationId: string, artefactType: string, projectId: string): Promise<OrgLifecycle[]>;
}

/** The live implementation of {@link LifecyclesApi}. */
export const lifecyclesApi: LifecyclesApi = {
  project: (projectId) => api.get<ProjectLifecycles>(`/api/v1/projects/${projectId}/lifecycles`),
  setProject: (projectId, artefactType, disabled) =>
    api.put<ProjectLifecycles>(`/api/v1/projects/${projectId}/lifecycles/${artefactType}`, { disabled_states: disabled }),
  organization: (organizationId) => api.get<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles`),
  setRequired: (organizationId, artefactType, required) =>
    api.put<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}`, { required_states: required }),
  addExemption: (organizationId, artefactType, projectId, includeChildren) =>
    api.post<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}/exemptions`, {
      project_id: projectId, include_children: includeChildren,
    }),
  removeExemption: (organizationId, artefactType, projectId) =>
    api.delete<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}/exemptions/${projectId}`),
};
