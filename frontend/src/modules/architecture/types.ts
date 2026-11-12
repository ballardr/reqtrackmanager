/**
 * Module: modules/architecture/types
 *
 * Frontend vocabulary for the System Architecture module: the wire values of its enums with their display labels.
 * Mirrors `backend/app/modules/architecture/enums.py` and `labels.py` by hand; any place that shows an enum value
 * goes through its label map, never the raw string.
 */

import type { BadgeTone, Principal, PrincipalRef } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";

export type ArchitectureRecordStatus = "draft" | "active" | "retired";

export const ARCHITECTURE_STATUS_LABEL: Record<ArchitectureRecordStatus, string> = {
  draft: "Draft",
  active: "Active",
  retired: "Retired",
};

export type PortDirection = "in" | "out" | "both";

export const PORT_DIRECTION_LABEL: Record<PortDirection, string> = {
  in: "In",
  out: "Out",
  both: "Both",
};

export const ARCHITECTURE_STATUS_TONE: Record<ArchitectureRecordStatus, BadgeTone> = {
  draft: "muted",
  active: "accent",
  retired: "muted",
};

export type Domain = "software" | "hardware" | "any";

export const DOMAIN_LABEL: Record<Domain, string> = {
  software: "Software",
  hardware: "Hardware",
  any: "Software and hardware",
};

export type ElementShape =
  | "rectangle" | "rounded" | "cylinder" | "hexagon" | "ellipse" | "parallelogram" | "folder" | "chip";

export const ELEMENT_SHAPE_LABEL: Record<ElementShape, string> = {
  rectangle: "Rectangle",
  rounded: "Rounded rectangle",
  cylinder: "Cylinder",
  hexagon: "Hexagon",
  ellipse: "Ellipse",
  parallelogram: "Parallelogram",
  folder: "Folder",
  chip: "Chip",
};

export type LineStyle = "solid" | "dashed" | "dotted";

export const LINE_STYLE_LABEL: Record<LineStyle, string> = {
  solid: "Solid",
  dashed: "Dashed",
  dotted: "Dotted",
};

// --- Response and request shapes (mirror `backend/app/modules/architecture/schemas.py`) ---

/** A vocabulary row. Exactly one of `project_id` and `organization_id` is set (its owner). */
interface VocabularyRow {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  name: string;
  domain: Domain;
  color_light: string | null;
  color_dark: string | null;
  sort_order: number;
}

export interface ElementType extends VocabularyRow {
  shape: ElementShape;
  symbol_id: string | null;
  /** The connection types a connection picker lists first when an element of this type is at an end (guidance only). */
  suggested_connection_type_ids: string[];
}

export interface ConnectionType extends VocabularyRow {
  line_style: LineStyle;
  directional: boolean;
  /** The types this one sits under (empty for a root); a type may have several parents, to any depth. */
  parent_ids: string[];
}

/** The writable fields of an element type (`symbol_id: null` clears the symbol). */
export interface ElementTypeValues {
  name: string;
  domain: Domain;
  shape: ElementShape;
  color_light: string | null;
  color_dark: string | null;
  symbol_id: string | null;
  /** The suggested connection types; an empty list clears them. */
  suggested_connection_type_ids: string[];
}

export interface ConnectionTypeValues {
  name: string;
  domain: Domain;
  line_style: LineStyle;
  directional: boolean;
  color_light: string | null;
  color_dark: string | null;
  /** The types this one sits under; an empty list makes it a root. */
  parent_ids: string[];
}

/** A symbol library entry; its drawing is read from `.../symbols/{id}/content`. */
export interface ArchitectureSymbol {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  name: string;
  builtin_key: string | null;
  is_builtin: boolean;
  sort_order: number;
}

/** A project type hidden from an organisation default (`.../hidden`). */
export type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";

export interface Port {
  id: string;
  element_id: string;
  name: string;
  direction: PortDirection;
  connection_type_id: string | null;
  connection_type_name: string | null;
  sort_order: number;
}

export interface PortValues {
  name: string;
  direction: PortDirection;
  connection_type_id: string | null;
}

export interface ArchitectureElement extends ProjectScopedRow {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  /** True when the element is shown in a project that does not own it (read-only there). */
  shared: boolean;
  unique_code: string;
  name: string;
  description: string;
  element_type_id: string;
  element_type_name: string;
  symbol_id: string | null;
  effective_symbol_id: string | null;
  parent_id: string | null;
  owner: Principal | null;
  status: ArchitectureRecordStatus;
  version: number;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  child_count: number;
  connection_count: number;
  ports: Port[];
}

/** The fields the element create and edit forms share. */
export interface ElementFieldValues {
  name: string;
  description: string;
  element_type_id: string;
  parent_id: string | null;
  owner: PrincipalRef | null;
  symbol_id: string | null;
}

/** Create payload: the shared fields plus what only a new element takes. */
export interface ElementCreateValues extends ElementFieldValues {
  activate: boolean;
  ports: PortValues[];
}

export interface ArchitectureConnection extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  name: string;
  connection_type_id: string;
  connection_type_name: string;
  directional: boolean;
  source_element_id: string;
  source_element_code: string;
  source_element_name: string;
  source_port_id: string | null;
  source_port_name: string | null;
  source_locked: boolean;
  source_shared: boolean;
  target_element_id: string;
  target_element_code: string;
  target_element_name: string;
  target_port_id: string | null;
  target_port_name: string | null;
  target_locked: boolean;
  target_shared: boolean;
  protocol: string;
  description: string;
  status: ArchitectureRecordStatus;
  version: number;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

