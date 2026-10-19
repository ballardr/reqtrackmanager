/**
 * Module: modules/stakeholders/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for every endpoint
 * `backend/app/modules/stakeholders/` exposes. The three lifecycle artefacts (Persona,
 * Stakeholder, Need) share a shape — CRUD, versions, archive, lifecycle,
 * comments, files — so `buildRecordApi` builds it once from a base URL and a
 * path segment; `buildTypeApi`/`buildProjectTypeCalls` do the same for the
 * two-tier type vocabulary. Each artefact then adds only what is its own
 * (Persona's weight override; Stakeholder's cadence hint, create-from-user,
 * erasure and "represents" links). Engagements are a different shape (no
 * lifecycle or versions; hard delete) and, with their research extras, have
 * their own `projectEngagementApi` / `projectResearchApi`. `id` parameters are a `project_id` or
 * `organization_id` to match the scope.
 */
import { api } from "../../api/client";
import type { FileAsset, PrincipalRef } from "../../api/types";
import type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import type {
  AnonymousParticipant,
  CadenceHint,
  Engagement,
  EngagementAudience,
  EngagementAudienceAdded,
  EngagementChannel,
  EngagementComment,
  EngagementFieldValues,
  EngagementOutcome,
  EngagementParticipant,
  EngagementPersona,
  EngagementPrompt,
  OutcomeKind,
  OutcomeTarget,
  OutcomeTargetType,
  ResearchFinding,
  StakeholderEngagement,
  EffectivePersonaType,
  GroupFromTextResult,
  GroupTextProposal,
  HeldNeed,
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
  RepresentedLink,
  Stakeholder,
  StakeholderComment,
  StakeholderFieldValues,
  StakeholderGroup,
  StakeholderGroupFieldValues,
  StakeholderGroupMember,
  StakeholderGroupRef,
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
  owner?: PrincipalRef | null;
  champion?: PrincipalRef | null;
};

/** Partial update payload — only keys present are changed; `null` clears a nullable field. */
export type PersonaUpdateValues = Partial<PersonaFieldValues> & { owner?: PrincipalRef | null; champion?: PrincipalRef | null };

export type StakeholderCreateValues = Omit<StakeholderFieldValues, "change_note"> & {
  owner?: PrincipalRef | null;
  user_id?: string | null;
};

export type StakeholderUpdateValues = Partial<StakeholderFieldValues> & {
  owner?: PrincipalRef | null;
  user_id?: string | null;
};

export type NeedCreateValues = Omit<NeedFieldValues, "change_note"> & { owner?: PrincipalRef | null };

export type NeedUpdateValues = Partial<NeedFieldValues> & { owner?: PrincipalRef | null };

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
    deleteType: (projectId: string, typeRefId: string) => api.delete<void>(url(projectId, typeRefId)),
    listHiddenTypes: (projectId: string) => api.get<HiddenDefinition[]>(`${url(projectId)}/hidden`),
    restoreTypes: (projectId: string, orgTypeIds?: string[]) =>
      api.post<unknown>(`${url(projectId)}/restore`, { org_type_ids: orgTypeIds ?? null }),
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

/** Stakeholder group calls both scopes share (`base(id)` is the org or project module URL). */
function buildGroupApi(base: (id: string) => string) {
  const url = (id: string, groupId?: string) => `${base(id)}/stakeholder-groups${groupId ? `/${groupId}` : ""}`;
  return {
    /** Every group this scope can see, flat (the project's include the organisation's). */
    list: (id: string) => api.get<StakeholderGroup[]>(url(id)),
    create: (id: string, values: StakeholderGroupFieldValues) => api.post<StakeholderGroup>(url(id), values),
    update: (id: string, groupId: string, values: Partial<StakeholderGroupFieldValues>) =>
      api.patch<StakeholderGroup>(url(id, groupId), values),
    move: (id: string, groupId: string, direction: "up" | "down") =>
      api.post<StakeholderGroup>(`${url(id, groupId)}/move`, { direction }),
    /** Deletes the group: its memberships go (never the stakeholders) and its children move up. */
    delete: (id: string, groupId: string) => api.delete<void>(url(id, groupId)),
    listMembers: (id: string, groupId: string, directOnly = false) =>
      api.get<StakeholderGroupMember[]>(`${url(id, groupId)}/members${directOnly ? "?direct_only=true" : ""}`),
    addMember: (id: string, groupId: string, stakeholderId: string) =>
      api.post<void>(`${url(id, groupId)}/members`, { stakeholder_id: stakeholderId }),
    removeMember: (id: string, groupId: string, stakeholderId: string) =>
      api.delete<void>(`${url(id, groupId)}/members/${stakeholderId}`),
    /** Sets the stakeholder's groups of this scope's tier to exactly `groupIds`. */
    setStakeholderGroups: (id: string, stakeholderId: string, groupIds: string[]) =>
      api.put<StakeholderGroupRef[]>(`${base(id)}/stakeholders/${stakeholderId}/groups`, { group_ids: groupIds }),
    textProposals: (id: string) => api.get<GroupTextProposal[]>(`${url(id)}/text-proposals`),
    createFromText: (id: string, names: string[]) => api.post<GroupFromTextResult>(`${url(id)}/from-text`, { names }),
  };
}

