/**
 * Module: modules/architecture/architectureFixtures
 *
 * Shared Storybook fixtures for the System Architecture components: builders for an element, a connection, a port, the
 * two kinds of type, a symbol and a collection, plus the ids and the organisation's members the stories share. Imported
 * by stories only.
 */
import { spyOn } from "storybook/test";

import { ApiError, api } from "../../api/client";
import type { Placement } from "../../api/placements";
import type { AnchoredThread, RecordThread } from "../../api/recordComments";
import type { OrgUser } from "../../api/types";
import { buildTree } from "../../testing/placementsFixtures";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import type {
  ArchitectureCollection, ArchitectureConnection, ArchitectureFolder, ArchitectureRecordStatus, ArchitectureDiagram, ArchitectureElement, ArchitectureSymbol, ConnectionType,
  DiagramModel, DiagramNote, DiagramToggle, DiagramView, DiagramViewBoundary, DiagramViewEdge, DiagramViewNode, ElementType, ModelConnectionType,
  ModelElement, Port, ArchitectureState, StateMachineDiagram, StateMachineFinding, StateMachineModel, StateTransition,
} from "./types";

export const PROJECT_ID = "project-1";
export const ORG_ID = "org-1";

export const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

/** The moves the server's status map allows from each state (a copy for stories; the server holds the real map). */
const STATUS_MOVES: Record<ArchitectureRecordStatus, ArchitectureRecordStatus[]> = {
  draft: ["proposed", "active", "rejected"], proposed: ["active", "draft", "rejected"], active: ["retired"],
  retired: ["active"], rejected: ["draft"],
};

/** `allowed_status_moves` for a built record: those of `status` (Active when not given). */
function movesFrom(status: ArchitectureRecordStatus = "active"): ArchitectureRecordStatus[] {
  return STATUS_MOVES[status];
}

export function buildPort(overrides: Partial<Port> = {}): Port {
  return {
    id: "port-1", element_id: "el-1", name: "HTTPS API", direction: "in", connection_type_id: "ct-1",
    connection_type_name: "REST API", sort_order: 0, ...overrides,
  };
}

export function buildElement(overrides: Partial<ArchitectureElement> = {}): ArchitectureElement {
  return {
    id: "el-1", project_id: PROJECT_ID, organization_id: null, shared: false, unique_code: "ELM-001", name: "Gateway",
    description: "Terminates client traffic.", display_note: "", element_type_id: "et-1", element_type_name: "Service", symbol_id: null,
    effective_symbol_id: null, parent_id: null, folder_id: null, folder_path: null, owner: null, status: "active", allowed_status_moves: movesFrom(overrides.status), version: 1, creator_id: "user-1",
    is_archived: false, archived_at: null, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
    child_count: 0, connection_count: 1, ports: [buildPort()], ...overrides,
  };
}

export function buildConnection(overrides: Partial<ArchitectureConnection> = {}): ArchitectureConnection {
  return {
    id: "con-1", project_id: PROJECT_ID, unique_code: "CON-001", name: "Client traffic", connection_type_id: "ct-1",
    connection_type_name: "REST API", directional: true, source_element_id: "el-1", source_element_code: "ELM-001",
    source_element_name: "Gateway", source_port_id: "port-1", source_port_name: "HTTPS API", source_locked: false,
    source_shared: false, target_element_id: "el-2", target_element_code: "ELM-002", target_element_name: "Orders",
    target_port_id: null, target_port_name: null, target_locked: false, target_shared: false, protocol: "HTTPS/1.1",
    description: "", folder_id: null, folder_path: null, status: "active", allowed_status_moves: movesFrom(overrides.status),
    version: 1, creator_id: "user-1", is_archived: false, archived_at: null,
    created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", realises: [], realised_by: [], ...overrides,
  };
}

export function buildDiagram(overrides: Partial<ArchitectureDiagram> = {}): ArchitectureDiagram {
  return {
    id: "dgm-1", project_id: PROJECT_ID, unique_code: "DGM-001", name: "Platform overview", purpose: "How traffic reaches the services.",
    scope_element_id: null, scope_element_code: null, scope_element_name: null, connection_detail: false,
    folder_id: null, folder_path: null, status: "active", allowed_status_moves: movesFrom(overrides.status), version: 3, creator_id: "user-1", is_archived: false, archived_at: null, created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z", placement_count: 3, note_count: 0, toggle_count: 1, ...overrides,
  };
}

