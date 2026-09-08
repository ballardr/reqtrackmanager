import type { ReactNode } from "react";

/**
 * One route a Tier A ("installed") module contributes — a plain React
 * Router route spliced into `App.tsx`'s `<Routes>` alongside the core
 * pages, compiled directly into this bundle (compliance-module-plan.md
 * Phase 3). `path` must match the `nav_path` the module's backend
 * `ModuleFrontendManifest` declares, so the nav entry `Layout.tsx` renders
 * (from `GET /projects/{id}/enabled-modules`) actually links somewhere.
 */
export interface TierAModuleRoute {
  path: string;
  element: ReactNode;
}

/**
 * One org-admin `ResourceMenu` group a Tier A module contributes to
 * `OrgAdminPage.tsx` (module system follow-up, 2026-09-07 — see
 * `docs/decisions.md`'s "Module system follow-up: dynamic org-admin panel
 * registration" entry). Phase 3's own routing/nav-discovery mechanism
 * (`TierAModuleRoute` above) is project-scoped end to end and has no
 * org-level equivalent (see Phase 12's notes in
 * `docs/compliance-module-plan.md`) — this is that missing org-level half,
 * generalising what Phase 12/14 each mounted by hand into `OrgAdminPage.tsx`
 * (`ComplianceAdminPanel`/`OrgCompliancePanel`) into a declared-by-the-module
 * mechanism instead. Shaped after `ResourceMenuGroupDef`
 * (`components/ResourceMenu.tsx`) — `key`/`label` mirror that type exactly
 * (the module doesn't compute `href` itself; `OrgAdminPage.tsx` derives it
 * from `key` the same way it does for every core group) — plus a
 * `render` prop-function, this codebase's existing convention for handing a
 * parent a piece of UI to mount with parent-owned data
 * (`ResourceMenuGroupDef`'s own `children`, `DirectoryColumn.render`,
 * `DefinitionList`'s `renderExtra`), rather than inventing a new shape. */
export interface OrgAdminSectionDef {
  /** This section's `ResourceMenu` group key and `/orgs/:orgId/admin/:group`
   * route segment — must be unique across every installed module's
   * contributed sections (and distinct from every core group key
   * `OrgAdminPage.tsx` itself declares), the same uniqueness assumption
   * `TierAModuleRoute.path` already relies on for project routes. */
  key: string;
  label: string;
  render: (props: { orgId: string }) => ReactNode;
}

/**
 * One top-level nav-rail link a Tier A module contributes to `Layout.tsx`'s
 * "Global" section (docs/compliance-module-plan.md Phase 18 — "Compliance
 * Standards" as a first-class, cross-org, project-like nav entity). Unlike
 * `OrgAdminSectionDef`, this has no parent-owned data to hand the module
 * (`Layout.tsx` doesn't know which org/project is relevant to a global tab)
 * — `railCollapsed` is the only prop, purely so the module's own link can
 * render consistently with every other rail entry (`NavRailLink`, exported
 * from `components/Layout.tsx` for exactly this reuse). The module's
 * `render` function owns *all* of its own visibility logic (e.g. Compliance
 * gates its link on its own `useComplianceNavVisibility()` hook) and
 * returns `null` when the tab shouldn't show at all — `Layout.tsx` invites
 * every installed module's global nav items to render unconditionally and
 * never itself decides whether a given one applies, the same "core doesn't
 * decide, the module decides" boundary `orgAdminSections`'s own filtering
 * already establishes for `OrgAdminPage.tsx` (there the filter is enablement
 * state Layout.tsx doesn't have a project/org to check against here; a
 * global tab's own applicability is the module's call to make, every time).
 */
export interface GlobalNavItemDef {
  /** Must be unique across every installed module's global nav items —
   * used only as this item's React list `key`, never rendered. */
  key: string;
  render: (props: { railCollapsed: boolean }) => ReactNode;
}

/**
 * One "standalone workspace" nav-rail section a Tier A module contributes —
 * a project-like drill-down entity that isn't a `Project` (docs/compliance-
 * module-plan.md Phase 18's own "Standard" section is the first of these:
 * Overview/Details, Versions, History, rendered as a sibling structural
 * pattern to the "Project" section, not nested inside it, whenever a
 * Standard's own id is present in the URL). `Layout.tsx` tests `matchPath`
 * against the current path for every installed module's contributed
 * workspaces and renders the first match's own section — it has no
 * built-in notion of what a "Standard" (or any future such entity) even is;
 * the module supplies both the URL shape it owns and the nav markup for it.
 */
export interface StandaloneWorkspaceDef {
  /** Must be unique across every installed module's standalone workspaces —
   * used only as this workspace's React list `key`, never rendered. */
  key: string;
  /** Tested against `location.pathname`; this workspace is active exactly
   * when it matches, and its own first capture group is passed to `render`
   * as `entityId` (the same "id in the URL selects the entity" shape
   * `Layout.tsx`'s existing `projectId` regex already uses, generalised to
   * a module-declared pattern instead of a hardcoded `/projects/` one). */
  matchPath: RegExp;
  render: (props: { entityId: string; railCollapsed: boolean }) => ReactNode;
}