/** Org-scoped Stakeholder group endpoints — `id` is an `organization_id`. */
export const orgStakeholderGroupApi = buildGroupApi(orgBase);

/** Project-scoped Stakeholder group endpoints (the list includes the organisation's groups, which
 * are read-only here) — `id` is a `project_id`. */
export const projectStakeholderGroupApi = buildGroupApi(projectBase);

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

/** The shape the artefacts' APIs share, for components written against any. */
export type { NeedApi, PersonaApi, StakeholderApi };

/** Create payload: the content plus the optional shortcuts that add people in the same request. */
export type EngagementCreateValues = EngagementFieldValues & {
  facilitators?: PrincipalRef[];
  stakeholder_ids?: string[];
  persona_ids?: string[];
  group_ids?: string[];
};

/** Partial update payload — only keys present are changed; `null` clears `retain_until`, and a `facilitators`
 * list replaces everyone who ran it. */
export type EngagementUpdateValues = Partial<EngagementFieldValues> & { facilitators?: PrincipalRef[] };

/** The list endpoint's optional filters; they combine. */
export interface EngagementListFilters {
  channel?: EngagementChannel;
  stakeholder_id?: string;
  persona_id?: string;
  date_from?: string;
  date_to?: string;
  retention_due?: boolean;
}

/** Outcome calls an engagement and a research finding share (`segment` is "engagements" or "findings"). */
function buildOutcomeCalls(segment: "engagements" | "findings") {
  const url = (projectId: string, holderId: string) => `${projectBase(projectId)}/${segment}/${holderId}/outcomes`;
  return {
    list: (projectId: string, holderId: string) => api.get<EngagementOutcome[]>(url(projectId, holderId)),
    add: (projectId: string, holderId: string, kind: OutcomeKind, targetType: OutcomeTargetType, targetId: string) =>
      api.post<EngagementOutcome>(url(projectId, holderId), { kind, target_type: targetType, target_id: targetId }),
    remove: (projectId: string, holderId: string, linkId: string) => api.delete<void>(`${url(projectId, holderId)}/${linkId}`),
  };
}

/** The outcome calls of an engagement or a finding. */
export type OutcomeApi = ReturnType<typeof buildOutcomeCalls>;

/** Project-scoped Engagement endpoints (`id` is a `project_id`). An Engagement has no lifecycle, versions
 * or archive: it is edited in place and permanently deleted (`erase`). */
export const projectEngagementApi = {
  list: (projectId: string, filters: EngagementListFilters = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    const query = params.toString();
    return api.get<Engagement[]>(`${projectBase(projectId)}/engagements${query ? `?${query}` : ""}`);
  },
  create: (projectId: string, values: EngagementCreateValues) => api.post<Engagement>(`${projectBase(projectId)}/engagements`, values),
  get: (projectId: string, engagementId: string) => api.get<Engagement>(`${projectBase(projectId)}/engagements/${engagementId}`),
  update: (projectId: string, engagementId: string, values: EngagementUpdateValues) =>
    api.put<Engagement>(`${projectBase(projectId)}/engagements/${engagementId}`, values),
  /** Permanently deletes the engagement, its notes, participant data, findings, comments and files. */
  erase: (projectId: string, engagementId: string) => api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}`),
  /** A Stakeholder's engagement timeline, most recent first. */
  listForStakeholder: (projectId: string, stakeholderId: string) =>
    api.get<StakeholderEngagement[]>(`${projectBase(projectId)}/stakeholders/${stakeholderId}/engagements`),

  listParticipants: (projectId: string, engagementId: string) =>
    api.get<EngagementParticipant[]>(`${projectBase(projectId)}/engagements/${engagementId}/participants`),
  addParticipant: (projectId: string, engagementId: string, stakeholderId: string) =>
    api.post<EngagementParticipant>(`${projectBase(projectId)}/engagements/${engagementId}/participants`, { stakeholder_id: stakeholderId }),
  removeParticipant: (projectId: string, engagementId: string, stakeholderId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/participants/${stakeholderId}`),

  listPersonas: (projectId: string, engagementId: string) =>
    api.get<EngagementPersona[]>(`${projectBase(projectId)}/engagements/${engagementId}/personas`),
  addPersona: (projectId: string, engagementId: string, personaId: string) =>
    api.post<EngagementPersona>(`${projectBase(projectId)}/engagements/${engagementId}/personas`, { persona_id: personaId }),
  removePersona: (projectId: string, engagementId: string, personaId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/personas/${personaId}`),

  listAudiences: (projectId: string, engagementId: string) =>
    api.get<EngagementAudience[]>(`${projectBase(projectId)}/engagements/${engagementId}/audiences`),
  /** Aims the engagement at a group and copies its current members in as participants (a snapshot). */
  addAudience: (projectId: string, engagementId: string, groupId: string) =>
    api.post<EngagementAudienceAdded>(`${projectBase(projectId)}/engagements/${engagementId}/audiences`, { group_id: groupId }),
  /** Removes the audience link only; the participants it added stay. */
  removeAudience: (projectId: string, engagementId: string, groupId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/audiences/${groupId}`),

  outcomes: buildOutcomeCalls("engagements"),
  /** The project's Pain Points / Needs / Open Questions an outcome can point at. */
  listOutcomeTargets: (projectId: string, targetType: OutcomeTargetType) =>
    api.get<OutcomeTarget[]>(`${projectBase(projectId)}/engagement-outcome-targets?target_type=${targetType}`),

  // The calls `RecordDiscussion` makes (comments and direct attachments).
  listComments: (projectId: string, engagementId: string) =>
    api.get<EngagementComment[]>(`${projectBase(projectId)}/engagements/${engagementId}/comments`),
  addComment: (projectId: string, engagementId: string, body: string) =>
    api.post<EngagementComment>(`${projectBase(projectId)}/engagements/${engagementId}/comments`, { body }),
  editComment: (projectId: string, engagementId: string, commentId: string, body: string) =>
    api.patch<EngagementComment>(`${projectBase(projectId)}/engagements/${engagementId}/comments/${commentId}`, { body }),
  uploadCommentAttachment: (projectId: string, engagementId: string, commentId: string, file: File) =>
    api.postFile<FileAsset>(`${projectBase(projectId)}/engagements/${engagementId}/comments/${commentId}/files`, file),
  removeCommentAttachment: (projectId: string, engagementId: string, commentId: string, fileId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/comments/${commentId}/files/${fileId}`),
  listFiles: (projectId: string, engagementId: string) =>
    api.get<FileAsset[]>(`${projectBase(projectId)}/engagements/${engagementId}/files`),
  uploadFile: (projectId: string, engagementId: string, file: File) =>
    api.postFile<FileAsset>(`${projectBase(projectId)}/engagements/${engagementId}/files`, file),
  unlinkFile: (projectId: string, engagementId: string, fileId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/files/${fileId}`),
};