/** A state machine diagram of the fixtures' Gateway element. */
export function buildStateMachine(overrides: Partial<StateMachineDiagram> = {}): StateMachineDiagram {
  return {
    id: "smd-1", project_id: PROJECT_ID, unique_code: "SMD-001", name: "Gateway modes", description: "The operating modes of the gateway.",
    element_id: "el-1", element_code: "ELM-001", element_name: "Gateway", status: "draft", allowed_status_moves: movesFrom(overrides.status ?? "draft"),
    version: 5, creator_id: "user-1", is_archived: false, archived_at: null, created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z", state_count: 4, transition_count: 4, error_count: 0, warning_count: 0, ...overrides,
  };
}

/** A state (or marker) of `buildStateMachine`'s diagram. */
export function buildState(overrides: Partial<ArchitectureState> = {}): ArchitectureState {
  return {
    id: "ste-1", project_id: PROJECT_ID, unique_code: "STE-001", state_machine_diagram_id: "smd-1", state_machine_diagram_code: "SMD-001",
    state_machine_diagram_name: "Gateway modes", state_machine_diagram_version: 5, element_id: "el-1", element_code: "ELM-001",
    element_name: "Gateway", name: "Idle", description: "", kind: "state", parent_state_id: null, parent_state_code: null,
    entry_action: "", exit_action: "", activity: "", x: 200, y: 40, width: 160, height: 64, collapsed: false, status: "draft",
    is_archived: false, creator_id: "user-1", created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...overrides,
  };
}

/** A transition between two of the fixtures' states. */
export function buildTransition(overrides: Partial<StateTransition> = {}): StateTransition {
  return {
    id: "trn-1", state_machine_diagram_id: "smd-1", state_machine_diagram_version: 5, source_state_id: "ste-1", source_state_code: "STE-001",
    target_state_id: "ste-2", target_state_code: "STE-002", event: "start", guard: "", action: "", description: "", sort_order: 0,
    source_point: null, target_point: null, ...overrides,
  };
}

/**
 * A small, sound state machine: an initial marker, Idle (entry and exit lines), Running (a self loop) and a final marker.
 * Pass `findings` to show the checks' answers on it.
 */
export function buildStateMachineModel(overrides: Partial<StateMachineModel> & { findings?: StateMachineFinding[] } = {}): StateMachineModel {
  const states = overrides.states ?? [
    buildState({ id: "ste-0", unique_code: "STE-000", name: "Initial state", kind: "initial", x: 40, y: 56, width: 20, height: 20 }),
    buildState({ id: "ste-1", name: "Idle", entry_action: "stop motor", exit_action: "log", x: 120, y: 34 }),
    buildState({ id: "ste-2", unique_code: "STE-002", name: "Running", activity: "regulate", x: 360, y: 34 }),
    buildState({ id: "ste-3", unique_code: "STE-003", name: "Final state", kind: "final", x: 620, y: 52, width: 28, height: 28 }),
  ];
  const transitions = overrides.transitions ?? [
    buildTransition({ id: "trn-0", source_state_id: "ste-0", source_state_code: "STE-000", target_state_id: "ste-1", target_state_code: "STE-001", event: "" }),
    buildTransition({ id: "trn-1", event: "start", guard: "ready" }),
    buildTransition({ id: "trn-2", source_state_id: "ste-2", source_state_code: "STE-002", target_state_id: "ste-2", target_state_code: "STE-002", event: "tick", action: "adjust" }),
    buildTransition({ id: "trn-3", source_state_id: "ste-2", source_state_code: "STE-002", target_state_id: "ste-3", target_state_code: "STE-003", event: "stop" }),
  ];
  return { diagram: buildStateMachine(), states, transitions, findings: [], ...overrides };
}

export function buildViewNode(overrides: Partial<DiagramViewNode> = {}): DiagramViewNode {
  return {
    placement_id: "pl-1", element_id: "el-1", unique_code: "ELM-001", name: "Gateway", display_note: "", locked: false, shared: false, hidden: false,
    status: "active", parent_id: null, element_type_id: "et-1", element_type_name: "Service", shape: "rounded",
    color_light: "#dbeafe", color_dark: "#1e3a8a", symbol_id: null, ports: [], x: 0, y: 0, width: 160, height: 80,
    collapsed: false, internal_connection_ids: [], ...overrides,
  };
}

