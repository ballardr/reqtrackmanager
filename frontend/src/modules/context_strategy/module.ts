import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { FutureStateDetailPage } from "./FutureStateDetailPage";
import { OrgFutureStatesPanel } from "./OrgFutureStatesPanel";
import { OrgPainPointTypesPanel } from "./OrgPainPointTypesPanel";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import { PainPointDetailPage } from "./PainPointDetailPage";
import { ProjectFutureStatesPage } from "./ProjectFutureStatesPage";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import { ProjectPainPointTypesPanel } from "./ProjectPainPointTypesPanel";
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
 * **This is the second of five planned sub-phases (7.1-7.5), one per
 * artefact type** (Strategy, Future State, Pain Point, Guiding Principle,
 * Open Question — Phase 0 Q7's explicit "five separate top-level nav-rail
 * entries, not one grouped entry with tabs," diverging from `docs/ux-style-
 * guide.md`'s usual grouping preference per the user's own deliberate call,
 * see that phase's own resolution text). Strategy (7.1) and Future State
 * (7.2) routes/panels exist so far — Phase 7.3-7.5 will each add their own
 * artefact type's `routes`/`globalRoutes` entries here and their own
 * `additional_nav_entries` row on the backend's `MODULE_DEFINITION.
 * frontend_manifest` (`app.modules.registry.ModuleFrontendManifest`,
 * extended with this exact multi-entry capability in Phase 7.1 — see
 * `docs/decisions.md`).
 *
 * `routes` (project-scoped, gated on this project's own enabled-modules
 * list, `buildModuleRoutes.tsx`): the Strategy list/detail pages (7.1) and,
 * added this phase, the Future State list (`ProjectFutureStatesPage`) and
 * detail page (`FutureStateDetailPage`) — `path` matches the corresponding
 * `nav_path` `module.py`'s own `frontend_manifest`/`additional_nav_entries`
 * declares.
 *
 * `globalRoutes` (always-mounted, Phase 18's precedent — see that phase's
 * own reasoning in `modules/compliance/module.ts`): `StrategyDetailPage`
 * and, added this phase, `FutureStateDetailPage`, each at an **org**-scoped
 * path (`/orgs/:organizationId/modules/context_strategy/{strategies,
 * future-states}/:id`). **Decided by: Agent, following `StrategyDetailPage`'s
 * own precedent exactly** — an org-scoped Future State (Phase 0 Q1's
 * follow-on) has no single *project* whose enabled-modules list `routes`
 * above could gate a detail route against; `FutureStateDetailPage` itself is
 * one shared, scope-aware component reading whichever of `projectId`/
 * `organizationId` its current route supplies, not two near-identical page
 * components.
 *
 * `orgOverviewSections`: `OrgStrategiesPanel` (7.1) and, added this phase,
 * `OrgFutureStatesPanel` — see that component's own docstring for the full
 * reasoning on why `orgOverviewSections` (Org Dashboard) rather than
 * `orgAdminSections` (Org Management) was chosen, following Strategy's own
 * placement for consistency.
 *
 * No `globalNavItems`/`standaloneWorkspaces`/`projectOverviewTiles`/
 * `orgAdminSections`/`requirementDetailSections`/`requirementLinkPickerTabs`/
 * `entityAccentColor` this phase either — Future State has no cross-org
 * standalone entity of its own, no project-overview summary tile or
 * admin-configuration table this phase's own scope calls for, and (mirroring
 * Phase 7.1's own identical omission and reasoning) nothing yet renders a
 * mixed list containing a Future State row alongside other entity kinds.
 *
 * **Phase 7.3 (2026-09-29) adds Pain Point** — the third of five planned
 * sub-phases, and structurally different from Strategy/Future State in two
 * ways this file reflects directly:
 *
 * 1. **Project-scoped only** (source overview §6) — `routes` gains
 *    `ProjectPainPointsPage`/`PainPointDetailPage`, but there is **no**
 *    `globalRoutes` entry and **no** `orgOverviewSections` contribution for
 *    the Pain Point artefact itself, unlike Strategy/Future State's org-
 *    scoped twins — there is no org-scoped Pain Point to reach via either
 *    mechanism.
 * 2. **A two-tier type vocabulary** (Phase 0 Q3) with its own admin surfaces,
 *    not just the artefact's own CRUD: `orgAdminSections` gains
 *    `OrgPainPointTypesPanel` (the org-scoped shared base tier) and
 *    `projectAdminSections` gains `ProjectPainPointTypesPanel` (the
 *    project-scoped override/local-type tier) — this module's first use of
 *    either section (see each panel's own docstring for the full placement
 *    reasoning, including why the type vocabulary lands on the admin
 *    sections while the artefact's own org-scoped siblings landed on
 *    `orgOverviewSections`).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "context_strategy",
  routes: [
    { path: "/projects/:projectId/modules/context_strategy/strategies", element: createElement(ProjectStrategiesPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
    { path: "/projects/:projectId/modules/context_strategy/future-states", element: createElement(ProjectFutureStatesPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/future-states/:futureStateId",
      element: createElement(FutureStateDetailPage),
    },
    { path: "/projects/:projectId/modules/context_strategy/pain-points", element: createElement(ProjectPainPointsPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/pain-points/:painPointId",
      element: createElement(PainPointDetailPage),
    },
  ],
  globalRoutes: [
    {
      path: "/orgs/:organizationId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
    {
      path: "/orgs/:organizationId/modules/context_strategy/future-states/:futureStateId",
      element: createElement(FutureStateDetailPage),
    },
  ],
  orgOverviewSections: [
    {
      key: "context-strategy-org-strategies",
      label: "Strategy",
      render: ({ orgId }) => createElement(OrgStrategiesPanel, { orgId }),
    },
    {
      key: "context-strategy-org-future-states",
      label: "Future State",
      render: ({ orgId }) => createElement(OrgFutureStatesPanel, { orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      render: ({ orgId }) => createElement(OrgPainPointTypesPanel, { orgId }),
    },
  ],
  projectAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      render: ({ projectId }) => createElement(ProjectPainPointTypesPanel, { projectId }),
    },
  ],
};
