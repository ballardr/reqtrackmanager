import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { DECISION_STATUS_LABEL } from "./types";
import { DecisionDetailPage } from "./DecisionDetailPage";
import { DecisionTemplatesPanel } from "./DecisionTemplatesPanel";
import { DecisionTypesPanel } from "./DecisionTypesPanel";
import { ProjectDecisionsPage } from "./ProjectDecisionsPage";

/**
 * Module: modules/decisions/module
 *
 * The Decision Management module's frontend registration — the frontend mirror of `backend/app/modules/decisions/
 * module.py`'s `MODULE_DEFINITION`, same single-`moduleDefinition`-export
 * convention every other Tier A module uses. `frontend/src/modules/
 * registry.ts` auto-discovers this file; no hand-edit to that file is
 * needed.
 *
 * `routes`: `ProjectDecisionsPage` (the list) and `DecisionDetailPage` (a
 * single Decision's full management/context view) — `path`
 * matches the `nav_path` `module.py`'s own `frontend_manifest` declares
 * (with React Router's `:projectId`/`:decisionId` syntax standing in for
 * the backend's `"{project_id}"`/`"{decision_id}"` placeholders).
 * `ProjectDecisionsPage`'s own list opens a minimal `DecisionQuickViewPanel`
 * `SidePanel` on row click (not a route of its own — it renders inline from
 * that page), whose "View full details" link is what reaches
 * `DecisionDetailPage`. See that page's own docstring and `docs/ux-style-
 * guide.md`'s "Pattern: entity detail panel" checklist for why the
 * original single-route, `SidePanel`-only shape (`DecisionDetailPanel`,
 * removed) was replaced.
 *
 * `projectAdminSections`: `DecisionTypesPanel`, this project's
 * Decision Type vocabulary — moved off `ProjectDecisionsPage.tsx`'s own tab
 * bar to sit alongside the project's other definition-table settings
 * (Action Types, Custom Fields) on `ProjectAdminPage.tsx`, matching where
 * Action Types themselves already live, per explicit user direction.
 *
 * `orgAdminSections` (moved from `orgOverviewSections`):
 * `DecisionTemplatesPanel`, the org-scoped Decision Template library — an org admin manages the template library on
 * Org Management (`OrgAdminPage.tsx`), not the Org Dashboard
 * (`OrgOverviewPage.tsx`), per explicit user direction; `render({orgId})`
 * is identical either way since both pages share `OrgAdminSectionDef`'s
 * shape.
 *
 * `entityAccentColor`: intentionally **not** set. This module still
 * doesn't add a `requirementDetailSections` contribution (a requirement's
 * Decision links are shown by the shared Links panel instead), so there is no
 * cross-module mixed list this module's own entity kind would ever need to be
 * told apart in — nothing would read `useEntityAccentColor("decisions")` yet.
 * Add it alongside whichever change does add such a list, not speculatively now.
 *
 * No `globalNavItems`/`standaloneWorkspaces`/`globalRoutes`/
 * `projectOverviewTiles`/`orgOverviewSections` — Decision Management has no
 * cross-org standalone entity (a Decision only ever exists inside a
 * project, unlike Compliance's own Standards), and nothing
 * calls for a project-overview summary tile or an org-dashboard
 * surface of its own.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "decisions",
  artefactPaths: {
    decision: (projectId, id) => `/projects/${projectId}/modules/decisions/${id}`,
  },
  artefactListPaths: {
    decision: (projectId) => `/projects/${projectId}/modules/decisions`,
  },
  artefactStatusLabels: { decision: DECISION_STATUS_LABEL },
  artefactInactiveStatuses: { decision: ["rejected", "superseded"] },
  routes: [
    { path: "/projects/:projectId/modules/decisions", element: createElement(ProjectDecisionsPage) },
    { path: "/projects/:projectId/modules/decisions/:decisionId", element: createElement(DecisionDetailPage) },
  ],
  projectAdminSections: [
    {
      key: "decision-types",
      label: "Decision Types",
      render: ({ projectId }) => createElement(DecisionTypesPanel, { projectId }),
    },
  ],
  orgAdminSections: [
    {
      key: "decision-templates",
      label: "Decision Templates",
      render: ({ orgId }) => createElement(DecisionTemplatesPanel, { orgId }),
    },
  ],
};
