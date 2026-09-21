import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { DecisionTemplatesPanel } from "./DecisionTemplatesPanel";
import { ProjectDecisionsPage } from "./ProjectDecisionsPage";

/**
 * Module: modules/decisions/module
 *
 * The Decision Management module's frontend registration (docs/plans/
 * module-04-decision-management-plan.md Phase 5) — the frontend mirror of
 * `backend/app/modules/decisions/module.py`'s `MODULE_DEFINITION`, same
 * single-`moduleDefinition`-export convention every other Tier A module
 * uses. `frontend/src/modules/registry.ts` auto-discovers this file; no
 * hand-edit to that file is needed.
 *
 * `routes`: `ProjectDecisionsPage`, this module's only project-scoped
 * route — `path` matches the `nav_path` `module.py`'s own `frontend_
 * manifest` declares (with React Router's `:projectId` syntax standing in
 * for the backend's `"{project_id}"` placeholder), mirroring `modules/
 * compliance/module.ts`'s identical single-route shape.
 *
 * `orgOverviewSections`: `DecisionTemplatesPanel`, the org-scoped Decision
 * Template library (Phase 0 addendum items 1/2/6/7) — a Decision Template
 * has no project of its own to live under, so this is the org-level
 * counterpart of `ProjectDecisionsPage`'s "Decision Types" tab (project-
 * scoped, lives inside that page instead — see `DecisionTypesPanel.tsx`'s
 * own docstring for why the two vocabularies have different scopes).
 *
 * `entityAccentColor`: intentionally **not** set. Phase 5 deliberately
 * doesn't add a `requirementDetailSections`/`requirementLinkPickerTabs`
 * contribution yet (see `ProjectDecisionsPage.tsx`'s own module docstring
 * for that scoping call), so there is no cross-module mixed list this
 * module's own entity kind would ever need to be told apart in — nothing
 * would read `useEntityAccentColor("decisions")` yet. Add it alongside
 * whichever future phase does add that contribution, not speculatively now.
 *
 * No `orgAdminSections`/`globalNavItems`/`standaloneWorkspaces`/
 * `globalRoutes`/`projectOverviewTiles` — Decision Management has no
 * cross-org standalone entity (a Decision only ever exists inside a
 * project, unlike Compliance's own Standards), and Phase 5's own scope
 * doesn't call for a project-overview summary tile.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "decisions",
  routes: [
    { path: "/projects/:projectId/modules/decisions", element: createElement(ProjectDecisionsPage) },
  ],
  orgOverviewSections: [
    {
      key: "decision-templates",
      label: "Decision Templates",
      render: ({ orgId }) => createElement(DecisionTemplatesPanel, { orgId }),
    },
  ],
};