/** Research-extras endpoints (the `research_extras` sub-component): session prompts, anonymous participants
 * and findings of an engagement. They 404 while the sub-component is off. `id` is a `project_id`. */
export const projectResearchApi = {
  listPrompts: (projectId: string, engagementId: string) =>
    api.get<EngagementPrompt[]>(`${projectBase(projectId)}/engagements/${engagementId}/prompts`),
  addPrompt: (projectId: string, engagementId: string, values: { prompt: string; response_notes?: string }) =>
    api.post<EngagementPrompt>(`${projectBase(projectId)}/engagements/${engagementId}/prompts`, values),
  updatePrompt: (projectId: string, engagementId: string, promptId: string, values: { prompt?: string; response_notes?: string }) =>
    api.patch<EngagementPrompt>(`${projectBase(projectId)}/engagements/${engagementId}/prompts/${promptId}`, values),
  /** Moves a prompt one place; resolves to the reordered list. */
  movePrompt: (projectId: string, engagementId: string, promptId: string, direction: "up" | "down") =>
    api.post<EngagementPrompt[]>(`${projectBase(projectId)}/engagements/${engagementId}/prompts/${promptId}/move`, { direction }),
  deletePrompt: (projectId: string, engagementId: string, promptId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/prompts/${promptId}`),

  listAnonymousParticipants: (projectId: string, engagementId: string) =>
    api.get<AnonymousParticipant[]>(`${projectBase(projectId)}/engagements/${engagementId}/anonymous-participants`),
  addAnonymousParticipant: (projectId: string, engagementId: string, values: { label: string; persona_id?: string | null }) =>
    api.post<AnonymousParticipant>(`${projectBase(projectId)}/engagements/${engagementId}/anonymous-participants`, values),
  deleteAnonymousParticipant: (projectId: string, engagementId: string, participantId: string) =>
    api.delete<void>(`${projectBase(projectId)}/engagements/${engagementId}/anonymous-participants/${participantId}`),

  /** Every finding of the project, across engagements. */
  listProjectFindings: (projectId: string) => api.get<ResearchFinding[]>(`${projectBase(projectId)}/findings`),
  listFindings: (projectId: string, engagementId: string) =>
    api.get<ResearchFinding[]>(`${projectBase(projectId)}/engagements/${engagementId}/findings`),
  getFinding: (projectId: string, findingId: string) => api.get<ResearchFinding>(`${projectBase(projectId)}/findings/${findingId}`),
  addFinding: (projectId: string, engagementId: string, values: { title: string; description?: string }) =>
    api.post<ResearchFinding>(`${projectBase(projectId)}/engagements/${engagementId}/findings`, values),
  updateFinding: (projectId: string, findingId: string, values: { title?: string; description?: string }) =>
    api.put<ResearchFinding>(`${projectBase(projectId)}/findings/${findingId}`, values),
  deleteFinding: (projectId: string, findingId: string) => api.delete<void>(`${projectBase(projectId)}/findings/${findingId}`),
  findingOutcomes: buildOutcomeCalls("findings"),
};
