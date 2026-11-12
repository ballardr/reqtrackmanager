/**
 * Module: modules/architecture/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for the endpoints of
 * `backend/app/modules/architecture/{project_router,router}.py`: elements with their ports, connections, the two type
 * vocabularies, the symbol library and collections with their members and grants. Tags, links and placements use the
 * generic endpoints (`RecordTags`, `ArtefactLinksPanel`), not these. The `projectApi` family is bound to a project;
 * the `orgApi` family to an organisation (its own elements, defaults and collections).
 */
import { api } from "../../api/client";
import { appendScopeParam, type ScopeListFilters } from "../../api/projectScope";
import { appendTagParams, type TagListFilters } from "../../api/tags";
import type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import type { ToggleStates } from "./diagramExport";
import type {
  ArchitectureCollection,
  ArchitectureConnection,
  ArchitectureDiagram,
  ArchitectureElement,
  ArchitectureRecordStatus,
  ArchitectureSymbol,
  CollectionGrant,
  CollectionGrantValues,
  CollectionMember,
  ConnectionCreateValues,
  ConnectionFieldValues,
  ConnectionType,
  ConnectionTypeValues,
  DiagramCreateValues,
  DiagramFieldValues,
  DiagramToggleValues,
  DiagramModel,
  DiagramView,
  ElementCreateValues,
  ElementFieldValues,
  ElementType,
  ElementTypeValues,
  NoteValues,
  DiagramAnchor,
  PlacementValues,
  Port,
  PortValues,
} from "./types";

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/architecture`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/architecture`;

/** Filters of the element list (the server applies them, so the list and its export agree). */
export interface ElementListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  status?: ArchitectureRecordStatus;
  element_type_id?: string;
  parent_id?: string;
  roots_only?: boolean;
  open_only?: boolean;
  search?: string;
}

/** Filters of the connection list. */
export interface ConnectionListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  status?: ArchitectureRecordStatus;
  connection_type_id?: string;
  element_id?: string;
  open_only?: boolean;
  search?: string;
}

/** Writes the simple filters both lists share as query parameters. */
function listQuery(filters: ElementListFilters | ConnectionListFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (typeof value === "boolean") {
      if (value) params.set(key, "true");
    } else if (typeof value === "string" && ["status", "element_type_id", "connection_type_id", "element_id", "parent_id", "search"].includes(key) && value) {
      params.set(key, value);
    }
  }
  appendTagParams(params, filters);
  appendScopeParam(params, filters);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The vocabulary calls of one kind of type, shared by the element and connection types. */
function vocabulary<Row, Values>(path: string) {
  return {
    projectList: (projectId: string) => api.get<Row[]>(`${projectBase(projectId)}/${path}`),
    projectCreate: (projectId: string, values: Values) => api.post<Row>(`${projectBase(projectId)}/${path}`, values),
    projectUpdate: (projectId: string, id: string, values: Partial<Values>) =>
      api.patch<Row>(`${projectBase(projectId)}/${path}/${id}`, values),
    projectMove: (projectId: string, id: string, direction: "up" | "down") =>
      api.post<Row>(`${projectBase(projectId)}/${path}/${id}/move`, { direction }),
    /** Deletes a project-owned row, or hides an organisation default in the project. */
    projectDelete: (projectId: string, id: string) => api.delete<void>(`${projectBase(projectId)}/${path}/${id}`),
    projectHidden: (projectId: string) => api.get<HiddenDefinition[]>(`${projectBase(projectId)}/${path}/hidden`),
    projectRestore: (projectId: string, orgTypeIds?: string[]) =>
      api.post<unknown>(`${projectBase(projectId)}/${path}/restore`, { org_type_ids: orgTypeIds ?? null }),
    orgList: (organizationId: string) => api.get<Row[]>(`${orgBase(organizationId)}/${path}`),
    orgCreate: (organizationId: string, values: Values) => api.post<Row>(`${orgBase(organizationId)}/${path}`, values),
    orgUpdate: (organizationId: string, id: string, values: Partial<Values>) =>
      api.patch<Row>(`${orgBase(organizationId)}/${path}/${id}`, values),
    orgMove: (organizationId: string, id: string, direction: "up" | "down") =>
      api.post<Row>(`${orgBase(organizationId)}/${path}/${id}/move`, { direction }),
    orgDelete: (organizationId: string, id: string) => api.delete<void>(`${orgBase(organizationId)}/${path}/${id}`),
  };
}

export const elementTypeApi = vocabulary<ElementType, ElementTypeValues>("element-types");
export const connectionTypeApi = vocabulary<ConnectionType, ConnectionTypeValues>("connection-types");

