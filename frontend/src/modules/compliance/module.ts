import { createElement } from "react";

import { t } from "../../i18n/strings";
import type { TierAModuleDefinition } from "../types";
import { ComplianceGlobalNavLink } from "./ComplianceGlobalNavLink";
import { ComplianceOrgOverviewTiles } from "./ComplianceOrgOverviewTiles";
import { ComplianceProjectOverviewTiles } from "./ComplianceProjectOverviewTiles";
import { ComplianceSettingsPage } from "./ComplianceSettingsPage";
import { OrgComplianceDashboard } from "./OrgComplianceDashboard";
import { OrgComplianceOutstandingPanel } from "./OrgComplianceOutstandingPanel";
import { OrgComplianceStandardsPanel } from "./OrgComplianceStandardsPanel";
import { ProjectCompliancePage } from "./ProjectCompliancePage";
import { StandardListPage } from "./StandardListPage";
import { StandardNavSection } from "./StandardNavSection";
import { StandardWorkspacePage } from "./StandardWorkspacePage";

/**
 * Module: modules/compliance/module
 *
 * The Compliance module's frontend registration — the frontend mirror of
 * `backend/app/modules/compliance/module.py`'s `MODULE_DEFINITION`, same
 * naming/shape convention (a `module.ts` file exporting a single
 * `moduleDefinition`, the way the backend file exports a single
 * `MODULE_DEFINITION`). `frontend/src/modules/registry.ts` auto-discovers
 * this file via `import.meta.glob('./*\/module.ts', { eager: true })`
 * (module system follow-up, 2026-09-07 — see `docs/decisions.md`'s "Module
 * system follow-up: frontend module auto-discovery" entry) rather than this
 * module hand-editing that shared file, the same "don't hand-maintain a
 * touch point every module has to remember" motivation the backend's own
 * `INSTALLED_MODULES`/registry-driven `Base.metadata` auto-import follow-ups
 * already established.
 *
 * `routes` (Phase 13, compliance-module-plan.md): this module's single
 * project-scoped route, `ProjectCompliancePage` — `path` uses React
 * Router's own `:projectId` param syntax and must match, once the router
 * segment is substituted for a real id, the `nav_path` the backend's
 * `ModuleFrontendManifest` declares (`backend/app/modules/compliance/
 * module.py`), which uses a literal `"{project_id}"` placeholder the
 * backend interpolates with a concrete id before sending it to the frontend
 * (`routers/projects.py::list_project_enabled_modules`).
 *
 * `orgAdminSections` (module system follow-up, 2026-09-07): originally two
 * org-scoped panels Phase 12/14 each mounted by hand into `OrgAdminPage.
 * tsx` — `ComplianceAdminPanel` (Phase 12, standards/action types/mapping
 * types management) and `OrgCompliancePanel` (Phase 14, the cross-project
 * dashboard/table/outstanding view). Phase 18 ("Compliance Standards" as a
 * first-class, cross-org, project-like nav entity, docs/compliance-module-
 * plan.md) retired the `"compliance"` entry entirely — standards/action
 * types/mapping types management moved to its own top-level `/standards`
 * nav-rail tab (`StandardListPage.tsx`/`StandardWorkspacePage.tsx`/
 * `ComplianceSettingsPage.tsx`), fully superseding `ComplianceAdminPanel`
 * (deleted). Phase 19 ("Organisation Overview" page) retires the remaining
 * `"compliance-overview"` entry the same way — `orgAdminSections` is now
 * empty; see `orgOverviewSections`/`orgOverviewTiles` below for where that
 * content moved to. Labels are read from `i18n/strings.ts`'s own `t()` (the
 * same static English table `useStrings()` layers terminology substitution
 * on top of) rather than duplicated as literals here — none of this
 * module's group labels contain `{term}` tokens, so the plain,
 * unsubstituted `t()` call (this file isn't a component and can't call the
 * `useStrings()` hook) already returns the exact same string
 * `OrgAdminPage`/`OrgOverviewPage` would resolve for every other group's
 * label.
 *
 * `orgOverviewSections` (Phase 19, `modules/types.ts`): originally
 * `OrgCompliancePanel` — a single group whose content was its own internal
 * `Tabs` (Dashboard / Compliance by standard / Outstanding) — previously
 * mounted via `orgAdminSections`' `"compliance-overview"` entry, then moved
 * below `pages/OrgOverviewPage.tsx`'s own core stats header instead,
 * reusing the exact same `{key, label, render({orgId})}` shape
 * `orgAdminSections` already established. **Phase 25b removed
 * `OrgCompliancePanel` and its inner `Tabs` entirely**: `ResourceMenu →
 * Tabs → content` was one navigation layer too many (the style guide's own
 * "when one resource-menu group outgrows itself, split it into more flat
 * top-level groups — don't add nested sub-navigation" addendum, applied a
 * second time, one level deeper than its first application already
 * covered) — the three former tabs are now three flat top-level
 * `orgOverviewSections` entries below, each rendering its panel component
 * directly.
 *
 * `orgOverviewTiles` (Phase 25b, `modules/types.ts`): three headline
 * gauges (overall compliance / active standards / non-compliant projects,
 * `ComplianceOrgOverviewTiles.tsx`) contributed directly into
 * `OrgOverviewPage.tsx`'s own always-visible stats header, so a reviewer
 * sees the org's compliance posture at a glance without clicking into any
 * `orgOverviewSections` group at all.
 *
 * `globalNavItems`/`standaloneWorkspaces` (Phase 18, `modules/types.ts`):
 * the "Compliance Standards" top-level nav-rail tab and the "Standard"
 * left-nav section, each a thin `createElement` wrapper around a real
 * compliance-owned component (`ComplianceGlobalNavLink.tsx`/
 * `StandardNavSection.tsx`) — mirroring `orgAdminSections`' own "module
 * hands the parent a render function producing real components" shape
 * exactly, generalised to the two new nav-contribution kinds this phase
 * needed. `Layout.tsx` never imports either component directly; this file
 * is the only place they're referenced outside their own module.
 *
 * `globalRoutes` (Phase 18, `modules/types.ts`): this module's always-
 * mounted top-level page routes — `StandardListPage.tsx` (`/standards`),
 * `StandardWorkspacePage.tsx` (`/standards/:standardId/:section?/
 * :versionId?` — the trailing `:versionId?` added by Phase 23 so a specific
 * version can be deep-linked/opened directly from `StandardNavSection.tsx`'s
 * new expandable Versions group, rather than always landing on the version
 * list first), and `ComplianceSettingsPage.tsx`
 * (`/standards/settings/:orgId/:group?`).
 * These live inside this module's own directory (not `frontend/src/
 * pages/`) and are registered here, not imported/hardcoded into `App.tsx`
 * — the first implementation pass got this wrong (`App.tsx` imported all
 * three page components directly and hardcoded their routes, the exact
 * same core-imports-a-specific-module mistake `Layout.tsx`'s
 * `globalNavItems`/`standaloneWorkspaces` above were already introduced to
 * fix, just on the routing side instead of the nav side); see
 * `docs/decisions.md`'s "Phase 18 complete" entry for the corrected
 * account. `App.tsx` consumes `globalRoutes` the same generic way it
 * already consumes `buildModuleRoutes`'s project-scoped output.
 *
 * `projectOverviewTiles` (module boundary cleanup, 2026-09-08): this
 * module's per-standard compliance-status tiles on `ProjectOverviewPage
 * .tsx` (Phase 17d) — previously a direct `getProjectComplianceStatus`/
 * `ProjectComplianceStatus` import baked into that core page, the same
 * violation as the two above, found and fixed alongside the backend's
 * `on_org_created`/`project_nav_visible` hooks (see `docs/decisions.md`'s
 * "Module system follow-up: on_org_created / project_nav_visible hooks"
 * entry). `ComplianceProjectOverviewTiles.tsx` owns the fetch and renders
 * zero or more `MetricTile`s; `ProjectOverviewPage.tsx` renders it without
 * knowing compliance exists.
 */