export function buildViewEdge(overrides: Partial<DiagramViewEdge> = {}): DiagramViewEdge {
  return {
    id: "edge-1", source_element_id: "el-1", target_element_id: "el-2", source_is_boundary: false, target_is_boundary: false, two_way: false, indirect: false, rolled_up: false,
    bridged: false, count: 1, type_name: null, line_style: null, color_light: null, color_dark: null, label: null,
    connections: [buildConnection()], hops: [], ...overrides,
  };
}

/** An annotation as the view lists it: neutral, 160 x 60 at the origin, with no leader. */
export function buildNote(overrides: Partial<DiagramNote> = {}): DiagramNote {
  return {
    id: "nt-1", text: "Check with ops", x: 0, y: -120, width: 160, height: 60, tone: "neutral", leader_kind: "none",
    leader_element_id: null, leader_connection_id: null, leader_x: null, leader_y: null, leader_arrow: true, ...overrides,
  };
}

export const FIREWALL_TOGGLE: DiagramToggle = {
  id: "tg-1", name: "Security devices", default_on: true, on: true, sort_order: 0, element_ids: ["el-3"], connection_ids: [],
  rule: { element_type_ids: [], connection_type_ids: [], domains: [], tags: [] },
};

/** Three placed elements (Gateway, Orders, Firewall), one line between the first two and one switch. */
export function buildDiagramView(overrides: Partial<DiagramView> = {}): DiagramView {
  return {
    diagram: buildDiagram(),
    toggles: [FIREWALL_TOGGLE],
    nodes: [
      buildViewNode(),
      buildViewNode({ placement_id: "pl-2", element_id: "el-2", unique_code: "ELM-002", name: "Orders", x: 300, y: 0 }),
      buildViewNode({ placement_id: "pl-3", element_id: "el-3", unique_code: "ELM-003", name: "Firewall", x: 150, y: 150 }),
    ],
    edges: [buildViewEdge()],
    notes: [],
    anchors: [],
    boundaries: [],
    ...overrides,
  };
}

/** An element as the diagram model lists it. */
export function buildModelElement(overrides: Partial<ModelElement> = {}): ModelElement {
  return {
    id: "el-1", unique_code: "ELM-001", name: "Gateway", display_note: "", locked: false, shared: false, status: "active",
    element_type_id: "et-1",
    element_type_name: "Service", color_light: "#dbeafe", color_dark: "#1e3a8a", symbol_id: null, ...overrides,
  };
}

/** The connection type `buildConnection` uses, as the diagram model lists it. */
export const MODEL_REST_TYPE: ModelConnectionType = {
  id: "ct-1", name: "REST API", directional: true, line_style: "solid", color_light: null, color_dark: null,
};

/**
 * The model data behind `buildDiagramView`: Gateway, Orders, Firewall and the unplaced Cache (no parents), one connection
 * from Gateway to Orders, and the switch holding the Firewall.
 */
export function buildDiagramModel(overrides: Partial<DiagramModel> = {}): DiagramModel {
  return {
    elements: [
      buildModelElement(),
      buildModelElement({ id: "el-2", unique_code: "ELM-002", name: "Orders" }),
      buildModelElement({ id: "el-3", unique_code: "ELM-003", name: "Firewall" }),
      buildModelElement({ id: "el-4", unique_code: "ELM-004", name: "Cache" }),
    ],
    parents: { "el-1": null, "el-2": null, "el-3": null, "el-4": null },
    connections: [buildConnection()],
    connection_types: [MODEL_REST_TYPE],
    toggle_members: [{ toggle_id: "tg-1", element_ids: ["el-3"], connection_ids: [] }],
    realisations: [],
    ...overrides,
  };
}

/** A boundary box of the scoped scene below (`buildBoundaryScene`): the outer connection CON-009 from Platform to Cloud. */
export function buildViewBoundary(overrides: Partial<DiagramViewBoundary> = {}): DiagramViewBoundary {
  return {
    id: "bx-1", connection_id: "con-9", connection_code: "CON-009", connection_name: "Platform uplink", type_name: "REST API",
    shape: "output", locked: false, outside_element_id: "el-8", outside_element_code: "ELM-008", outside_element_name: "Cloud",
    scope_end_element_id: "el-9", scope_end_port_name: null, covered: true, realised_by_count: 1, x: 400, y: 40, width: 140, height: 56,
    ...overrides,
  };
}

/**
 * A diagram of the inside of Platform (ELM-009): Gateway and Orders placed inside it, Cloud (ELM-008) outside it, the outer
 * connection CON-009 (Platform to Cloud) drawn as a boundary box, and CON-010 (Gateway to Platform) realising it. The view's
 * lines are not used by the editor (it resolves them from the model); `edges` holds the one drawn to the box for completeness.
 */
