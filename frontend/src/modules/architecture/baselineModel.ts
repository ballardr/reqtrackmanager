/**
 * Module: modules/architecture/baselineModel
 *
 * Display helpers for a baseline's content: the label of each field a snapshot or a comparison names, and a value as text.
 * A snapshot is the record's portable bundle entry, so its keys are the bundle's (`type_name`, `parent_code`, `boxes`); the
 * labels here are the words the same fields carry on the record's own screens.
 */

/** The label of each content key a snapshot can hold; a key not listed is shown capitalised with its underscores as spaces. */
const FIELD_LABEL: Record<string, string> = {
  unique_code: "Code",
  name: "Name",
  description: "Description",
  display_note: "Display note",
  type_name: "Type",
  parent_code: "Parent",
  symbol: "Symbol",
  folder: "Folder",
  status: "Status",
  ports: "Ports",
  tags: "Tags",
  placements: "Places",
  protocol: "Protocol",
  source_code: "Source",
  source_port: "Source port",
  source_ref: "Source (other owner)",
  target_code: "Target",
  target_port: "Target port",
  target_ref: "Target (other owner)",
  realises: "Realises",
  purpose: "Purpose",
  scope: "Scope",
  connection_detail: "Connection detail",
  boxes: "Boxes",
  notes: "Notes",
  anchors: "Line ends",
  boundaries: "Boundary boxes",
  toggles: "Switches",
  element: "Element",
  states: "States",
  transitions: "Transitions",
};

/**
 * @param key A content key of a snapshot.
 * @returns Its label.
 */
export function baselineFieldLabel(key: string): string {
  if (FIELD_LABEL[key]) return FIELD_LABEL[key];
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * A snapshot value as text: nothing as a dash, a list as its length, an object as compact JSON.
 *
 * @param value Any JSON value from a snapshot.
 */
export function baselineValueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length === 0 ? "—" : `${value.length}`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Content keys never listed in a record's detail (its code and name are the dialog's own title). */
export const BASELINE_HEADING_KEYS: readonly string[] = ["unique_code", "name"];
