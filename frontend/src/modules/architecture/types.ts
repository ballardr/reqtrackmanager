/**
 * Module: modules/architecture/types
 *
 * Frontend vocabulary for the System Architecture module: the wire values of its enums with their display labels.
 * Mirrors `backend/app/modules/architecture/enums.py` and `labels.py` by hand; any place that shows an enum value
 * goes through its label map, never the raw string.
 */

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
