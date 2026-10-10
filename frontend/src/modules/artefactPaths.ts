/**
 * Module: modules/artefactPaths
 *
 * Resolves the page of a record from its artefact type, so one module's UI
 * (the links panel, Stakeholders' relationship list) can link to another's
 * records (a Pain Point, a Decision) without importing that module or
 * hardcoding its URLs. Two sources, merged like `entityAccentColor.ts`: the
 * core-owned types (`requirement`, `requirement_action`), and every installed
 * module's own `TierAModuleDefinition.artefactPaths`. Every artefact type the
 * backend registers must resolve here, or it could be linked yet unreachable
 * (`artefactPaths.stories.tsx` guards this).
 */
import { REQUIREMENT_ACTION_OUTCOME_LABEL, REQUIREMENT_STATUS_LABEL } from "../api/types";
import { installedModules } from "./registry";

/** The detail route of a record of `artefactType` in `projectId`, or `null`
 * when no installed module (and not core) can say where it lives. */
export function getArtefactPath(artefactType: string, projectId: string, id: string): string | null {
  if (artefactType === "requirement") return `/projects/${projectId}/requirements/${id}`;
  if (artefactType === "requirement_action") return `/projects/${projectId}/actions/${id}`;
  for (const module of installedModules) {
    const path = module.artefactPaths?.[artefactType];
    if (path) return path(projectId, id);
  }
  return null;
}

const CORE_STATUS_LABELS: Record<string, Record<string, string>> = {
  requirement: REQUIREMENT_STATUS_LABEL,
  requirement_action: REQUIREMENT_ACTION_OUTCOME_LABEL,
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