/** The fields the connection create and edit forms share. */
export interface ConnectionFieldValues {
  name: string;
  connection_type_id: string;
  source_element_id: string;
  source_port_id: string | null;
  target_element_id: string;
  target_port_id: string | null;
  protocol: string;
  description: string;
}

export interface ConnectionCreateValues extends ConnectionFieldValues {
  activate: boolean;
}

export interface CollectionGrant {
  id: string;
  project_id: string | null;
  project_name: string | null;
  project_code: string | null;
  group: Principal | null;
  include_descendants: boolean;
  created_at: string;
}

export interface CollectionMember {
  element_id: string;
  unique_code: string;
  name: string;
}

export interface ArchitectureCollection {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  name: string;
  description: string;
  member_count: number;
  grant_count: number;
  grants: CollectionGrant[];
  created_at: string;
  updated_at: string;
}

/** Who a grant reaches: a project (optionally with its descendants) or a group. */
export interface CollectionGrantValues {
  project_id: string | null;
  group: PrincipalRef | null;
  include_descendants: boolean;
}

// --- Diagrams (mirror the diagram schemas in `backend/app/modules/architecture/schemas.py`) ---

/** A diagram record with its counts. The scope element's name is blank when the viewer cannot read it. */
export interface ArchitectureDiagram extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  name: string;
  purpose: string;
  scope_element_id: string | null;
  scope_element_code: string | null;
  scope_element_name: string | null;
  connection_detail: boolean;
  status: ArchitectureRecordStatus;
  version: number;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  placement_count: number;
  note_count: number;
  toggle_count: number;
}

/** The fields the diagram create and edit forms share. */
export interface DiagramFieldValues {
  name: string;
  purpose: string;
  scope_element_id: string | null;
  connection_detail: boolean;
}

/** Create payload: the shared fields plus what only a new diagram takes. */
export interface DiagramCreateValues extends DiagramFieldValues {
  activate: boolean;
  populate: boolean;
}

/** What a toggle matches besides its manual members. */
export interface DiagramToggleRule {
  element_type_ids: string[];
  connection_type_ids: string[];
  domains: Domain[];
  tags: string[];
}

/** A toggle as the view returns it; `on` is its state in this view. */
export interface DiagramToggle {
  id: string;
  name: string;
  default_on: boolean;
  on: boolean;
  rule: DiagramToggleRule;
  element_ids: string[];
  connection_ids: string[];
  sort_order: number;
}

/** A toggle as saved (`id` keeps an existing one). */
export interface DiagramToggleValues {
  id: string | null;
  name: string;
  default_on: boolean;
  rule: DiagramToggleRule;
  element_ids: string[];
  connection_ids: string[];
}

export interface DiagramViewPort {
  id: string;
  name: string;
  direction: PortDirection;
  connection_type_name: string | null;
}

/** A placed element as drawn. A `locked` node is one the viewer can no longer read (its code only). */
export interface DiagramViewNode {
  placement_id: string;
  element_id: string;
  unique_code: string;
  name: string;
  locked: boolean;
  shared: boolean;
  hidden: boolean;
  status: ArchitectureRecordStatus;
  parent_id: string | null;
  element_type_id: string | null;
  element_type_name: string;
  shape: ElementShape;
  color_light: string | null;
  color_dark: string | null;
  symbol_id: string | null;
  ports: DiagramViewPort[];
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
  internal_connection_ids: string[];
}

/** A hidden element a bridged line passes through. */
export interface DiagramViewHop {
  element_id: string;
  unique_code: string;
  name: string;
}

/** A line between two placed elements and the connections behind it. */
export interface DiagramViewEdge {
  id: string;
  source_element_id: string;
  target_element_id: string;
  two_way: boolean;
  indirect: boolean;
  rolled_up: boolean;
  bridged: boolean;
  count: number;
  type_name: string | null;
  line_style: LineStyle | null;
  color_light: string | null;
  color_dark: string | null;
  label: string | null;
  connections: ArchitectureConnection[];
  hops: DiagramViewHop[];
}

export interface DiagramNote {
  id: string;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A diagram resolved for drawing. */
export interface DiagramView {
  diagram: ArchitectureDiagram;
  toggles: DiagramToggle[];
  nodes: DiagramViewNode[];
  edges: DiagramViewEdge[];
  notes: DiagramNote[];
}

/** An element as the editor needs it to draw a box and resolve lines; a `locked` one carries its code only. */
export interface ModelElement {
  id: string;
  unique_code: string;
  name: string;
  locked: boolean;
  shared: boolean;
  status: ArchitectureRecordStatus;
  element_type_id: string | null;
  element_type_name: string;
  color_light: string | null;
  color_dark: string | null;
  symbol_id: string | null;
}

/** A connection type's drawing attributes. */
export interface ModelConnectionType {
  id: string;
  name: string;
  directional: boolean;
  line_style: LineStyle;
  color_light: string | null;
  color_dark: string | null;
}

/** What one view switch hides when it is off: its manual members plus whatever its rule matches. */
export interface ModelToggleMembers {
  toggle_id: string;
  element_ids: string[];
  connection_ids: string[];
}

/** The model data a diagram's lines are resolved from in the browser (`GET .../diagrams/{id}/model`). */
export interface DiagramModel {
  elements: ModelElement[];
  /** Every element listed, connection end and ancestor of one, mapped to its parent (a root to null). */
  parents: Record<string, string | null>;
  connections: ArchitectureConnection[];
  connection_types: ModelConnectionType[];
  toggle_members: ModelToggleMembers[];
}

/** One box as saved. */
export interface PlacementValues {
  element_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
}

/** One note as saved (`id` keeps an existing note; none creates one). */
export interface NoteValues {
  id: string | null;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
}
