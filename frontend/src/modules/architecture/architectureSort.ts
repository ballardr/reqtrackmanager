/**
 * Module: modules/architecture/architectureSort
 *
 * The sortable value of each sortable column on the Elements, Connections and Diagrams lists, for `sortRows`. The lists
 * load their whole filtered set in one request, so the order is applied in the browser; the keys are the column keys and
 * the sort lives in the URL (`useUrlSort`). A column with no natural order (none here) stays unsortable.
 */
import type { SortValue } from "../../utils/sortRows";
import {
  ARCHITECTURE_STATUS_LABEL, DIAGRAM_KIND_LABEL, STATE_KIND_LABEL, type ArchitectureConnection, type ArchitectureDiagram,
  type ArchitectureElement, type ArchitectureState, type DiagramKind, type StateMachineDiagram,
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

/** One row of the merged Diagrams list: a block diagram or a state machine diagram, with the values the columns show. */
export type DiagramListRow =
  | { kind: "block"; id: string; source: ArchitectureDiagram }
  | { kind: "state_machine"; id: string; source: StateMachineDiagram };

/** The registered artefact type of each diagram type (the record type its Export, Import and Components column address). */
export const DIAGRAM_KIND_ARTEFACT_TYPE: Record<DiagramKind, string> = {
  block: "architecture_diagram", state_machine: "architecture_state_machine_diagram",
};

/** @param row A list row. @returns The code, name and status common to both types. */
const common = (row: DiagramListRow) => row.source;

/** The text of the Element column: a block diagram's scope element (empty for the system context), a state machine diagram's element. */
export function rowElementText(row: DiagramListRow): string {
  if (row.kind === "block") return row.source.scope_element_id ? `${row.source.scope_element_code ?? ""} ${row.source.scope_element_name ?? ""}`.trim() : "";
  return `${row.source.element_code ?? ""} ${row.source.element_name ?? ""}`.trim();
}

/** The count the Contents column shows: a block diagram's elements, a state machine diagram's states. */
export const rowContents = (row: DiagramListRow): number => (row.kind === "block" ? row.source.placement_count : row.source.state_count);

/** Sortable columns of the merged Diagrams list. */
export const DIAGRAM_ROW_SORT_VALUES: Values<DiagramListRow> = {
  code: (r) => common(r).unique_code,
  name: (r) => common(r).name,
  type: (r) => DIAGRAM_KIND_LABEL[r.kind satisfies DiagramKind],
  folder: (r) => (r.kind === "block" ? r.source.folder_path : null),
  scope: rowElementText,
  boxes: rowContents,
  toggles: (r) => (r.kind === "block" ? r.source.toggle_count : null),
  status: (r) => ARCHITECTURE_STATUS_LABEL[common(r).status],
};

/** Sortable columns of the project-wide States list. */
export const STATE_SORT_VALUES: Values<ArchitectureState> = {
  code: (s) => s.unique_code,
  name: (s) => s.name,
  diagram: (s) => `${s.state_machine_diagram_code} ${s.state_machine_diagram_name}`,
  kind: (s) => STATE_KIND_LABEL[s.kind],
  element: (s) => `${s.element_code ?? ""} ${s.element_name ?? ""}`.trim(),
};

export const ELEMENT_SORT_KEYS = ["code", "name", "type", "folder", "parent", "owner", "connections", "status"] as const;
export const CONNECTION_SORT_KEYS = ["code", "name", "type", "folder", "source", "target", "protocol", "status"] as const;
export const DIAGRAM_SORT_KEYS = ["code", "name", "type", "folder", "scope", "boxes", "toggles", "status"] as const;
export const STATE_SORT_KEYS = ["code", "name", "diagram", "kind", "element"] as const;
