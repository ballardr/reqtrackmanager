/**
 * Module: modules/stakeholders/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for every endpoint
 * `backend/app/modules/stakeholders/` exposes, for the three artefacts (Persona,
 * Stakeholder, Need). They share a shape — CRUD, versions, archive, lifecycle,
 * comments, files — so `buildRecordApi` builds it once from a base URL and a
 * path segment; `buildTypeApi`/`buildProjectTypeCalls` do the same for the
 * two-tier type vocabulary. Each artefact then adds only what is its own
 * (Persona's weight override; Stakeholder's cadence hint, create-from-user,
 * erasure and "represents" links). `id` parameters are a `project_id` or
 * `organization_id` to match the scope.
 */
import { api } from "../../api/client";
import type { FileAsset } from "../../api/types";
import type {
  CadenceHint,
  EffectivePersonaType,
  HeldNeed,
  IncomingRelationship,
  Need,
  NeedComment,
  NeedFieldValues,
  NeedHolder,
  NeedHolderKind,
  NeedRequirement,
  NeedVersion,
  Persona,
  PersonaComment,
  PersonaFieldValues,
  PersonaTypeDefinition,
  PersonaVersion,
  Relationship,
  RelationshipHolderKind,
  RelationshipKind,
  RelationshipTarget,
  RepresentedLink,
  Stakeholder,
  StakeholderComment,
  StakeholderFieldValues,
  StakeholderVersion,
  TargetCadence,
} from "./types";

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/stakeholders`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/stakeholders`;

/** Every list endpoint's optional filters. */
export interface RecordListFilters {
  include_archived?: boolean;
  /** Project Stakeholder list only: also list org Stakeholders hidden from the project. */
  include_hidden?: boolean;
}

/** Create payload: the editable fields plus the people pickers' values. */
export type PersonaCreateValues = Omit<PersonaFieldValues, "change_note"> & {
  owner_id?: string | null;
  champion_id?: string | null;
};

/** Partial update payload — only keys present are changed; `null` clears a nullable field. */
export type PersonaUpdateValues = Partial<PersonaFieldValues> & { owner_id?: string | null; champion_id?: string | null };

export type StakeholderCreateValues = Omit<StakeholderFieldValues, "change_note"> & {
  owner_id?: string | null;
  user_id?: string | null;
};

export type StakeholderUpdateValues = Partial<StakeholderFieldValues> & {
  owner_id?: string | null;
  user_id?: string | null;
};

export type NeedCreateValues = Omit<NeedFieldValues, "change_note"> & { owner_id?: string | null };

export type NeedUpdateValues = Partial<NeedFieldValues> & { owner_id?: string | null };

/** The calls every record kind in this module has; what the shared detail
 * components (`RecordDiscussion`, `RecordLifecycleControls`) are written
 * against. */
export interface RecordApi<Rec, Version, Comment, Create, Update> {
  list(id: string, filters?: RecordListFilters): Promise<Rec[]>;
  create(id: string, values: Create): Promise<Rec>;
  get(id: string, recordId: string): Promise<Rec>;
  update(id: string, recordId: string, values: Update): Promise<Rec>;
  listVersions(id: string, recordId: string): Promise<Version[]>;
  archive(id: string, recordId: string): Promise<Rec>;
  unarchive(id: string, recordId: string): Promise<Rec>;
  activate(id: string, recordId: string, comment?: string): Promise<Rec>;
  retire(id: string, recordId: string, comment?: string): Promise<Rec>;
  listComments(id: string, recordId: string): Promise<Comment[]>;
  addComment(id: string, recordId: string, body: string): Promise<Comment>;
  editComment(id: string, recordId: string, commentId: string, body: string): Promise<Comment>;
  uploadCommentAttachment(id: string, recordId: string, commentId: string, file: File): Promise<FileAsset>;
  removeCommentAttachment(id: string, recordId: string, commentId: string, fileId: string): Promise<void>;
  listFiles(id: string, recordId: string): Promise<FileAsset[]>;
  uploadFile(id: string, recordId: string, file: File): Promise<FileAsset>;
  unlinkFile(id: string, recordId: string, fileId: string): Promise<void>;
}

