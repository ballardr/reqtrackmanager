import type { TierAModuleDefinition } from "../types";
import { RISK_STATUS_LABEL } from "./types";

/**
 * Module: modules/risk_management/module
 *
 * The Risk Management module's frontend registration (docs/plans/module-03-
 * risk-management-plan.md) — the frontend mirror of `backend/app/modules/
 * risk_management/module.py`'s `MODULE_DEFINITION`. `registry.ts`
 * auto-discovers this file.
 *
 * Phase 1 is backend-only, so this registers only what the shared artefact
 * helpers need to describe a Risk: where a risk lives, its status labels, and
 * which statuses count as no longer live. Phase 5 adds the routes, nav entry
 * and admin sections; the `artefactPaths` route below is the one Phase 5's
 * detail page must serve, and nothing can link to a Risk before then (the
 * backend registers no summary provider for it until Phase 3).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "risk_management",
  artefactPaths: {
    risk: (projectId, id) => `/projects/${projectId}/modules/risk_management/risks/${id}`,
  },
  artefactStatusLabels: { risk: RISK_STATUS_LABEL },
  artefactInactiveStatuses: { risk: ["closed", "rejected"] },
};
