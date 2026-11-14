/**
 * Module: modules/architecture/types
 *
 * Frontend vocabulary for the System Architecture module: the wire values of its enums with their display labels.
 * Mirrors `backend/app/modules/architecture/enums.py` and `labels.py` by hand; any place that shows an enum value
 * goes through its label map, never the raw string.
 */

import type { BadgeTone, Principal, PrincipalRef } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";
import type { AttachPoint } from "../../components/graphAttachPoints";

export type ArchitectureRecordStatus = "draft" | "proposed" | "active" | "retired" | "rejected";

export const ARCHITECTURE_STATUS_LABEL: Record<ArchitectureRecordStatus, string> = {
  draft: "Draft",
  proposed: "Proposed",
  active: "Active",
  retired: "Retired",
  rejected: "Rejected",
};

export type PortDirection = "in" | "out" | "both";

/** The colour family of an annotation note on a diagram. */
export type NoteTone = "neutral" | "info" | "success" | "warning" | "danger";

export const NOTE_TONE_LABEL: Record<NoteTone, string> = {
  neutral: "Neutral", info: "Information", success: "Positive", warning: "Caution", danger: "Critical",
};

/** What an annotation's leader line points at. */
export type LeaderKind = "none" | "element" | "connection" | "point";

/** The fields of a note that name what its leader points at, and its arrowhead (mirrors `NoteIn` in `schemas.py`). */
export interface NoteLeader {
  leader_kind: LeaderKind;
  leader_element_id: string | null;
  leader_connection_id: string | null;
  leader_x: number | null;
  leader_y: number | null;
  leader_arrow: boolean;
}

export const PORT_DIRECTION_LABEL: Record<PortDirection, string> = {
  in: "In",
  out: "Out",
  both: "Both",
};

/** The states that mean a record is out of use: hidden by "Open only", not offered as a new end, parent, scope or box, drawn faded. */
export const ARCHITECTURE_INACTIVE_STATUSES: ArchitectureRecordStatus[] = ["retired", "rejected"];

/** Whether a record in `status` is out of use (retired or rejected). */
export function isOutOfUse(status: ArchitectureRecordStatus): boolean {
  return ARCHITECTURE_INACTIVE_STATUSES.includes(status);
}

export const ARCHITECTURE_STATUS_TONE: Record<ArchitectureRecordStatus, BadgeTone> = {
  draft: "muted",
  proposed: "info",
  active: "accent",
  retired: "muted",
  rejected: "danger",
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
  /** The short line drawn inside the element's box on a diagram (the description is never drawn). */
  display_note: string;
  element_type_id: string;
  element_type_name: string;
  symbol_id: string | null;
  effective_symbol_id: string | null;
  parent_id: string | null;
  /** The folder in the owner's tree; null at the top level, and for a shared element (the owner's tree is not disclosed). */
  folder_id: string | null;
  /** The folder's path (`Software/Modules`): only the names on the way to this record, also for a shared element. */
  folder_path: string | null;
  owner: Principal | null;
  status: ArchitectureRecordStatus;
  /** The states the server lets this record move to, in menu order (one map on the server). */
  allowed_status_moves: ArchitectureRecordStatus[];
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
  display_note: string;
  element_type_id: string;
  parent_id: string | null;
  folder_id: string | null;
  owner: PrincipalRef | null;
  symbol_id: string | null;
}

/** Create payload: the shared fields plus what only a new element takes. */
export interface ElementCreateValues extends ElementFieldValues {
  activate: boolean;
  ports: PortValues[];
}