export function buildBoundaryScene(opts: { realised?: boolean } = {}): { view: DiagramView; model: DiagramModel; elements: ArchitectureElement[] } {
  const realised = opts.realised ?? true;
  const outer = buildConnection({
    id: "con-9", unique_code: "CON-009", name: "Platform uplink", source_element_id: "el-9", source_element_code: "ELM-009",
    source_element_name: "Platform", source_port_id: null, source_port_name: null, target_element_id: "el-8",
    target_element_code: "ELM-008", target_element_name: "Cloud", target_port_id: null, protocol: "HTTPS",
    realised_by: realised ? [{ id: "con-10", unique_code: "CON-010", name: "Gateway uplink", status: "active" }] : [],
  });
  const inner = buildConnection({
    id: "con-10", unique_code: "CON-010", name: "Gateway uplink", source_element_id: "el-1", source_element_code: "ELM-001",
    source_element_name: "Gateway", source_port_id: null, source_port_name: null, target_element_id: "el-9",
    target_element_code: "ELM-009", target_element_name: "Platform", target_port_id: null, protocol: "HTTPS",
    realises: realised ? [{ id: "con-9", unique_code: "CON-009", name: "Platform uplink", status: "active" }] : [],
  });
  const between = buildConnection({
    id: "con-11", unique_code: "CON-011", name: "Order flow", source_element_id: "el-1", source_element_code: "ELM-001",
    source_element_name: "Gateway", target_element_id: "el-2", target_element_code: "ELM-002", target_element_name: "Orders",
  });
  const view = buildDiagramView({
    diagram: buildDiagram({ scope_element_id: "el-9", scope_element_code: "ELM-009", scope_element_name: "Platform", toggle_count: 0, placement_count: 2 }),
    toggles: [],
    nodes: [
      buildViewNode({ parent_id: "el-9" }),
      buildViewNode({ placement_id: "pl-2", element_id: "el-2", unique_code: "ELM-002", name: "Orders", x: 200, y: 160, parent_id: "el-9" }),
    ],
    edges: [buildViewEdge({
      id: "edge-bx", source_element_id: "el-1", target_element_id: "bx-1", target_is_boundary: true, connections: [inner],
    }), buildViewEdge({ id: "edge-order", source_element_id: "el-1", target_element_id: "el-2", connections: [between] })],
    boundaries: [buildViewBoundary({ covered: realised, realised_by_count: realised ? 1 : 0 })],
  });
  const model = buildDiagramModel({
    elements: [
      buildModelElement(), buildModelElement({ id: "el-2", unique_code: "ELM-002", name: "Orders" }),
      buildModelElement({ id: "el-9", unique_code: "ELM-009", name: "Platform" }),
      buildModelElement({ id: "el-8", unique_code: "ELM-008", name: "Cloud" }),
    ],
    parents: { "el-1": "el-9", "el-2": "el-9", "el-9": null, "el-8": null },
    connections: [outer, inner, between],
    toggle_members: [],
    realisations: realised ? [{ inner_connection_id: "con-10", outer_connection_id: "con-9" }] : [],
  });
  const elements = [
    buildElement({ parent_id: "el-9" }), buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [], parent_id: "el-9" }),
    buildElement({ id: "el-9", unique_code: "ELM-009", name: "Platform", ports: [], child_count: 2 }),
    buildElement({ id: "el-8", unique_code: "ELM-008", name: "Cloud", ports: [] }),
  ];
  return { view, model, elements };
}

export const ELEMENT_TYPES: ElementType[] = [
  { id: "et-1", project_id: null, organization_id: ORG_ID, name: "Service", domain: "software", shape: "rounded", color_light: "#dbeafe", color_dark: "#1e3a8a", symbol_id: null, sort_order: 0, suggested_connection_type_ids: ["ct-1"] },
  { id: "et-2", project_id: null, organization_id: ORG_ID, name: "Board", domain: "hardware", shape: "chip", color_light: null, color_dark: null, symbol_id: null, sort_order: 1, suggested_connection_type_ids: ["ct-2"] },
  { id: "et-3", project_id: PROJECT_ID, organization_id: null, name: "Custom block", domain: "any", shape: "rectangle", color_light: null, color_dark: null, symbol_id: null, sort_order: 2, suggested_connection_type_ids: [] },
];

