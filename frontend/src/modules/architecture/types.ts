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
}

export interface ConnectionType extends VocabularyRow {
  line_style: LineStyle;
  directional: boolean;
}

/** The writable fields of an element type (`symbol_id: null` clears the symbol). */
export interface ElementTypeValues {
  name: string;
  domain: Domain;
  shape: ElementShape;
  color_light: string | null;
  color_dark: string | null;
  symbol_id: string | null;
}

export interface ConnectionTypeValues {
  name: string;
  domain: Domain;
  line_style: LineStyle;
  directional: boolean;
  color_light: string | null;
  color_dark: string | null;
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
