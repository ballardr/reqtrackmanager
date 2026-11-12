/**
 * Module: modules/architecture/architectureFixtures
 *
 * Shared Storybook fixtures for the System Architecture components: builders for an element, a connection, a port, the
 * two kinds of type, a symbol and a collection, plus the ids and the organisation's members the stories share. Imported
 * by stories only.
 */
import { spyOn } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import type {
  ArchitectureCollection, ArchitectureConnection, ArchitectureDiagram, ArchitectureElement, ArchitectureSymbol, ConnectionType,
  DiagramModel, DiagramToggle, DiagramView, DiagramViewEdge, DiagramViewNode, ElementType, ModelConnectionType, ModelElement, Port,
} from "./types";

export const PROJECT_ID = "project-1";
export const ORG_ID = "org-1";

export const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

export function buildPort(overrides: Partial<Port> = {}): Port {
  return {
    id: "port-1", element_id: "el-1", name: "HTTPS API", direction: "in", connection_type_id: "ct-1",
    connection_type_name: "REST API", sort_order: 0, ...overrides,
  };
}

export function buildElement(overrides: Partial<ArchitectureElement> = {}): ArchitectureElement {
  return {
    id: "el-1", project_id: PROJECT_ID, organization_id: null, shared: false, unique_code: "ELM-001", name: "Gateway",
    description: "Terminates client traffic.", element_type_id: "et-1", element_type_name: "Service", symbol_id: null,
    effective_symbol_id: null, parent_id: null, owner: null, status: "active", version: 1, creator_id: "user-1",
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
    description: "", status: "active", version: 1, creator_id: "user-1", is_archived: false, archived_at: null,
    created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...overrides,
  };
}

export function buildDiagram(overrides: Partial<ArchitectureDiagram> = {}): ArchitectureDiagram {
  return {
    id: "dgm-1", project_id: PROJECT_ID, unique_code: "DGM-001", name: "Platform overview", purpose: "How traffic reaches the services.",
    scope_element_id: null, scope_element_code: null, scope_element_name: null, connection_detail: false, status: "active",
    version: 3, creator_id: "user-1", is_archived: false, archived_at: null, created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z", placement_count: 3, note_count: 0, toggle_count: 1, ...overrides,
  };
}

export function buildViewNode(overrides: Partial<DiagramViewNode> = {}): DiagramViewNode {
  return {
    placement_id: "pl-1", element_id: "el-1", unique_code: "ELM-001", name: "Gateway", locked: false, shared: false, hidden: false,
    status: "active", parent_id: null, element_type_id: "et-1", element_type_name: "Service", shape: "rounded",
    color_light: "#dbeafe", color_dark: "#1e3a8a", symbol_id: null, ports: [], x: 0, y: 0, width: 160, height: 80,
    collapsed: false, internal_connection_ids: [], ...overrides,
  };
}

export function buildViewEdge(overrides: Partial<DiagramViewEdge> = {}): DiagramViewEdge {
  return {
    id: "edge-1", source_element_id: "el-1", target_element_id: "el-2", two_way: false, indirect: false, rolled_up: false,
    bridged: false, count: 1, type_name: null, line_style: null, color_light: null, color_dark: null, label: null,
    connections: [buildConnection()], hops: [], ...overrides,
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
    ...overrides,
  };
}

/** An element as the diagram model lists it. */
export function buildModelElement(overrides: Partial<ModelElement> = {}): ModelElement {
  return {
    id: "el-1", unique_code: "ELM-001", name: "Gateway", locked: false, shared: false, status: "active", element_type_id: "et-1",
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
    ...overrides,
  };
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
    if (path.endsWith("/records/architecture_element/columns")) return buildRecordColumns({ label: "Elements" });
    if (path.endsWith("/records/architecture_connection/columns")) return buildRecordColumns({ label: "Connections" });
    if (base.endsWith("/modules/architecture/element-types")) return ELEMENT_TYPES;
    if (base.endsWith("/modules/architecture/connection-types")) return CONNECTION_TYPES;
    if (base.endsWith("/modules/architecture/symbols")) return SYMBOLS;
    if (base.includes("/modules/architecture/symbols/") && base.endsWith("/content")) return SYMBOL_SVG;
    if (base.endsWith("/modules/architecture/elements/shared")) return reads.shared ?? [];
    if (base.endsWith("/modules/architecture/elements")) return elements;
    if (base.includes("/modules/architecture/elements/")) return reads.element ?? elements[0];
    if (base.endsWith("/modules/architecture/connections")) return reads.connections ?? [buildConnection()];
    if (base.includes("/modules/architecture/connections/")) return reads.connection ?? buildConnection();
    if (base.endsWith("/modules/architecture/diagrams")) return reads.diagrams ?? [buildDiagram()];
    if (base.includes("/modules/architecture/diagrams/") && base.endsWith("/view")) return reads.diagramView ?? buildDiagramView();
    if (base.includes("/modules/architecture/diagrams/") && base.endsWith("/model")) return reads.diagramModel ?? buildDiagramModel();
    if (base.includes("/modules/architecture/diagrams/")) return (reads.diagramView ?? buildDiagramView()).diagram;
    if (path.endsWith("/records/architecture_diagram/columns")) return buildRecordColumns({ label: "Diagrams" });
    if (base.endsWith("/modules/architecture/collections")) return reads.collections ?? [buildCollection()];
    if (base.includes("/collections/") && base.endsWith("/members")) return [{ element_id: "el-1", unique_code: "ELM-001", name: "Gateway" }];
    if (base.endsWith("/users")) return ORG_USERS;
    if (base.endsWith("/groups")) return [];
    if (base.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: ORG_ID, name: "Platform", code: "PLAT" };
    if (base.endsWith("/api/v1/projects")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}
