import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import { ProjectStrategiesPage } from "./ProjectStrategiesPage";
import { StrategyDetailPage } from "./StrategyDetailPage";

/**
 * Module: modules/context_strategy/module
 *
 * The Context & Strategy module's frontend registration (docs/plans/
 * module-01-context-and-strategy-plan.md Phase 7.1) — the frontend mirror
 * of `backend/app/modules/context_strategy/module.py`'s `MODULE_DEFINITION`,
 * same single-`moduleDefinition`-export convention every other Tier A
 * module uses. `frontend/src/modules/registry.ts` auto-discovers this file
 * via `import.meta.glob('./*\/module.ts', { eager: true })`; no hand-edit
 * to that file is needed (confirmed by reading `registry.ts`'s own
 * docstring before adding this file).
 *
 * **This is the first of five planned sub-phases (7.1-7.5), one per
 * artefact type** (Strategy, Future State, Pain Point, Guiding Principle,
 * Open Question — Phase 0 Q7's explicit "five separate top-level nav-rail
 * entries, not one grouped entry with tabs," diverging from `docs/ux-style-
 * guide.md`'s usual grouping preference per the user's own deliberate call,
 * see that phase's own resolution text). Only Strategy's own routes/panel
 * exist so far — Phase 7.2-7.5 will each add their own artefact type's
 * `routes`/`globalRoutes` entries here and their own `additional_nav_
 * entries` row on the backend's `MODULE_DEFINITION.frontend_manifest`
 * (`app.modules.registry.ModuleFrontendManifest`, extended with this exact
 * multi-entry capability as part of this same phase — see `docs/
 * decisions.md`).
 *
 * `routes` (project-scoped, gated on this project's own enabled-modules
 * list, `buildModuleRoutes.tsx`): the Strategy list
 * (`ProjectStrategiesPage`) and its detail page (`StrategyDetailPage`) —
 * `path` matches the primary `nav_path` `module.py`'s own `frontend_
 * manifest` declares.
 *
 * `globalRoutes` (always-mounted, Phase 18's precedent — see that phase's
 * own reasoning in `modules/compliance/module.ts`): `StrategyDetailPage`
 * again, this time at an **org**-scoped path
 * (`/orgs/:organizationId/modules/context_strategy/strategies/:strategyId`).
 * **Decided by: Agent** — an org-scoped Strategy (Phase 0 Q2) has no single
 * *project* whose enabled-modules list `routes` above could gate a detail
 * route against, the same reason Compliance's own Standards detail route
 * uses `globalRoutes` rather than `routes`; `StrategyDetailPage` itself is
 * one shared, scope-aware component reading whichever of `projectId`/
 * `organizationId` its current route supplies (see that component's own
 * docstring), not two near-identical page components.
 *
 * `orgOverviewSections`: `OrgStrategiesPanel`, the org-scoped Strategy list
 * — see that component's own docstring for the full reasoning on why
 * `orgOverviewSections` (Org Dashboard) rather than `orgAdminSections` (Org
 * Management) was chosen.
 *
 * No `globalNavItems`/`standaloneWorkspaces`/`projectOverviewTiles`/
 * `orgAdminSections`/`requirementDetailSections`/`requirementLinkPickerTabs`/
 * `entityAccentColor` this phase — Strategy has no cross-org standalone
 * entity of its own (unlike Compliance's Standards), no project-overview
 * summary tile or admin-configuration table this phase's own scope calls
 * for, and (mirroring `modules/decisions/module.ts`'s own identical
 * omission and reasoning) no `requirementDetailSections`/
 * `requirementLinkPickerTabs`/`entityAccentColor` contribution yet, since
 * nothing renders a mixed list containing a Strategy row alongside other
 * entity kinds.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "context_strategy",
  routes: [
    { path: "/projects/:projectId/modules/context_strategy/strategies", element: createElement(ProjectStrategiesPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
  ],
  globalRoutes: [
    {
      path: "/orgs/:organizationId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
  ],
  orgOverviewSections: [
    {
      key: "context-strategy-org-strategies",
      label: "Strategy",
      render: ({ orgId }) => createElement(OrgStrategiesPanel, { orgId }),
    },
  ],
};