/**
 * One extra metric tile a Tier A module contributes to
 * `ProjectOverviewPage.tsx`'s `.grid.grid-metrics` grid (module boundary
 * cleanup, 2026-09-08 — e.g. Compliance's per-standard status tiles,
 * previously a direct `getProjectComplianceStatus`/`ProjectComplianceStatus`
 * import baked into that core page). Gated on the same per-project
 * `enabled-modules` list `ProjectOverviewPage.tsx` already fetches — a
 * module not currently enabled for the project contributes nothing, the
 * same "core doesn't decide, the module decides how much to render" shape
 * `globalNavItems`/`standaloneWorkspaces` already establish, just filtered
 * on project-scoped enablement here instead of nothing to filter on
 * (compare `routes`' own project-scoped/`enabledModules`-gated shape).
 * `render` may return zero tiles (e.g. Compliance renders none once loaded
 * if the project has no standards assigned yet) — build tiles with
 * `components/MetricTile.tsx` so a module's own tiles render identically
 * to the page's built-in ones.
 */
export interface ProjectOverviewTileDef {
  /** Must be unique across every installed module's project-overview
   * tiles — used only as this contribution's React list `key`, never
   * rendered. */
  key: string;
  render: (props: { projectId: string }) => ReactNode;
}

/**
 * A first-party (or npm-installed third-party) Tier A module's frontend
 * registration — the module ships its own route components and registers
 * them here, the same way this file's own first-party pages are declared
 * in `App.tsx`, rather than through any dynamic/remote-loading mechanism
 * (that's Tier B, `<ModuleFrame>`). See `registry.ts`'s own docstring.
 */
export interface TierAModuleDefinition {
  /** Must match the `module_key` the backend `ModuleDefinition` registers
   * (`backend/app/modules/registry.py`), so `App.tsx` can look up which
   * routes to mount for a given currently-enabled module, and so
   * `OrgAdminPage.tsx` can tell whether this module is actually enabled for
   * the org it's rendering before showing any of its `orgAdminSections`. */
  key: string;
  /** This module's project-scoped routes (Phase 3). Defaults to none — a
   * module contributing only org-admin sections (see below) and no
   * project-scoped UI of its own doesn't need to declare any. Only ever
   * mounted for a project where the backend currently reports this module
   * as enabled (`buildModuleRoutes`, keyed off `useProjectEnabledModules`'s
   * `enabledModules` list) — contrast with `globalRoutes` below, which is
   * always mounted for every installed module regardless of any one
   * project's/org's own enablement state. */
  routes?: TierAModuleRoute[];
  /** This module's always-mounted, top-level routes (Phase 18) — reuses
   * `TierAModuleRoute`'s exact `{path, element}` shape, but spliced into
   * `App.tsx`'s `<Routes>` unconditionally for every installed module, the
   * same way `/projects`/`/orgs` are, rather than gated on a specific
   * project's/org's own currently-enabled-modules list the way `routes`
   * above is. For a cross-org, always-present surface with no single
   * project/org to check enablement against in the first place (Compliance
   * Standards' `/standards`, `/standards/:standardId`, `/standards/
   * settings/:orgId` — none of these has a `projectId` in the URL for
   * `buildModuleRoutes`'s existing mechanism to key an enablement check
   * off). `App.tsx` consumes this generically (`installedModules.flatMap(m
   * => m.globalRoutes ?? [])`) and never imports a specific module's page
   * components directly — the same "core doesn't hardcode one module"
   * boundary `globalNavItems`/`standaloneWorkspaces` above already
   * establish, and the reason a Tier A module's own page components (e.g.
   * `modules/compliance/StandardListPage.tsx`) live inside the module's own
   * directory, never under `frontend/src/pages/` (see `docs/decisions.md`'s
   * "Phase 18 complete" entry for the second, `App.tsx`-side instance of
   * this same violation being caught and corrected here). Omitted (or
   * empty) for a module with no such route of its own. */
  globalRoutes?: TierAModuleRoute[];
  /** This module's org-admin `ResourceMenu` groups, if any — merged into
   * `OrgAdminPage.tsx`'s own fixed core groups and filtered to this org's
   * actually-enabled modules. Omitted (or empty) for a module with no
   * org-level admin surface. */
  orgAdminSections?: OrgAdminSectionDef[];
  /** This module's top-level nav-rail links (Phase 18), rendered in
   * `Layout.tsx`'s "Global" section. Omitted (or empty) for a module with
   * no global tab of its own. */
  globalNavItems?: GlobalNavItemDef[];
  /** This module's "standalone workspace" nav-rail sections (Phase 18),
   * rendered as a sibling to `Layout.tsx`'s "Project" section whenever the
   * current path matches one of them. Omitted (or empty) for a module with
   * no such entity of its own. */
  standaloneWorkspaces?: StandaloneWorkspaceDef[];
  /** Extra metric tiles this module contributes to `ProjectOverviewPage
   * .tsx` (module boundary cleanup, 2026-09-08), gated on this project's
   * own `enabled-modules` list. Omitted (or empty) for a module with no
   * project-overview summary of its own. */
  projectOverviewTiles?: ProjectOverviewTileDef[];
}