/** Builds the shared record endpoints for `segment` ("personas" / "stakeholders") under `base`. */
function buildRecordApi<Rec, Version, Comment, Create, Update>(
  base: (id: string) => string,
  segment: string,
): RecordApi<Rec, Version, Comment, Create, Update> {
  const url = (id: string, recordId?: string) => `${base(id)}/${segment}${recordId ? `/${recordId}` : ""}`;
  return {
    list: (id, filters = {}) => {
      const params = new URLSearchParams();
      if (filters.include_archived) params.set("include_archived", "true");
      if (filters.include_hidden) params.set("include_hidden", "true");
      const query = params.toString();
      return api.get<Rec[]>(`${url(id)}${query ? `?${query}` : ""}`);
    },
    create: (id, values) => api.post<Rec>(url(id), values),
    get: (id, recordId) => api.get<Rec>(url(id, recordId)),
    update: (id, recordId, values) => api.put<Rec>(url(id, recordId), values),
    listVersions: (id, recordId) => api.get<Version[]>(`${url(id, recordId)}/versions`),
    archive: (id, recordId) => api.post<Rec>(`${url(id, recordId)}/archive`),
    unarchive: (id, recordId) => api.post<Rec>(`${url(id, recordId)}/unarchive`),
    activate: (id, recordId, comment) => api.post<Rec>(`${url(id, recordId)}/activate`, { comment: comment || null }),
    retire: (id, recordId, comment) => api.post<Rec>(`${url(id, recordId)}/retire`, { comment: comment || null }),
    listComments: (id, recordId) => api.get<Comment[]>(`${url(id, recordId)}/comments`),
    addComment: (id, recordId, body) => api.post<Comment>(`${url(id, recordId)}/comments`, { body }),
    editComment: (id, recordId, commentId, body) =>
      api.patch<Comment>(`${url(id, recordId)}/comments/${commentId}`, { body }),
    uploadCommentAttachment: (id, recordId, commentId, file) =>
      api.postFile<FileAsset>(`${url(id, recordId)}/comments/${commentId}/files`, file),
    removeCommentAttachment: (id, recordId, commentId, fileId) =>
      api.delete<void>(`${url(id, recordId)}/comments/${commentId}/files/${fileId}`),
    listFiles: (id, recordId) => api.get<FileAsset[]>(`${url(id, recordId)}/files`),
    uploadFile: (id, recordId, file) => api.postFile<FileAsset>(`${url(id, recordId)}/files`, file),
    unlinkFile: (id, recordId, fileId) => api.delete<void>(`${url(id, recordId)}/files/${fileId}`),
  };
}

/** A type-vocabulary row as the org list returns it (`PersonaTypeDefinition` /
 * `StakeholderTypeDefinition` have the same shape). */
type OrgType = PersonaTypeDefinition;

/** Org-scoped type CRUD for `segment` ("persona-types" / "stakeholder-types"). */
function buildOrgTypeApi(segment: string) {
  const url = (organizationId: string, typeId?: string) => `${orgBase(organizationId)}/${segment}${typeId ? `/${typeId}` : ""}`;
  return {
    list: (organizationId: string) => api.get<OrgType[]>(url(organizationId)),
    create: (organizationId: string, name: string) => api.post<OrgType>(url(organizationId), { name }),
    move: (organizationId: string, typeId: string, direction: "up" | "down") =>
      api.post<OrgType>(`${url(organizationId, typeId)}/move`, { direction }),
    update: (organizationId: string, typeId: string, values: { name?: string; is_active?: boolean }) =>
      api.patch<OrgType>(url(organizationId, typeId), values),
    delete: (organizationId: string, typeId: string) => api.delete<void>(url(organizationId, typeId)),
  };
}

/** Project-tier type calls for `segment`. */
function buildProjectTypeCalls(segment: string) {
  const url = (projectId: string, typeId?: string) => `${projectBase(projectId)}/${segment}${typeId ? `/${typeId}` : ""}`;
  return {
    listTypes: (projectId: string) => api.get<EffectivePersonaType[]>(url(projectId)),
    createLocalType: (projectId: string, name: string, displayOrder?: number) =>
      api.post<unknown>(url(projectId), { name, display_order: displayOrder ?? null }),
    overrideType: (
      projectId: string, typeRefId: string,
      values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
    ) => api.put<unknown>(url(projectId, typeRefId), values),
    deleteType: (projectId: string, projectTypeId: string) => api.delete<void>(url(projectId, projectTypeId)),
  };
}

type PersonaApi = RecordApi<Persona, PersonaVersion, PersonaComment, PersonaCreateValues, PersonaUpdateValues>;
type StakeholderApi = RecordApi<Stakeholder, StakeholderVersion, StakeholderComment, StakeholderCreateValues, StakeholderUpdateValues>;

