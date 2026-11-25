/**
 * Module: api/lifecycles
 *
 * Types and calls for lifecycle configuration: the optional states a project uses, the states an organisation
 * requires and the projects it exempts, and whether records may skip steps (`/projects/{id}/lifecycles`,
 * `/orgs/{id}/lifecycles`).
 *
 * {@link LifecyclesApi} is injectable so stories stay off the network.
 */
import { api } from "./client";
import type { Project } from "./types";

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
  /** The states that must stay on: the organisation's (unless it is exempt) and those the governance profiles require. */
  required: string[];
  exempt: boolean;
  /** `{state: names of the governance profiles requiring it}`, to name the source of a requirement. */
  required_by_profiles: Record<string, string[]>;
  source: LifecycleSource;
  /** Every state's legal next states with the turned-off states stepped over. */
  transitions: Record<string, string[]>;
  /** `{state: {target: [states passed over]}}`: the later steps a record may be moved to by skipping steps. Empty
   * unless the project allows skipping and the type supports it. */
  skip_transitions: Record<string, Record<string, string[]>>;
}

/** Whether records of a project may skip steps. */
export interface ProjectSkip {
  /** Skipping is possible now (the project's choice and not forbidden by the organisation). */
  allowed: boolean;
  /** The project's own choice; `null` follows the nearest ancestor project (else off). */
  own: boolean | null;
  chosen: boolean;
  source: LifecycleSource;
  /** Skipping is forbidden for this project, by the organisation or by a governance profile. */
  forbidden: boolean;
  /** The organisation forbids skipping but this project is exempt (and no profile forbids it). */
  exempt: boolean;
  /** Names of the governance profiles that forbid skipping for this project. */
  forbidden_by_profiles: string[];
}

/** A project's lifecycles and whether the caller may change them. */
export interface ProjectLifecycles {
  can_manage: boolean;
  has_parent: boolean;
  skip: ProjectSkip;
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

/** The organisation's rule on skipping steps. */
export interface OrgSkip {
  /** No project may skip steps, except the exempt ones. */
  forbidden: boolean;
  exemptions: LifecycleExemption[];
}

/** The calls the lifecycle surfaces make; injectable for stories. */
export interface LifecyclesApi {
  project(projectId: string): Promise<ProjectLifecycles>;
  /** Sets the project's own turned-off states for one type (`null` follows the nearest ancestor project). */
  setProject(projectId: string, artefactType: string, disabled: string[] | null): Promise<ProjectLifecycles>;
  /** Sets whether the project lets a record skip steps (`null` follows the nearest ancestor project, else off). */
  setProjectSkip(projectId: string, allowed: boolean | null): Promise<ProjectLifecycles>;
  organization(organizationId: string): Promise<OrgLifecycle[]>;
  organizationSkip(organizationId: string): Promise<OrgSkip>;
  setSkipForbidden(organizationId: string, forbidden: boolean): Promise<OrgSkip>;
  addSkipExemption(organizationId: string, projectId: string, includeChildren: boolean): Promise<OrgSkip>;
  removeSkipExemption(organizationId: string, projectId: string): Promise<OrgSkip>;
  setRequired(organizationId: string, artefactType: string, required: string[]): Promise<OrgLifecycle[]>;
  addExemption(organizationId: string, artefactType: string, projectId: string, includeChildren: boolean): Promise<OrgLifecycle[]>;
  removeExemption(organizationId: string, artefactType: string, projectId: string): Promise<OrgLifecycle[]>;
}

/** The live implementation of {@link LifecyclesApi}. */
export const lifecyclesApi: LifecyclesApi = {
  project: (projectId) => api.get<ProjectLifecycles>(`/api/v1/projects/${projectId}/lifecycles`),
  setProject: (projectId, artefactType, disabled) =>
    api.put<ProjectLifecycles>(`/api/v1/projects/${projectId}/lifecycles/${artefactType}`, { disabled_states: disabled }),
  setProjectSkip: (projectId, allowed) => api.put<ProjectLifecycles>(`/api/v1/projects/${projectId}/lifecycles/skip`, { allowed }),
  organization: (organizationId) => api.get<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles`),
  organizationSkip: (organizationId) => api.get<OrgSkip>(`/api/v1/orgs/${organizationId}/lifecycles/skip`),
  setSkipForbidden: (organizationId, forbidden) => api.put<OrgSkip>(`/api/v1/orgs/${organizationId}/lifecycles/skip`, { forbidden }),
  addSkipExemption: (organizationId, projectId, includeChildren) =>
    api.post<OrgSkip>(`/api/v1/orgs/${organizationId}/lifecycles/skip/exemptions`, { project_id: projectId, include_children: includeChildren }),
  removeSkipExemption: (organizationId, projectId) =>
    api.delete<OrgSkip>(`/api/v1/orgs/${organizationId}/lifecycles/skip/exemptions/${projectId}`),
  setRequired: (organizationId, artefactType, required) =>
    api.put<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}`, { required_states: required }),
  addExemption: (organizationId, artefactType, projectId, includeChildren) =>
    api.post<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}/exemptions`, {
      project_id: projectId, include_children: includeChildren,
    }),
  removeExemption: (organizationId, artefactType, projectId) =>
    api.delete<OrgLifecycle[]>(`/api/v1/orgs/${organizationId}/lifecycles/${artefactType}/exemptions/${projectId}`),
};

/** Loads the organisation's projects for an exemption dialog. */
export type LoadOrgProjects = (organizationId: string) => Promise<Array<Pick<Project, "id" | "name" | "code">>>;

/** The live {@link LoadOrgProjects}. */
export const loadOrgProjects: LoadOrgProjects = (organizationId) =>
  api.get<Project[]>(`/api/v1/projects?organization_id=${organizationId}`);
