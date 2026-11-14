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
  AllocationAcceptResult,
  AllocationCoverage,
  AllocationView,
  ArchitectureCollection,
  ArchitectureConnection,
  ArchitectureDiagram,
  ArchitectureElement,
  ArchitectureFolder,
  ArchitectureRecordStatus,
  ArchitectureState,
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
  FolderKind,
  NoteValues,
  BoundaryValues,
  DiagramAnchor,
  PlacementValues,
  Port,
  PortValues,
  StateFieldValues,
  StateKind,
  StateLayoutValues,
  StateMachineCreateValues,
  StateMachineDiagram,
  StateMachineFieldValues,
  StateMachineModel,
  StateTransition,
  TransitionFieldValues,
  TransitionPointsValues,
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

/** The plain text filters the lists send as query parameters. */
const LIST_QUERY_KEYS = ["status", "element_type_id", "connection_type_id", "element_id", "parent_id", "search", "kind", "state_machine_diagram_id"];

/** Writes the simple filters the lists share as query parameters. */
function listQuery(
  filters: ElementListFilters | ConnectionListFilters | DiagramListFilters | StateMachineListFilters | StateListFilters,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (typeof value === "boolean") {
      if (value) params.set(key, "true");
    } else if (typeof value === "string" && LIST_QUERY_KEYS.includes(key) && value) {
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

/** What the caller may change in a project (`GET .../capabilities`), so a screen offers only actions that will be accepted. */
export const capabilitiesApi = {
  get: (projectId: string) => api.get<{ manage_types: boolean }>(`${projectBase(projectId)}/capabilities`),
};

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
    /** Sets the outer connections a connection realises (the server checks the rule and refuses a cycle). */
    setRealisations: (id: string, version: number, outerConnectionIds: string[]) =>
      api.put<ArchitectureConnection>(`${base}/${id}/realisations`, { version, outer_connection_ids: outerConnectionIds }),
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
    saveLayout: (
      id: string, version: number, placements: PlacementValues[], notes: NoteValues[], anchors: DiagramAnchor[],
      boundaries: BoundaryValues[],
    ) => api.put<ArchitectureDiagram>(`${base}/${id}/layout`, { version, placements, notes, anchors, boundaries }),
    saveToggles: (id: string, version: number, toggles: DiagramToggleValues[]) =>
      api.put<ArchitectureDiagram>(`${base}/${id}/toggles`, { version, toggles }),
    /** The saved diagram drawn by the server as an SVG document, for the view-switch states named. */
    svg: async (id: string, states: ToggleStates) => (await api.getForBlob(`${base}/${id}/svg${statesQuery(states)}`)).text(),
    /** The saved diagram as Mermaid flowchart text, for the view-switch states named. */
    mermaid: async (id: string, states: ToggleStates) => (await api.getForBlob(`${base}/${id}/mermaid${statesQuery(states)}`)).text(),
  };
};

/** Filters of the state machine diagram list. */
export interface StateMachineListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  status?: ArchitectureRecordStatus;
  open_only?: boolean;
  search?: string;
  element_id?: string;
}

/** Filters of the project-wide state list. */
export interface StateListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  kind?: StateKind;
  search?: string;
  state_machine_diagram_id?: string;
}

/** What a state is created with: the diagram's `version` (the lock), the fields and the drawing. */
export interface StateCreateValues extends StateFieldValues {
  parent_state_id: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A project's state machine diagrams with their states and transitions (each write quotes the diagram's `version`). */
