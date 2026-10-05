/**
 * Module: modules/artefactPaths
 *
 * Resolves the detail-page route of a record from its artefact type, so one
 * module's UI (Stakeholders' relationship list) can link to another's records
 * (a Pain Point, a Decision) without importing that module or hardcoding its
 * URLs. Two sources, merged like `entityAccentColor.ts`: the one core-owned
 * type (`requirement`), and every installed module's own
 * `TierAModuleDefinition.artefactPaths`.
 */
import { installedModules } from "./registry";

/** The detail route of a record of `artefactType` in `projectId`, or `null`
 * when no installed module (and not core) can say where it lives. */
export function getArtefactPath(artefactType: string, projectId: string, id: string): string | null {
  if (artefactType === "requirement") return `/projects/${projectId}/requirements/${id}`;
  for (const module of installedModules) {
    const path = module.artefactPaths?.[artefactType];
    if (path) return path(projectId, id);
  }
  return null;
}
