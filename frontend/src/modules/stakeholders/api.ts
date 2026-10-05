/**
 * Module: modules/stakeholders/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for every Persona
 * endpoint `backend/app/modules/stakeholders/{router,project_router}.py`
 * exposes. `projectPersonaApi`/`orgPersonaApi` share the endpoint suffixes
 * the two scopes have in common (`buildPersonaApi`, parameterised by the base
 * URL), then `projectPersonaApi` adds the project-only weight override and
 * persona-type calls; the org Persona-type calls live on `orgPersonaTypeApi`.
 * `id` parameters are a `project_id` or `organization_id` to match.
 */
import { api } from "../../api/client";
import type { FileAsset } from "../../api/types";
import type {
  EffectivePersonaType,
  Persona,
  PersonaComment,
  PersonaFieldValues,
  PersonaTypeDefinition,
  PersonaVersion,
} from "./types";

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/stakeholders`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/stakeholders`;

/** Every list endpoint's optional filters. */
export interface PersonaListFilters {
  include_archived?: boolean;
}

/** Create payload: the editable fields plus the people pickers' values. */
export type PersonaCreateValues = Omit<PersonaFieldValues, "change_note"> & {
  owner_id?: string | null;
  champion_id?: string | null;
};

/** Partial update payload — only keys present are changed; `null` clears a nullable field. */
export type PersonaUpdateValues = Partial<PersonaFieldValues> & { owner_id?: string | null; champion_id?: string | null };

function buildPersonaApi(base: (id: string) => string) {
  return {
    list(id: string, filters: PersonaListFilters = {}) {
      const query = filters.include_archived ? "?include_archived=true" : "";
      return api.get<Persona[]>(`${base(id)}/personas${query}`);
    },
    create(id: string, values: PersonaCreateValues) {
      return api.post<Persona>(`${base(id)}/personas`, values);
    },
    get(id: string, personaId: string) {
      return api.get<Persona>(`${base(id)}/personas/${personaId}`);
    },
    update(id: string, personaId: string, values: PersonaUpdateValues) {
      return api.put<Persona>(`${base(id)}/personas/${personaId}`, values);
    },
    listVersions(id: string, personaId: string) {
      return api.get<PersonaVersion[]>(`${base(id)}/personas/${personaId}/versions`);
    },
    archive(id: string, personaId: string) {
      return api.post<Persona>(`${base(id)}/personas/${personaId}/archive`);
    },
    unarchive(id: string, personaId: string) {
      return api.post<Persona>(`${base(id)}/personas/${personaId}/unarchive`);
    },
    activate(id: string, personaId: string, comment?: string) {
      return api.post<Persona>(`${base(id)}/personas/${personaId}/activate`, { comment: comment || null });
    },
    retire(id: string, personaId: string, comment?: string) {
      return api.post<Persona>(`${base(id)}/personas/${personaId}/retire`, { comment: comment || null });
    },
    listComments(id: string, personaId: string) {
      return api.get<PersonaComment[]>(`${base(id)}/personas/${personaId}/comments`);
    },
    addComment(id: string, personaId: string, body: string) {
      return api.post<PersonaComment>(`${base(id)}/personas/${personaId}/comments`, { body });
    },
    editComment(id: string, personaId: string, commentId: string, body: string) {
      return api.patch<PersonaComment>(`${base(id)}/personas/${personaId}/comments/${commentId}`, { body });
    },
    uploadCommentAttachment(id: string, personaId: string, commentId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/personas/${personaId}/comments/${commentId}/files`, file);
    },
    removeCommentAttachment(id: string, personaId: string, commentId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/personas/${personaId}/comments/${commentId}/files/${fileId}`);
    },
    listFiles(id: string, personaId: string) {
      return api.get<FileAsset[]>(`${base(id)}/personas/${personaId}/files`);
    },
    uploadFile(id: string, personaId: string, file: File) {
      return api.postFile<FileAsset>(`${base(id)}/personas/${personaId}/files`, file);
    },
    unlinkFile(id: string, personaId: string, fileId: string) {
      return api.delete<void>(`${base(id)}/personas/${personaId}/files/${fileId}`);
    },
  };
}

/** Org-scoped Persona endpoints — `id` is an `organization_id`. */
export const orgPersonaApi = buildPersonaApi(orgBase);

/** Project-scoped Persona endpoints (reads include the organisation's
 * personas) plus the weight override and the project type tier — `id` is a
 * `project_id`. */
export const projectPersonaApi = {
  ...buildPersonaApi(projectBase),
  setWeightOverride(projectId: string, personaId: string, weight: number) {
    return api.put<Persona>(`${projectBase(projectId)}/personas/${personaId}/weight`, { weight });
  },
  clearWeightOverride(projectId: string, personaId: string) {
    return api.delete<Persona>(`${projectBase(projectId)}/personas/${personaId}/weight`);
  },
  listTypes(projectId: string) {
    return api.get<EffectivePersonaType[]>(`${projectBase(projectId)}/persona-types`);
  },
  createLocalType(projectId: string, name: string, displayOrder?: number) {
    return api.post<unknown>(`${projectBase(projectId)}/persona-types`, { name, display_order: displayOrder ?? null });
  },
  overrideType(
    projectId: string, typeRefId: string,
    values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
  ) {
    return api.put<unknown>(`${projectBase(projectId)}/persona-types/${typeRefId}`, values);
  },
  deleteType(projectId: string, projectTypeId: string) {
    return api.delete<void>(`${projectBase(projectId)}/persona-types/${projectTypeId}`);
  },
};

/** Org-scoped `PersonaTypeDefinition` CRUD — `id` parameters are an `organization_id`. */
export const orgPersonaTypeApi = {
  list(organizationId: string) {
    return api.get<PersonaTypeDefinition[]>(`${orgBase(organizationId)}/persona-types`);
  },
  create(organizationId: string, name: string) {
    return api.post<PersonaTypeDefinition>(`${orgBase(organizationId)}/persona-types`, { name });
  },
  move(organizationId: string, typeId: string, direction: "up" | "down") {
    return api.post<PersonaTypeDefinition>(`${orgBase(organizationId)}/persona-types/${typeId}/move`, { direction });
  },
  update(organizationId: string, typeId: string, values: { name?: string; is_active?: boolean }) {
    return api.patch<PersonaTypeDefinition>(`${orgBase(organizationId)}/persona-types/${typeId}`, values);
  },
  delete(organizationId: string, typeId: string) {
    return api.delete<void>(`${orgBase(organizationId)}/persona-types/${typeId}`);
  },
};