export const projectStateMachineApi = (projectId: string) => {
  const base = `${projectBase(projectId)}/state-machine-diagrams`;
  return {
    list: (filters: StateMachineListFilters = {}) => api.get<StateMachineDiagram[]>(`${base}${listQuery(filters)}`),
    create: (values: StateMachineCreateValues) => api.post<StateMachineDiagram>(base, values),
    get: (id: string) => api.get<StateMachineDiagram>(`${base}/${id}`),
    /** The diagram with its states, transitions and modelling findings. */
    model: (id: string) => api.get<StateMachineModel>(`${base}/${id}/model`),
    update: (id: string, version: number, values: Partial<StateMachineFieldValues>) =>
      api.put<StateMachineDiagram>(`${base}/${id}`, { version, ...values }),
    setStatus: (id: string, version: number, status: ArchitectureRecordStatus) =>
      api.post<StateMachineDiagram>(`${base}/${id}/status`, { version, status }),
    archive: (id: string) => api.post<StateMachineDiagram>(`${base}/${id}/archive`),
    unarchive: (id: string) => api.post<StateMachineDiagram>(`${base}/${id}/unarchive`),
    remove: (id: string) => api.delete<void>(`${base}/${id}`),
    saveLayout: (id: string, version: number, states: StateLayoutValues[], transitions: TransitionPointsValues[]) =>
      api.put<StateMachineDiagram>(`${base}/${id}/layout`, { version, states, transitions }),
    addState: (id: string, version: number, values: StateCreateValues) =>
      api.post<ArchitectureState>(`${base}/${id}/states`, { version, ...values }),
    addTransition: (id: string, version: number, values: TransitionFieldValues) =>
      api.post<StateTransition>(`${base}/${id}/transitions`, { version, ...values }),
    updateTransition: (id: string, transitionId: string, version: number, values: Partial<TransitionFieldValues>) =>
      api.put<StateTransition>(`${base}/${id}/transitions/${transitionId}`, { version, ...values }),
    /** Deletes a transition; resolves with the diagram's new version. */
    removeTransition: (id: string, transitionId: string, version: number) =>
      api.delete<{ version: number }>(`${base}/${id}/transitions/${transitionId}?version=${version}`),
    /** The saved diagram drawn by the server as an SVG document. */
    svg: async (id: string) => (await api.getForBlob(`${base}/${id}/svg`)).text(),
    /** The saved diagram as Mermaid `stateDiagram-v2` text. */
    mermaid: async (id: string) => (await api.getForBlob(`${base}/${id}/mermaid`)).text(),
  };
};

/** A project's states: the project-wide list, one state, its edit and its delete (with the impact the confirmation names). */
export const projectStateApi = (projectId: string) => {
  const base = `${projectBase(projectId)}/states`;
  return {
    list: (filters: StateListFilters = {}) => api.get<ArchitectureState[]>(`${base}${listQuery(filters)}`),
    get: (id: string) => api.get<ArchitectureState>(`${base}/${id}`),
    update: (id: string, version: number, values: Partial<StateFieldValues> & { parent_state_id?: string | null }) =>
      api.put<ArchitectureState>(`${base}/${id}`, { version, ...values }),
    /** How many transitions and links deleting the state would remove. */
    impact: (id: string) => api.get<{ transitions: number; links: number }>(`${base}/${id}/impact`),
    /** Deletes a state with its transitions and links; resolves with what went and the diagram's new version. */
    remove: (id: string, version: number) =>
      api.delete<{ transitions: number; links: number; version: number }>(`${base}/${id}?version=${version}`),
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

/** Folders of one kind in a project, or (elements only) in an organisation: a tree that organises a list. */
function folderCalls(base: string, kind: FolderKind) {
  const url = `${base}/${kind}-folders`;
  return {
    list: () => api.get<ArchitectureFolder[]>(url),
    create: (values: { name: string; parent_id: string | null }) => api.post<ArchitectureFolder>(url, values),
    update: (id: string, values: { name?: string; parent_id?: string | null }) => api.put<ArchitectureFolder>(`${url}/${id}`, values),
    /** Deletes a folder; its records and sub-folders move to its parent. */
    remove: (id: string) => api.delete<void>(`${url}/${id}`),
    /** Puts records in a folder (null: the top level); resolves with how many changed. */
    moveRecords: (recordIds: string[], folderId: string | null) =>
      api.post<{ moved: number }>(`${url}/move-records`, { record_ids: recordIds, folder_id: folderId }),
  };
}

export const projectFolderApi = (projectId: string, kind: FolderKind) => folderCalls(projectBase(projectId), kind);
export const orgFolderApi = (organizationId: string) => folderCalls(orgBase(organizationId), "element");

/** The allocation endpoints of a project: a requirement's or an element's view, accepting, dismissing and restoring. */
export const projectAllocationApi = (projectId: string) => {
  const base = projectBase(projectId);
  return {
    forRequirement: (requirementId: string) => api.get<AllocationView>(`${base}/requirements/${requirementId}/allocation`),
    forElement: (elementId: string) => api.get<AllocationView>(`${base}/elements/${elementId}/allocation`),
    /** Turns suggested pairs into allocation links; a pair that cannot be accepted comes back in `failed`. */
    accept: (pairs: { requirement_id: string; element_id: string }[]) =>
      api.post<AllocationAcceptResult>(`${base}/allocation/accept`, { pairs }),
    dismiss: (pair: { requirement_id: string; element_id: string }) => api.post<void>(`${base}/allocation/dismiss`, pair),
    restore: (pair: { requirement_id: string; element_id: string }) => api.post<void>(`${base}/allocation/restore`, pair),
    coverage: () => api.get<AllocationCoverage>(`${base}/allocation/coverage`),
  };
};
