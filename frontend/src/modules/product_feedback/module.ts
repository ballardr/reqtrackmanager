import type { TierAModuleDefinition } from "../types";
import { REQUEST_STATUS_LABEL } from "./types";

/**
 * Module: modules/product_feedback/module
 *
 * The Product Feedback module's frontend registration — the frontend mirror of `backend/app/modules/
 * product_feedback/module.py`'s `MODULE_DEFINITION`, same single-`moduleDefinition`-export convention every other
 * Tier A module uses. `frontend/src/modules/registry.ts` auto-discovers this file.
 *
 * `artefactPaths` / `orgArtefactPaths` / `artefactListPaths`: where a request, an inbox request and the project's
 * request list live, so links, notifications and search hits resolve without core naming this module. The pages
 * themselves are added with the module's UI; until then the module has no `routes` and the backend declares no
 * nav entry.
 *
 * `artefactInactiveStatuses`: a declined or duplicate request is greyed out in shared lists.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "product_feedback",
  artefactPaths: {
    enhancement_request: (projectId, id) => `/projects/${projectId}/modules/product_feedback/requests/${id}`,
  },
  artefactListPaths: {
    enhancement_request: (projectId) => `/projects/${projectId}/modules/product_feedback/requests`,
  },
  orgArtefactPaths: {
    enhancement_request: (orgId, id) => `/orgs/${orgId}/modules/product_feedback/requests/${id}`,
  },
  artefactStatusLabels: { enhancement_request: REQUEST_STATUS_LABEL },
  artefactInactiveStatuses: { enhancement_request: ["declined", "duplicate"] },
  routes: [],
};