export const CONNECTION_TYPES: ConnectionType[] = [
  { id: "ct-1", project_id: null, organization_id: ORG_ID, name: "REST API", domain: "software", line_style: "solid", directional: true, color_light: null, color_dark: null, sort_order: 0, parent_ids: [] },
  { id: "ct-2", project_id: PROJECT_ID, organization_id: null, name: "I2C", domain: "hardware", line_style: "dashed", directional: false, color_light: "#065f46", color_dark: "#6ee7b7", sort_order: 1, parent_ids: ["ct-3"] },
  { id: "ct-3", project_id: null, organization_id: ORG_ID, name: "Serial bus", domain: "hardware", line_style: "solid", directional: false, color_light: null, color_dark: null, sort_order: 2, parent_ids: [] },
];

export const SYMBOLS: ArchitectureSymbol[] = [
  { id: "sym-1", project_id: null, organization_id: ORG_ID, name: "Server", builtin_key: "server", is_builtin: true, sort_order: 0 },
  { id: "sym-2", project_id: PROJECT_ID, organization_id: null, name: "Vendor router", builtin_key: null, is_builtin: false, sort_order: 1 },
];

export function buildCollection(overrides: Partial<ArchitectureCollection> = {}): ArchitectureCollection {
  return {
    id: "col-1", project_id: PROJECT_ID, organization_id: null, name: "Shared infrastructure", description: "Used by other teams.",
    member_count: 1, grant_count: 1,
    grants: [{ id: "grant-1", project_id: "project-2", project_name: "Billing", project_code: "BILL", group: null, include_descendants: true, created_at: "2026-11-01T00:00:00Z" }],
    created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...overrides,
  };
}

export function buildFolder(overrides: Partial<ArchitectureFolder> = {}): ArchitectureFolder {
  const name = overrides.name ?? "Software";
  return {
    id: "fold-1", project_id: PROJECT_ID, organization_id: null, kind: "element", name, parent_id: null, sort_order: 0,
    path: name, record_count: 0, ...overrides,
  };
}

/** A minimal SVG a story's symbol request answers with. */
export const SYMBOL_SVG = new Blob(
  ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'], { type: "image/svg+xml" },
);

/** What `mockArchitectureReads` answers with; each list defaults to the fixtures above or empty. */
export interface ArchitectureReads {
  elements?: ArchitectureElement[];
  shared?: ArchitectureElement[];
  connections?: ArchitectureConnection[];
  collections?: ArchitectureCollection[];
  element?: ArchitectureElement;
  connection?: ArchitectureConnection;
  diagrams?: ArchitectureDiagram[];
  diagramView?: DiagramView;
  diagramModel?: DiagramModel;
  /** The project's state machine diagrams (the Diagrams list merges them with `diagrams`); none by default. */
  stateMachines?: StateMachineDiagram[];
  /** Answers the state machine diagram list as refused (403), as for a person with no access to that type. */
  stateMachinesRefused?: boolean;
  /** The state machine diagram's model (the editor's data). */
  stateMachineModel?: StateMachineModel;
  /** The project-wide States list. */
  states?: ArchitectureState[];
  /** Sub-components switched off for the project (the page hides their tabs). */
  disabledSubComponents?: string[];
  /** The project's (or organisation's) folders, answered for every kind and filtered by the kind in the address. */
  folders?: ArchitectureFolder[];
  /** Whether the viewer may manage the project's types (shows the Add menu's setup entry). */
  canManageTypes?: boolean;
  /** `{element id: places}`; when given, the project has the shared component tree and the elements' places are readable and editable. */
  placements?: Record<string, Placement[]>;
  /** The record comments the generic API answers with (a diagram's, element's or connection's); empty by default. */
  comments?: Partial<RecordThread>;
  /** The pinned threads anchored to a box or line (`anchored-comments`); none by default. */
  anchoredComments?: AnchoredThread[];
}

/**
 * Answers the GET requests the architecture screens make, so a story needs no network. A path it does not know throws,
 * which the screens treat as an empty optional list (tags, placements, link types).
 *
 * @param reads The records to answer with.
 */
