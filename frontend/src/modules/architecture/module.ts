import type { TierAModuleDefinition } from "../types";
import { ARCHITECTURE_STATUS_LABEL } from "./types";

/**
 * Module: modules/architecture/module
 *
 * The System Architecture module's frontend registration, the mirror of `backend/app/modules/architecture/
 * module.py`'s `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` auto-discovers this file.
 *
 * `artefactPaths` / `artefactListPaths`: where an element, a connection and their lists live, so links,
 * notifications and search hits resolve without core naming this module.
 * `artefactStatusLabels` / `artefactInactiveStatuses`: a retired record is greyed out in shared lists.
 *
 * The pages these paths open are added with the element and connection screens; until then the module has no
 * `routes`, navigation entry or admin section.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "architecture",
  artefactPaths: {
    architecture_element: (projectId, id) => `/projects/${projectId}/modules/architecture/elements/${id}`,
    architecture_connection: (projectId, id) => `/projects/${projectId}/modules/architecture/connections/${id}`,
  },
  artefactListPaths: {
    architecture_element: (projectId) => `/projects/${projectId}/modules/architecture/elements`,
    architecture_connection: (projectId) => `/projects/${projectId}/modules/architecture/connections`,
  },
  artefactStatusLabels: {
    architecture_element: ARCHITECTURE_STATUS_LABEL,
    architecture_connection: ARCHITECTURE_STATUS_LABEL,
  },
  artefactInactiveStatuses: {
    architecture_element: ["retired"],
    architecture_connection: ["retired"],
  },
};