/** The symbol library of a project or an organisation (an upload is a file, so there is no JSON create). */
export const symbolApi = {
  projectList: (projectId: string) => api.get<ArchitectureSymbol[]>(`${projectBase(projectId)}/symbols`),
  projectUpload: (projectId: string, file: File, name?: string) =>
    api.postFile<ArchitectureSymbol>(`${projectBase(projectId)}/symbols`, file, name ? { name } : undefined),
  projectRename: (projectId: string, id: string, name: string) =>
    api.patch<ArchitectureSymbol>(`${projectBase(projectId)}/symbols/${id}`, { name }),
  projectMove: (projectId: string, id: string, direction: "up" | "down") =>
    api.post<ArchitectureSymbol>(`${projectBase(projectId)}/symbols/${id}/move`, { direction }),
  projectDelete: (projectId: string, id: string) => api.delete<void>(`${projectBase(projectId)}/symbols/${id}`),
  projectHidden: (projectId: string) => api.get<HiddenDefinition[]>(`${projectBase(projectId)}/symbols/hidden`),
  projectRestore: (projectId: string, orgTypeIds?: string[]) =>
    api.post<unknown>(`${projectBase(projectId)}/symbols/restore`, { org_type_ids: orgTypeIds ?? null }),
  orgList: (organizationId: string) => api.get<ArchitectureSymbol[]>(`${orgBase(organizationId)}/symbols`),
  orgUpload: (organizationId: string, file: File, name?: string) =>
    api.postFile<ArchitectureSymbol>(`${orgBase(organizationId)}/symbols`, file, name ? { name } : undefined),
  orgRename: (organizationId: string, id: string, name: string) =>
    api.patch<ArchitectureSymbol>(`${orgBase(organizationId)}/symbols/${id}`, { name }),
  orgMove: (organizationId: string, id: string, direction: "up" | "down") =>
    api.post<ArchitectureSymbol>(`${orgBase(organizationId)}/symbols/${id}/move`, { direction }),
  orgDelete: (organizationId: string, id: string) => api.delete<void>(`${orgBase(organizationId)}/symbols/${id}`),
};

/** The URL a symbol's sanitised SVG is served from, for an `<img>` (the symbol is read through the project, which
 * applies the visibility rule). */
export function projectSymbolUrl(projectId: string, symbolId: string): string {
  return `${projectBase(projectId)}/symbols/${symbolId}/content`;
}

/** The URL of a symbol read through the organisation. */
export function orgSymbolUrl(organizationId: string, symbolId: string): string {
  return `${orgBase(organizationId)}/symbols/${symbolId}/content`;
}

/** The element and port calls of a project or an organisation (the same shapes, different scope). */
function elementCalls(base: string) {
  const url = (id: string) => `${base}/elements/${id}`;
  return {
    list: (filters: ElementListFilters = {}) => api.get<ArchitectureElement[]>(`${base}/elements${listQuery(filters)}`),
    create: (values: ElementCreateValues) => api.post<ArchitectureElement>(`${base}/elements`, values),
    get: (id: string) => api.get<ArchitectureElement>(url(id)),
    update: (id: string, version: number, values: Partial<ElementFieldValues>) =>
      api.put<ArchitectureElement>(url(id), { version, ...values }),
    setStatus: (id: string, version: number, status: ArchitectureRecordStatus) =>
      api.post<ArchitectureElement>(`${url(id)}/status`, { version, status }),
    archive: (id: string) => api.post<ArchitectureElement>(`${url(id)}/archive`),
    unarchive: (id: string) => api.post<ArchitectureElement>(`${url(id)}/unarchive`),
    remove: (id: string) => api.delete<void>(url(id)),
    addPort: (id: string, values: PortValues) => api.post<Port>(`${url(id)}/ports`, values),
    updatePort: (id: string, portId: string, values: Partial<PortValues>) =>
      api.put<Port>(`${url(id)}/ports/${portId}`, values),
    removePort: (id: string, portId: string) => api.delete<void>(`${url(id)}/ports/${portId}`),
  };
}

/** A project's elements and ports, plus the read-only elements other owners share with it. */
export const projectElementApi = (projectId: string) => ({
  ...elementCalls(projectBase(projectId)),
  /** Elements other owners share with the project; `open_only` leaves out retired ones (the picker's view). */
  listShared: (filters: { open_only?: boolean; search?: string } = {}) =>
    api.get<ArchitectureElement[]>(`${projectBase(projectId)}/elements/shared${listQuery(filters)}`),
});

/** An organisation's own elements (shared with projects through collections). */
export const orgElementApi = (organizationId: string) => elementCalls(orgBase(organizationId));