/** Persona calls both scopes share, plus the persona-side "represented by" list. */
function buildPersonaApi(base: (id: string) => string): PersonaApi & { listStakeholders(id: string, personaId: string): Promise<RepresentedLink[]> } {
  return {
    ...buildRecordApi<Persona, PersonaVersion, PersonaComment, PersonaCreateValues, PersonaUpdateValues>(base, "personas"),
    listStakeholders: (id, personaId) => api.get<RepresentedLink[]>(`${base(id)}/personas/${personaId}/stakeholders`),
  };
}

/** Stakeholder calls both scopes share. */
function buildStakeholderApi(base: (id: string) => string) {
  const url = (id: string, stakeholderId: string) => `${base(id)}/stakeholders/${stakeholderId}`;
  return {
    ...buildRecordApi<Stakeholder, StakeholderVersion, StakeholderComment, StakeholderCreateValues, StakeholderUpdateValues>(
      base, "stakeholders",
    ),
    createFromUser: (
      id: string,
      values: { user_id: string; stakeholder_type_id?: string | null; role?: string; organisation_group?: string; target_cadence?: TargetCadence | null },
    ) => api.post<Stakeholder>(`${base(id)}/stakeholders/from-user`, values),
    /** Permanently deletes the stakeholder and everything held about them. */
    erase: (id: string, stakeholderId: string) => api.delete<void>(url(id, stakeholderId)),
    cadenceHint: (id: string, influenceLevelId: string | null, interestLevelId: string | null) => {
      const params = new URLSearchParams();
      if (influenceLevelId) params.set("influence_level_id", influenceLevelId);
      if (interestLevelId) params.set("interest_level_id", interestLevelId);
      return api.get<CadenceHint>(`${base(id)}/stakeholders/cadence-hint?${params.toString()}`);
    },
    listPersonas: (id: string, stakeholderId: string) => api.get<RepresentedLink[]>(`${url(id, stakeholderId)}/personas`),
    addPersona: (id: string, stakeholderId: string, personaId: string) =>
      api.post<RepresentedLink>(`${url(id, stakeholderId)}/personas`, { persona_id: personaId }),
    removePersona: (id: string, stakeholderId: string, personaId: string) =>
      api.delete<void>(`${url(id, stakeholderId)}/personas/${personaId}`),
  };
}

/** Org-scoped Persona endpoints — `id` is an `organization_id`. */
export const orgPersonaApi = buildPersonaApi(orgBase);

/** Project-scoped Persona endpoints (reads include the organisation's
 * personas, minus those hidden from the project) plus the weight and visibility
 * overrides and the project type tier — `id` is a
 * `project_id`. */
export const projectPersonaApi = {
  ...buildPersonaApi(projectBase),
  setWeightOverride(projectId: string, personaId: string, weight: number) {
    return api.put<Persona>(`${projectBase(projectId)}/personas/${personaId}/weight`, { weight });
  },
  clearWeightOverride(projectId: string, personaId: string) {
    return api.delete<Persona>(`${projectBase(projectId)}/personas/${personaId}/weight`);
  },
  /** Hides an org persona from the project (`hidden: true`) or re-shows one a parent project hides. */
  setVisibility: (projectId: string, personaId: string, hidden: boolean) =>
    api.put<Persona>(`${projectBase(projectId)}/personas/${personaId}/visibility`, { hidden }),
  /** Removes the project's own override, reverting to the inherited (else visible) state. */
  clearVisibility: (projectId: string, personaId: string) =>
    api.delete<Persona>(`${projectBase(projectId)}/personas/${personaId}/visibility`),
  ...buildProjectTypeCalls("persona-types"),
};

/** Org-scoped `PersonaTypeDefinition` CRUD — `id` parameters are an `organization_id`. */
export const orgPersonaTypeApi = buildOrgTypeApi("persona-types");

/** Org-scoped Stakeholder endpoints — `id` is an `organization_id`. */
export const orgStakeholderApi = buildStakeholderApi(orgBase);

/** Project-scoped Stakeholder endpoints (reads include the organisation's
 * stakeholders, minus those hidden from the project), the visibility override
 * and the project type tier — `id` is a `project_id`. */
