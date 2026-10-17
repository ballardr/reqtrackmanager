import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import { OrgRiskTypesPanel } from "./OrgRiskTypesPanel";
import { ProjectRiskTypesPanel } from "./ProjectRiskTypesPanel";
import { ProjectRisksPage } from "./ProjectRisksPage";
import { RiskDetailPage } from "./RiskDetailPage";
import { RISK_SCORING_SCHEME, RISK_STATUS_LABEL } from "./types";

/**
 * Module: modules/risk_management/module
 *
 * The Risk Management module's frontend registration — the mirror of `backend/app/modules/
 * risk_management/module.py`'s `MODULE_DEFINITION`. `registry.ts`
 * auto-discovers this file; no core file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled-modules list): the
 *   register (`.../risks`, the path the backend `frontend_manifest` nav entry
 *   points at) and a risk's detail page (`.../risks/:riskId`, also the
 *   `artefactPaths` target other records' links follow).
 * - `orgAdminSections`/`projectAdminSections`: the two tiers of the Risk type
 *   vocabulary, and Risk scoring configuration (Likelihood/Consequence/
 *   Detectability levels, default model, rating bands and per-cell ratings)
 *   through core's shared `ScoringSchemeEditor` (org) and `ProjectScoringSettings`
 *   (project), the same way Stakeholders and Pain Points configure theirs.
 * - Notifications about a risk deep-link through `artefactPaths` (the generic
 *   `getNotificationLink`), so there is no per-module case in core.
 *
 * `entityAccentColor` is intentionally not set: no mixed cross-module list shows
 * a risk row yet (a risk's links are shown by the shared Links panel).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "risk_management",
  artefactPaths: {
    risk: (projectId, id) => `/projects/${projectId}/modules/risk_management/risks/${id}`,
  },
  artefactStatusLabels: { risk: RISK_STATUS_LABEL },
  artefactInactiveStatuses: { risk: ["closed", "rejected"] },
  routes: [
    { path: "/projects/:projectId/modules/risk_management/risks", element: createElement(ProjectRisksPage) },
    { path: "/projects/:projectId/modules/risk_management/risks/:riskId", element: createElement(RiskDetailPage) },
  ],
  orgAdminSections: [
    {
      key: "risk-management-types",
      label: "Risk Types",
      render: ({ orgId }) => createElement(OrgRiskTypesPanel, { orgId }),
    },
    {
      key: "risk-management-scoring",
      label: "Risk Scoring",
      render: ({ orgId }) => createElement(ScoringSchemeEditor, { orgId, schemeKey: RISK_SCORING_SCHEME }),
    },
  ],
  projectAdminSections: [
    {
      key: "risk-management-types",
      label: "Risk Types",
      render: ({ projectId }) => createElement(ProjectRiskTypesPanel, { projectId }),
    },
    {
      key: "risk-management-scoring",
      label: "Risk Scoring",
      render: ({ projectId }) => createElement(ProjectScoringSettings, { projectId, schemeKey: RISK_SCORING_SCHEME }),
    },
  ],
};