/** A connection named from another connection's page (what it realises, or what realises it). */
export interface ConnectionRef {
  id: string;
  unique_code: string;
  name: string;
  status: ArchitectureRecordStatus;
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
  folder_id: string | null;
  folder_path: string | null;
  status: ArchitectureRecordStatus;
  /** The states the server lets this record move to, in menu order (one map on the server). */
  allowed_status_moves: ArchitectureRecordStatus[];
  version: number;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  /** The outer connections this one realises (it lies inside the interface each declares). */
  realises: ConnectionRef[];
  /** The inner connections that realise this one. */
  realised_by: ConnectionRef[];
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
  folder_id: string | null;
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
  folder_id: string | null;
  folder_path: string | null;
  status: ArchitectureRecordStatus;
  /** The states the server lets this record move to, in menu order (one map on the server). */
  allowed_status_moves: ArchitectureRecordStatus[];
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
  folder_id: string | null;
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
  display_note: string;
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
  /** An element id, or a boundary box's id when `source_is_boundary`. */
  source_element_id: string;
  target_element_id: string;
  source_is_boundary: boolean;
  target_is_boundary: boolean;
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

/** How a boundary box is drawn, from the direction of the outer connection it stands for, seen from inside the scope. */
export type BoundaryShape = "input" | "output" | "bidirectional" | "dot";

/**
 * A boundary box: a scoped diagram's stand-in for one outer connection (the scope, or an element inside it, to an element
 * outside). A `locked` box is one whose outside element the viewer cannot read: codes only, drawn as a dot.
 */
export interface DiagramViewBoundary {
  id: string;
  connection_id: string;
  connection_code: string;
  connection_name: string;
  type_name: string;
  shape: BoundaryShape;
  locked: boolean;
  outside_element_id: string;
  outside_element_code: string;
  outside_element_name: string;
  scope_end_element_id: string;
  scope_end_port_name: string | null;
  covered: boolean;
  realised_by_count: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DiagramNote extends NoteLeader {
  id: string;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: NoteTone;
}

/** A diagram resolved for drawing. */
export interface DiagramView {
  diagram: ArchitectureDiagram;
  toggles: DiagramToggle[];
  nodes: DiagramViewNode[];
  edges: DiagramViewEdge[];
  notes: DiagramNote[];
  anchors: DiagramAnchor[];
  boundaries: DiagramViewBoundary[];
}

/** Where a drawn line meets its two boxes, when a person chose it; an end that is null is automatic. */
export interface DiagramAnchor {
  source_element_id: string;
  target_element_id: string;
  source_point: AttachPoint | null;
  target_point: AttachPoint | null;
}

/** An element as the editor needs it to draw a box and resolve lines; a `locked` one carries its code only. */
export interface ModelElement {
  id: string;
  unique_code: string;
  name: string;
  display_note: string;
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
  /** Which connection realises which (both live), so the editor can join a realising connection to its boundary box. */
  realisations: ModelRealisation[];
}

/** One inner connection realising one outer connection. */
export interface ModelRealisation {
  inner_connection_id: string;
  outer_connection_id: string;
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
export interface NoteValues extends NoteLeader {
  id: string | null;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: NoteTone;
}

/** One boundary box as saved: the outer connection it stands for and its box. */
export interface BoundaryValues {
  connection_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

// --- Folders (mirror the folder schemas in `backend/app/modules/architecture/schemas.py`) ---

/** Which list a folder organises; each kind has its own tree. */
export type FolderKind = "element" | "connection" | "diagram";

/** A folder: a name in a tree that organises one list. Navigation only. */
export interface ArchitectureFolder {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  kind: FolderKind;
  name: string;
  parent_id: string | null;
  sort_order: number;
  /** Names from the top, joined by `/`. */
  path: string;
  /** Records directly in the folder (not in its sub-folders). */
  record_count: number;
}

// --- State machine diagrams (mirror the schemas in `backend/app/modules/architecture/schemas.py`) ---

/** What a state is: an ordinary state, or one of the three markers (the start, an end, a choice). */
export type StateKind = "initial" | "state" | "final" | "choice";

export const STATE_KIND_LABEL: Record<StateKind, string> = {
  initial: "Initial state",
  state: "State",
  final: "Final state",
  choice: "Choice",
};

/** The kinds drawn as a marker (a shape with no text inside) rather than a box. */
export const STATE_MARKER_KINDS: readonly StateKind[] = ["initial", "final", "choice"];

/** How serious a modelling finding is: an error blocks activation, a warning never does. */
export type FindingSeverity = "error" | "warning";

export const FINDING_SEVERITY_LABEL: Record<FindingSeverity, string> = { error: "Error", warning: "Warning" };

/** Which kind of diagram a Diagrams-tab row is. */
export type DiagramKind = "block" | "state_machine";

export const DIAGRAM_KIND_LABEL: Record<DiagramKind, string> = { block: "Block diagram", state_machine: "State machine diagram" };

/** A state machine diagram with its counts. The element's name is blank when the viewer cannot read it. */
export interface StateMachineDiagram extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  name: string;
  description: string;
  element_id: string;
  element_code: string | null;
  element_name: string | null;
  status: ArchitectureRecordStatus;
  allowed_status_moves: ArchitectureRecordStatus[];
  version: number;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  state_count: number;
  transition_count: number;
  error_count: number;
  warning_count: number;
}

/** The fields the state machine diagram create and edit forms share. */
export interface StateMachineFieldValues {
  name: string;
  description: string;
  element_id: string;
}

/** Create payload: the shared fields plus Save and activate. */
export interface StateMachineCreateValues extends StateMachineFieldValues {
  activate: boolean;
}

/** A state (or marker) with the diagram and element it belongs to. */
export interface ArchitectureState extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  state_machine_diagram_id: string;
  state_machine_diagram_code: string;
  state_machine_diagram_name: string;
  state_machine_diagram_version: number;
  element_id: string;
  element_code: string | null;
  element_name: string | null;
  name: string;
  description: string;
  kind: StateKind;
  parent_state_id: string | null;
  parent_state_code: string | null;
  entry_action: string;
  exit_action: string;
  activity: string;
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
  status: ArchitectureRecordStatus;
  is_archived: boolean;
  creator_id: string;
  created_at: string;
  updated_at: string;
}

/** The fields the state form edits (a state's drawing is edited on the canvas). */
export interface StateFieldValues {
  name: string;
  description: string;
  kind: StateKind;
  entry_action: string;
  exit_action: string;
  activity: string;
}

/** A transition with the codes of its two states and the diagram's version after the change. */
export interface StateTransition {
  id: string;
  state_machine_diagram_id: string;
  state_machine_diagram_version: number;
  source_state_id: string;
  source_state_code: string;
  target_state_id: string;
  target_state_code: string;
  event: string;
  guard: string;
  action: string;
  description: string;
  sort_order: number;
  source_point: AttachPoint | null;
  target_point: AttachPoint | null;
}

/** The fields the transition form edits. */
export interface TransitionFieldValues {
  source_state_id: string;
  target_state_id: string;
  event: string;
  guard: string;
  action: string;
  description: string;
}

/** One modelling finding; `subject` is the code of the state or transition it concerns (empty for the whole diagram). */
export interface StateMachineFinding {
  severity: FindingSeverity;
  code: string;
  subject: string;
  message: string;
}

/** A state machine diagram with everything it holds, as the editor and the outline read it. */
export interface StateMachineModel {
  diagram: StateMachineDiagram;
  states: ArchitectureState[];
  transitions: StateTransition[];
  findings: StateMachineFinding[];
}

/** One state's box and nesting as saved. */
export interface StateLayoutValues {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  collapsed: boolean;
  parent_state_id: string | null;
}

/** One transition's attach points as saved (`null` is automatic). */
export interface TransitionPointsValues {
  id: string;
  source_point: AttachPoint | null;
  target_point: AttachPoint | null;
}

/** A requirement as the allocation panels name it. */
export interface AllocationRequirement {
  id: string;
  unique_code: string;
  name: string;
  status: string;
}

/** An element as the allocation panels name it; `organization_id` is set for an organisation-owned one. */
export interface AllocationElement {
  id: string;
  unique_code: string;
  name: string;
  status: ArchitectureRecordStatus;
  project_id: string | null;
  organization_id: string | null;
}

/** One requirement and one element; `link_id` is the allocation link when the pair is allocated. */
export interface AllocationPair {
  requirement: AllocationRequirement;
  element: AllocationElement;
  link_id: string | null;
}

/** What a requirement's Architecture panel or an element's Requirements card shows. */
export interface AllocationView {
  allocated: AllocationPair[];
  suggested: AllocationPair[];
  dismissed: AllocationPair[];
  can_manage: boolean;
}

/** The result of accepting suggestions: how many became links and which pairs did not, with the reason. */
export interface AllocationAcceptResult {
  accepted: number;
  failed: { requirement_id: string; element_id: string; reason: string }[];
}

/** The project's allocation counts. */
export interface AllocationCoverage {
  requirements: number;
  allocated_requirements: number;
  elements: number;
  allocated_elements: number;
  suggestions: number;
}