/** A project's connections. */
export const projectConnectionApi = (projectId: string) => {
  const base = `${projectBase(projectId)}/connections`;
  return {
    list: (filters: ConnectionListFilters = {}) => api.get<ArchitectureConnection[]>(`${base}${listQuery(filters)}`),
    create: (values: ConnectionCreateValues) => api.post<ArchitectureConnection>(base, values),
    get: (id: string) => api.get<ArchitectureConnection>(`${base}/${id}`),
    update: (id: string, version: number, values: Partial<ConnectionFieldValues>) =>
      api.put<ArchitectureConnection>(`${base}/${id}`, { version, ...values }),
    setStatus: (id: string, version: number, status: ArchitectureRecordStatus) =>
      api.post<ArchitectureConnection>(`${base}/${id}/status`, { version, status }),
    archive: (id: string) => api.post<ArchitectureConnection>(`${base}/${id}/archive`),
    unarchive: (id: string) => api.post<ArchitectureConnection>(`${base}/${id}/unarchive`),
    remove: (id: string) => api.delete<void>(`${base}/${id}`),
  };
};

/** Filters of the diagram list. */
export interface DiagramListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  status?: ArchitectureRecordStatus;
  open_only?: boolean;
  search?: string;
}

/** A project's diagrams: the record, its layout and toggles (each save quotes the version it was based on). */
export const projectDiagramApi = (projectId: string) => {
  const base = `${projectBase(projectId)}/diagrams`;
  return {
    list: (filters: DiagramListFilters = {}) => api.get<ArchitectureDiagram[]>(`${base}${listQuery(filters)}`),
    create: (values: DiagramCreateValues) => api.post<ArchitectureDiagram>(base, values),
    get: (id: string) => api.get<ArchitectureDiagram>(`${base}/${id}`),
    update: (id: string, version: number, values: Partial<DiagramFieldValues>) =>
      api.put<ArchitectureDiagram>(`${base}/${id}`, { version, ...values }),
    setStatus: (id: string, version: number, status: ArchitectureRecordStatus) =>
      api.post<ArchitectureDiagram>(`${base}/${id}/status`, { version, status }),
    archive: (id: string) => api.post<ArchitectureDiagram>(`${base}/${id}/archive`),
    unarchive: (id: string) => api.post<ArchitectureDiagram>(`${base}/${id}/unarchive`),
    remove: (id: string) => api.delete<void>(`${base}/${id}`),
    /** The diagram resolved for the caller on the saved view-switch defaults: its boxes, notes and switches. */
    view: (id: string) => api.get<DiagramView>(`${base}/${id}/view`),
    /** The model data the diagram's lines are resolved from in the browser. */
    model: (id: string) => api.get<DiagramModel>(`${base}/${id}/model`),
    saveLayout: (id: string, version: number, placements: PlacementValues[], notes: NoteValues[], anchors: DiagramAnchor[]) =>
      api.put<ArchitectureDiagram>(`${base}/${id}/layout`, { version, placements, notes, anchors }),
    saveToggles: (id: string, version: number, toggles: DiagramToggleValues[]) =>
      api.put<ArchitectureDiagram>(`${base}/${id}/toggles`, { version, toggles }),
    /** The saved diagram drawn by the server as an SVG document, for the view-switch states named. */
    svg: async (id: string, states: ToggleStates) => (await api.getForBlob(`${base}/${id}/svg${statesQuery(states)}`)).text(),
    /** The saved diagram as Mermaid flowchart text, for the view-switch states named. */
    mermaid: async (id: string, states: ToggleStates) => (await api.getForBlob(`${base}/${id}/mermaid${statesQuery(states)}`)).text(),
  };
};

/** The query naming a page's view-switch states (`toggle_on` / `toggle_off` repeated per id). */
function statesQuery(states: ToggleStates): string {
  const query = new URLSearchParams();
  states.on.forEach((id) => query.append("toggle_on", id));
  states.off.forEach((id) => query.append("toggle_off", id));
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** Collections of a project or an organisation: their members (the tops of the subtrees shared) and grants. */
function collectionCalls(base: string) {
  const url = (id: string) => `${base}/collections/${id}`;
  return {
    list: () => api.get<ArchitectureCollection[]>(`${base}/collections`),
    create: (values: { name: string; description: string }) => api.post<ArchitectureCollection>(`${base}/collections`, values),
    update: (id: string, values: { name?: string; description?: string }) => api.put<ArchitectureCollection>(url(id), values),
    remove: (id: string) => api.delete<void>(url(id)),
    members: (id: string) => api.get<CollectionMember[]>(`${url(id)}/members`),
    addMembers: (id: string, elementIds: string[]) =>
      api.post<CollectionMember[]>(`${url(id)}/members`, { element_ids: elementIds }),
    removeMember: (id: string, elementId: string) => api.delete<void>(`${url(id)}/members/${elementId}`),
    addGrant: (id: string, values: CollectionGrantValues) => api.post<CollectionGrant>(`${url(id)}/grants`, values),
    removeGrant: (id: string, grantId: string) => api.delete<void>(`${url(id)}/grants/${grantId}`),
  };
}

export const projectCollectionApi = (projectId: string) => collectionCalls(projectBase(projectId));
export const orgCollectionApi = (organizationId: string) => collectionCalls(orgBase(organizationId));