const strings = t();

export const moduleDefinition: TierAModuleDefinition = {
  key: "compliance",
  routes: [
    { path: "/projects/:projectId/modules/compliance", element: createElement(ProjectCompliancePage) },
  ],
  globalRoutes: [
    { path: "/standards", element: createElement(StandardListPage) },
    { path: "/standards/settings/:orgId/:group?", element: createElement(ComplianceSettingsPage) },
    { path: "/standards/:standardId/:section?/:versionId?", element: createElement(StandardWorkspacePage) },
  ],
  orgOverviewSections: [
    {
      key: "compliance-dashboard",
      label: strings.orgAdmin.groupComplianceDashboard,
      render: ({ orgId }) => createElement(OrgComplianceDashboard, { orgId }),
    },
    {
      key: "compliance-by-standard",
      label: strings.orgAdmin.groupComplianceByStandard,
      render: ({ orgId }) => createElement(OrgComplianceStandardsPanel, { orgId }),
    },
    {
      key: "compliance-outstanding",
      label: strings.orgAdmin.groupComplianceOutstanding,
      render: ({ orgId }) => createElement(OrgComplianceOutstandingPanel, { orgId }),
    },
  ],
  orgOverviewTiles: [
    {
      key: "headline",
      render: ({ orgId }) => createElement(ComplianceOrgOverviewTiles, { orgId }),
    },
  ],
  globalNavItems: [
    {
      key: "compliance-standards",
      render: ({ railCollapsed }) => createElement(ComplianceGlobalNavLink, { railCollapsed }),
    },
  ],
  standaloneWorkspaces: [
    {
      key: "standard",
      // Excludes `/standards/settings/:orgId` (`ComplianceSettingsPage.tsx`)
      // — that path also starts with `/standards/` but names an org, not a
      // standard, and has no "Standard" nav section of its own (it's a
      // `ResourceMenu` page, not a project-like drill-down).
      matchPath: /^\/standards\/(?!settings\/)([^/]+)/,
      render: ({ entityId, railCollapsed }) => createElement(StandardNavSection, { entityId, railCollapsed }),
    },
  ],
  projectOverviewTiles: [
    {
      key: "status",
      render: ({ projectId }) => createElement(ComplianceProjectOverviewTiles, { projectId }),
    },
  ],
};