export function mockArchitectureReads(reads: ArchitectureReads = {}) {
  const elements = reads.elements ?? [buildElement()];
  spyOn(api, "getForBlob").mockResolvedValue(SYMBOL_SVG);
  return spyOn(api, "get").mockImplementation(async (path: string) => {
    const base = path.split("?")[0];
    if (base.endsWith("/modules/architecture/capabilities")) return { manage_types: reads.canManageTypes ?? false };
    if (base.endsWith("/enabled-modules")) {
      return [{ module_key: "architecture", name: "System Architecture", frontend_manifest: null, disabled_sub_components: reads.disabledSubComponents ?? [] }];
    }
    if (base.endsWith("/anchored-comments")) return { threads: reads.anchoredComments ?? [] };
    if (base.endsWith("/comments")) return { comments: [], pins: [], can_pin: base.includes("/architecture_diagram/") || base.includes("/architecture_state_machine_diagram/"), can_manage: true, ...reads.comments };
    if (path.endsWith("/records/architecture_element/columns")) return buildRecordColumns({ label: "Elements" });
    if (path.endsWith("/records/architecture_connection/columns")) return buildRecordColumns({ label: "Connections" });
    const folderKind = /\/modules\/architecture\/(element|connection|diagram)-folders$/.exec(base);
    if (folderKind) return (reads.folders ?? []).filter((f) => f.kind === folderKind[1]);
    if (base.endsWith("/modules/architecture/element-types")) return ELEMENT_TYPES;
    if (base.endsWith("/modules/architecture/connection-types")) return CONNECTION_TYPES;
    if (base.endsWith("/modules/architecture/symbols")) return SYMBOLS;
    if (base.includes("/modules/architecture/symbols/") && base.endsWith("/content")) return SYMBOL_SVG;
    if (base.endsWith("/modules/architecture/elements/shared")) return reads.shared ?? [];
    if (base.endsWith("/modules/architecture/elements")) return elements;
    if (base.includes("/modules/architecture/elements/")) return reads.element ?? elements[0];
    if (base.endsWith("/modules/architecture/connections")) return reads.connections ?? [buildConnection()];
    if (base.includes("/modules/architecture/connections/")) return reads.connection ?? buildConnection();
    if (base.endsWith("/modules/architecture/state-machine-diagrams")) {
      if (reads.stateMachinesRefused) throw new ApiError(403, "You do not have access to state machine diagrams.");
      return reads.stateMachines ?? [];
    }
    if (base.includes("/modules/architecture/state-machine-diagrams/") && base.endsWith("/model")) return reads.stateMachineModel ?? buildStateMachineModel();
    if (base.includes("/modules/architecture/state-machine-diagrams/")) return (reads.stateMachineModel ?? buildStateMachineModel()).diagram;
    if (base.endsWith("/modules/architecture/states")) return reads.states ?? [];
    if (base.includes("/modules/architecture/states/") && base.endsWith("/impact")) return { transitions: 2, links: 1 };
    if (base.endsWith("/modules/architecture/diagrams")) return reads.diagrams ?? [buildDiagram()];
    if (base.includes("/modules/architecture/diagrams/") && base.endsWith("/view")) return reads.diagramView ?? buildDiagramView();
    if (base.includes("/modules/architecture/diagrams/") && base.endsWith("/model")) return reads.diagramModel ?? buildDiagramModel();
    if (base.includes("/modules/architecture/diagrams/")) return (reads.diagramView ?? buildDiagramView()).diagram;
    if (path.endsWith("/records/architecture_state_machine_diagram/columns")) return buildRecordColumns({ label: "State machine diagrams" });
    if (path.endsWith("/records/architecture_state/columns")) return buildRecordColumns({ label: "States" });
    if (path.endsWith("/records/architecture_diagram/columns")) return buildRecordColumns({ label: "Diagrams" });
    if (base.endsWith("/modules/architecture/collections")) return reads.collections ?? [buildCollection()];
    if (base.includes("/collections/") && base.endsWith("/members")) return [{ element_id: "el-1", unique_code: "ELM-001", name: "Gateway" }];
    if (reads.placements) {
      const tree = buildTree();
      if (base.endsWith("/components")) return tree.components;
      if (base.endsWith("/categories")) return tree.categories;
      if (base.endsWith("/placements/architecture_element")) return { placements: reads.placements };
      const own = /\/artefacts\/architecture_element\/([^/]+)\/placements$/.exec(base);
      if (own) return { placements: reads.placements[own[1]] ?? [], can_edit: true, managed_on_record: false };
    }
    if (base.endsWith("/users")) return ORG_USERS;
    if (base.endsWith("/groups")) return [];
    if (base.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: ORG_ID, name: "Platform", code: "PLAT" };
    if (base.endsWith("/api/v1/projects")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}
