/**
 * Module: modules/architecture/architectureSort
 *
 * The sortable value of each sortable column on the Elements, Connections and Diagrams lists, for `sortRows`. The lists
 * load their whole filtered set in one request, so the order is applied in the browser; the keys are the column keys and
 * the sort lives in the URL (`useUrlSort`). A column with no natural order (none here) stays unsortable.
 */
import type { SortValue } from "../../utils/sortRows";
import {
  ARCHITECTURE_STATUS_LABEL, type ArchitectureConnection, type ArchitectureDiagram, type ArchitectureElement,
} from "./types";

type Values<Row> = Record<string, (row: Row) => SortValue>;

/** Text of a connection end as the list shows it: code, then name when readable. */
function endText(connection: ArchitectureConnection, end: "source" | "target"): string {
  const locked = end === "source" ? connection.source_locked : connection.target_locked;
  const code = end === "source" ? connection.source_element_code : connection.target_element_code;
  const name = end === "source" ? connection.source_element_name : connection.target_element_name;
  return locked ? code : `${code} ${name}`;
}

/** Sortable columns of the Elements list; `parentName` resolves an element's parent for the Parent column. */
export function elementSortValues(parentName: (e: ArchitectureElement) => string): Values<ArchitectureElement> {
  return {
    code: (e) => e.unique_code,
    name: (e) => e.name,
    type: (e) => e.element_type_name,
    folder: (e) => e.folder_path,
    parent: (e) => parentName(e) || null,
    owner: (e) => e.owner?.label ?? null,
    connections: (e) => e.connection_count,
    status: (e) => ARCHITECTURE_STATUS_LABEL[e.status],
  };
}

/** Sortable columns of the Connections list. */
export const CONNECTION_SORT_VALUES: Values<ArchitectureConnection> = {
  code: (c) => c.unique_code,
  name: (c) => c.name || null,
  type: (c) => c.connection_type_name,
  folder: (c) => c.folder_path,
  source: (c) => endText(c, "source"),
  target: (c) => endText(c, "target"),
  protocol: (c) => c.protocol || null,
  status: (c) => ARCHITECTURE_STATUS_LABEL[c.status],
};

/** Sortable columns of the Diagrams list; a diagram with no scope element is the system context and sorts first. */
export const DIAGRAM_SORT_VALUES: Values<ArchitectureDiagram> = {
  code: (d) => d.unique_code,
  name: (d) => d.name,
  folder: (d) => d.folder_path,
  scope: (d) => (d.scope_element_id ? `${d.scope_element_code ?? ""} ${d.scope_element_name ?? ""}`.trim() : ""),
  boxes: (d) => d.placement_count,
  toggles: (d) => d.toggle_count,
  status: (d) => ARCHITECTURE_STATUS_LABEL[d.status],
};

export const ELEMENT_SORT_KEYS = ["code", "name", "type", "folder", "parent", "owner", "connections", "status"] as const;
export const CONNECTION_SORT_KEYS = ["code", "name", "type", "folder", "source", "target", "protocol", "status"] as const;
export const DIAGRAM_SORT_KEYS = ["code", "name", "folder", "scope", "boxes", "toggles", "status"] as const;
