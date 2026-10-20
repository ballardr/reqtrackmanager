/**
 * Module: modules/artefactPaths
 *
 * Resolves the page of a record from its artefact type, so one module's UI
 * (the links panel, Stakeholders' relationship list) can link to another's
 * records (a Pain Point, a Decision) without importing that module or
 * hardcoding its URLs. Two sources, merged like `entityAccentColor.ts`: the
 * core-owned types (`requirement`, `requirement_action`, `change_request`), and every installed
 * module's own `TierAModuleDefinition.artefactPaths`. Every artefact type the
 * backend registers must resolve here, or it could be linked yet unreachable
 * (`artefactPaths.stories.tsx` guards this).
 */
import {
  CHANGE_REQUEST_STATUS_LABEL, notificationLink, REQUIREMENT_ACTION_OUTCOME_LABEL, REQUIREMENT_STATUS_LABEL,
  type Notification,
} from "../api/types";
import { installedModules } from "./registry";

/** The detail route a module declares for `artefactType` in `projectId`, or `null` when none does. */
function getModuleArtefactPath(artefactType: string, projectId: string, id: string): string | null {
  for (const module of installedModules) {
    const path = module.artefactPaths?.[artefactType];
    if (path) return path(projectId, id);
  }
  return null;
}

/** The detail route of a record of `artefactType` in `projectId`, or `null`
 * when no installed module (and not core) can say where it lives. */
export function getArtefactPath(artefactType: string, projectId: string, id: string): string | null {
  if (artefactType === "requirement") return `/projects/${projectId}/requirements/${id}`;
  if (artefactType === "requirement_action") return `/projects/${projectId}/actions/${id}`;
  if (artefactType === "change_request") return `/projects/${projectId}/change-requests/${id}`;
  return getModuleArtefactPath(artefactType, projectId, id);
}

/**
 * Where a global-search result opens: a project's own page, or the page of the record the server
 * says to open (`open_*`: a research finding opens its engagement) in the project it was found through, or
 * at its organisation page for an organisation-owned record found without one. `null` when no installed
 * module can say where that record lives.
 */
export function getSearchHitPath(hit: {
  open_type: string;
  open_id: string;
  open_project_id: string | null;
  organization_id?: string | null;
}): string | null {
  if (hit.open_type === "project") return `/projects/${hit.open_id}`;
  if (hit.open_project_id) return getArtefactPath(hit.open_type, hit.open_project_id, hit.open_id);
  // An organisation-owned record found without a project opens at its organisation-level page.
  if (hit.organization_id) {
    for (const module of installedModules) {
      const path = module.orgArtefactPaths?.[hit.open_type];
      if (path) return path(hit.organization_id, hit.open_id);
    }
  }
  return null;
}

/**
 * Where clicking a notification navigates: a notification about a record a module owns (its
 * `entity_type` is that module's registered artefact type) opens that record's page via the
 * module's `artefactPaths`; anything else keeps the core resolution (`notificationLink`).
 * `null` means the notification is not navigable.
 */
export function getNotificationLink(n: Notification): string | null {
  if (n.project_id && n.entity_type && n.entity_id) {
    const modulePath = getModuleArtefactPath(n.entity_type, n.project_id, n.entity_id);
    if (modulePath) return modulePath;
  }
  return notificationLink(n);
}

const CORE_STATUS_LABELS: Record<string, Record<string, string>> = {
  requirement: REQUIREMENT_STATUS_LABEL,
  requirement_action: REQUIREMENT_ACTION_OUTCOME_LABEL,
  change_request: CHANGE_REQUEST_STATUS_LABEL,
};

/** The display label of a record's status, or `null` when no label map is registered
 * for it (core's own types, then every installed module's `artefactStatusLabels`) —
 * callers show no status rather than the raw backend string. */
export function getArtefactStatusLabel(artefactType: string, status: string | null): string | null {
  if (status === null) return null;
  const core = CORE_STATUS_LABELS[artefactType]?.[status];
  if (core) return core;
  for (const module of installedModules) {
    const label = module.artefactStatusLabels?.[artefactType]?.[status];
    if (label) return label;
  }
  return null;
}

/** Core statuses that mean a record is no longer live (modules declare theirs on
 * `TierAModuleDefinition.artefactInactiveStatuses`). */
const CORE_INACTIVE_STATUSES: Record<string, string[]> = {
  requirement: ["archived"],
  change_request: ["rejected", "withdrawn"],
};

/**
 * Whether a record is no longer live: archived, or in a status its owning module (or core)
 * declares inactive (superseded, retired, rejected, withdrawn…).
 *
 * @param artefactType The record's registered artefact type.
 * @param status The record's status, if it has one.
 * @param isArchived The record's archived flag.
 */
export function isArtefactInactive(artefactType: string, status: string | null, isArchived: boolean): boolean {
  if (isArchived) return true;
  if (status === null) return false;
  if (CORE_INACTIVE_STATUSES[artefactType]?.includes(status)) return true;
  return installedModules.some((module) => module.artefactInactiveStatuses?.[artefactType]?.includes(status));
}
