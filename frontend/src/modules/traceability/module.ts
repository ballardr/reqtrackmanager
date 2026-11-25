import type { TierAModuleDefinition } from "../types";

/**
 * Module: modules/traceability/module
 *
 * The Traceability & Governance module's frontend registration, the mirror of
 * `backend/app/modules/traceability/module.py`'s `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` discovers this
 * file.
 *
 * The module contributes no route, section or navigation entry yet; each part adds its own to this definition. Its
 * sub-component switches appear in the organisation and project Modules lists, which are generic over every module.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "traceability",
};