export const projectStakeholderApi = {
  ...buildStakeholderApi(projectBase),
  /** Hides an org stakeholder from the project (`hidden: true`) or re-shows one a parent project hides. */
  setVisibility: (projectId: string, stakeholderId: string, hidden: boolean) =>
    api.put<Stakeholder>(`${projectBase(projectId)}/stakeholders/${stakeholderId}/visibility`, { hidden }),
  /** Removes the project's own override, reverting to the inherited (else visible) state. */
  clearVisibility: (projectId: string, stakeholderId: string) =>
    api.delete<Stakeholder>(`${projectBase(projectId)}/stakeholders/${stakeholderId}/visibility`),
  ...buildProjectTypeCalls("stakeholder-types"),
};

/** Org-scoped Stakeholder type CRUD — `id` parameters are an `organization_id`. */
export const orgStakeholderTypeApi = buildOrgTypeApi("stakeholder-types");

type NeedApi = RecordApi<Need, NeedVersion, NeedComment, NeedCreateValues, NeedUpdateValues>;

/** Project-scoped Stakeholder Need endpoints (`id` is a `project_id`), with the
 * "has need" holders, the "gives rise to" Requirements, and the needs of a
 * Stakeholder or Persona. A need has no org scope, so there is no org API. */
export const projectNeedApi = {
  ...buildRecordApi<Need, NeedVersion, NeedComment, NeedCreateValues, NeedUpdateValues>(projectBase, "needs"),
  listHolders: (projectId: string, needId: string) => api.get<NeedHolder[]>(`${projectBase(projectId)}/needs/${needId}/holders`),
  addHolder: (projectId: string, needId: string, kind: NeedHolderKind, id: string) =>
    api.post<NeedHolder>(`${projectBase(projectId)}/needs/${needId}/holders`, { kind, id }),
  removeHolder: (projectId: string, needId: string, kind: NeedHolderKind, id: string) =>
    api.delete<void>(`${projectBase(projectId)}/needs/${needId}/holders/${kind}/${id}`),
  listRequirements: (projectId: string, needId: string) =>
    api.get<NeedRequirement[]>(`${projectBase(projectId)}/needs/${needId}/requirements`),
  addRequirement: (projectId: string, needId: string, requirementId: string) =>
    api.post<NeedRequirement>(`${projectBase(projectId)}/needs/${needId}/requirements`, { requirement_id: requirementId }),
  removeRequirement: (projectId: string, needId: string, requirementId: string) =>
    api.delete<void>(`${projectBase(projectId)}/needs/${needId}/requirements/${requirementId}`),
  listStakeholderNeeds: (projectId: string, stakeholderId: string) =>
    api.get<HeldNeed[]>(`${projectBase(projectId)}/stakeholders/${stakeholderId}/needs`),
  listPersonaNeeds: (projectId: string, personaId: string) =>
    api.get<HeldNeed[]>(`${projectBase(projectId)}/personas/${personaId}/needs`),
};

/** Project-scoped §10.5 relationships a Stakeholder or Persona has with Pain
 * Points, Requirements and Decisions (`id` is a `project_id`). A holder's links
 * are always listed per project, so a shared org record shows only this project's. */
export const projectRelationshipApi = {
  kinds: (projectId: string) => api.get<RelationshipKind[]>(`${projectBase(projectId)}/relationship-kinds`),
  targets: (projectId: string, targetType: string) =>
    api.get<RelationshipTarget[]>(`${projectBase(projectId)}/relationship-targets?target_type=${encodeURIComponent(targetType)}`),
  list: (projectId: string, holder: RelationshipHolderKind, holderId: string) =>
    api.get<Relationship[]>(`${projectBase(projectId)}/${holder}s/${holderId}/relationships`),
  add: (projectId: string, holder: RelationshipHolderKind, holderId: string, kind: string, targetType: string, targetId: string) =>
    api.post<Relationship>(`${projectBase(projectId)}/${holder}s/${holderId}/relationships`, {
      kind,
      target_type: targetType,
      target_id: targetId,
    }),
  remove: (projectId: string, holder: RelationshipHolderKind, holderId: string, linkId: string) =>
    api.delete<void>(`${projectBase(projectId)}/${holder}s/${holderId}/relationships/${linkId}`),
  incoming: (projectId: string, targetType: string, targetId: string) =>
    api.get<IncomingRelationship[]>(
      `${projectBase(projectId)}/relationships/incoming?target_type=${encodeURIComponent(targetType)}&target_id=${targetId}`,
    ),
};

/** The shape the artefacts' APIs share, for components written against any. */
export type { NeedApi, PersonaApi, StakeholderApi };
