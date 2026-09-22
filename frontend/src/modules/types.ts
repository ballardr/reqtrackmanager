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

/** `OrgAdminSectionDef`'s project-scoped counterpart (Module 4 Phase 9,
 * 2026-09-22) — same shape, scoped by `projectId` instead of `orgId` for
 * `ProjectAdminPage.tsx`'s own `ResourceMenu` groups. */
export interface ProjectAdminSectionDef {
  /** This section's `ResourceMenu` group key and
   * `/projects/:projectId/admin/:group` route segment — must be unique
   * across every installed module's contributed sections (and distinct
   * from every core group key `ProjectAdminPage.tsx` itself declares). */
  key: string;
  label: string;
  render: (props: { projectId: string }) => ReactNode;
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
 * One headline stat tile a Tier A module contributes to
 * `pages/OrgOverviewPage.tsx`'s own always-visible stats header
 * (compliance-module-plan.md Phase 25b — "the org's headline compliance
 * gauges... must surface directly in the overview's own always-visible
 * stats header, not require a click into the `ResourceMenu` group at
 * all"). Mirrors `ProjectOverviewTileDef` exactly (same "module hands the
 * parent a render function, parent has no idea what's inside it" shape),
 * scoped by `orgId` instead of `projectId` since this header has no project
 * in context. Deliberately distinct from `orgOverviewSections` above: that
 * contributes a whole `ResourceMenu` group of drill-down detail below the
 * header; this contributes one card *inside* the header itself, so a
 * reviewer sees the headline number without navigating anywhere. Omitted
 * (or empty) for a module with no headline gauge of its own.
 */
export interface OrgOverviewTileDef {
  /** Must be unique across every installed module's org-overview tiles —
   * used only as this contribution's React list `key`, never rendered. */
  key: string;
  render: (props: { orgId: string }) => ReactNode;
}

/**
 * One extra section a Tier A module contributes to
 * `pages/RequirementDetailPage.tsx`'s own "Links" card (compliance-module-
 * plan.md Phase 34 — the first consumer is Compliance's own linked-
 * compliance-requirements list plus a picker to add one). Mirrors
 * `ProjectOverviewTileDef`'s exact "module hands the parent a render
 * function, parent has no idea what's inside it" shape, gated the same
 * way (this project's own currently-enabled-modules list) — `render`
 * decides everything about what it shows, including rendering nothing.
 * `RequirementDetailPage.tsx` never imports a specific module's own entity
 * (e.g. it has no notion of what a "compliance requirement" is) — see
 * that page's own Links-card comment for why this exists, and CLAUDE.md's
 * "Modular Feature System Boundary" for the rule this satisfies.
 */
export interface RequirementDetailSectionDef {
  /** Must be unique across every installed module's requirement-detail
   * sections — used only as this contribution's React list `key`, never
   * rendered. */
  key: string;
  render: (props: {
    projectId: string;
    requirementId: string;
    organizationId: string;
    /** Bumped by `RequirementDetailPage.tsx` whenever any link involving
     * this requirement changes — core-to-core (add/remove) or a module's
     * own link kind added via `requirementLinkPickerTabs` below (platform-
     * review-2026-09 Phase 7). A section that owns its own link list (e.g.
     * Compliance's `RequirementTraceabilityLinksSection`) should re-fetch
     * on a `refreshToken` change: it has no other way to learn that a link
     * was added from the shared picker modal, which is a different
     * component instance than this section. Purely a plumbing signal —
     * core has no idea what changed, only that something did. */
    refreshToken: number;
  }) => ReactNode;
}

/**
 * One extra tab a Tier A module contributes to the shared requirement-link
 * picker modal (`components/RequirementLinkPickerModal.tsx`), opened from
 * `pages/RequirementDetailPage.tsx`'s "Add link" button (platform-review-
 * 2026-09 Phase 7). The modal always renders its own built-in "Search" and
 * "Requirements" tabs (core requirement-to-requirement links); any
 * currently-enabled module's own tabs are appended after those, in
 * registration order. Mirrors `RequirementDetailSectionDef`'s exact "module
 * hands the parent a render function, parent has no idea what's inside it"
 * shape — the modal never imports a specific module's own entity (e.g. it
 * has no notion of what a "compliance requirement" is). A contributed tab
 * owns its own target-picker UI *and* its own link-creation call (it links
 * to its own kind of entity via its own module's API, not core's
 * `RequirementLink` — see CLAUDE.md's "Modular Feature System Boundary");
 * calling `onLinked()` is how it tells the modal "a link was created, close
 * and refresh" without the modal knowing what kind of link it was. The
 * first (and, at the time this was written, only) consumer is Compliance's
 * own cascading standard → version → requirement picker.
 */
export interface RequirementLinkPickerTabDef {
  /** Must be unique across every installed module's link-picker tabs, and
   * distinct from the built-in `"search"`/`"requirements"` tab keys — used
   * as this contribution's React list `key` and as part of its `Tabs`
   * panel id, never rendered directly (see `label` for the visible name). */
  key: string;
  /** Visible tab label, e.g. `"Compliance"`. */
  label: string;
  render: (props: {
    projectId: string;
    requirementId: string;
    organizationId: string;
    /** Call once this tab has successfully created its own kind of link.
     * The modal closes and bumps the shared `refreshToken` (above) so any
     * section displaying that link (core's own list, or another module's
     * `requirementDetailSections` contribution) re-fetches. */
    onLinked: () => void;
  }) => ReactNode;
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
  /** This module's `ResourceMenu` groups on `pages/ProjectAdminPage.tsx`
   * (Module 4 Phase 9, 2026-09-22) — merged into that page's own fixed
   * six groups and filtered to this project's actually-enabled modules,
   * the same "module hands the parent a render function, parent has no
   * idea what's inside it" shape `orgAdminSections` already establishes,
   * just scoped by `projectId` instead of `orgId` (a distinct interface
   * from `OrgAdminSectionDef` for that reason, not a second declaration of
   * the same shape). First contributor: Decision Types, moved off
   * `ProjectDecisionsPage.tsx`'s own tab bar to sit alongside the
   * project's other definition-table settings (Action Types, Custom
   * Fields) rather than the module's day-to-day working page — see
   * `docs/decisions.md`. Omitted (or empty) for a module with no
   * project-level admin surface. */
  projectAdminSections?: ProjectAdminSectionDef[];
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
  /** This module's `ResourceMenu` groups on `pages/OrgOverviewPage.tsx`
   * (compliance-module-plan.md Phase 19 — the "Organisation Overview"
   * page), below that page's own core stats header. Reuses
   * `OrgAdminSectionDef`'s exact `{key, label, render({orgId})}` shape —
   * the two pages need identical things from a module (a `ResourceMenu`
   * group's own menu item plus the content it renders) — rather than
   * declaring a second, identically-shaped interface. `OrgOverviewPage.tsx`
   * filters these to this org's actually-enabled modules the same way
   * `OrgAdminPage.tsx` already filters `orgAdminSections`. Omitted (or
   * empty) for a module with no org-overview surface of its own. */
  orgOverviewSections?: OrgAdminSectionDef[];
  /** This module's headline stat tiles on `pages/OrgOverviewPage.tsx`'s own
   * stats header (compliance-module-plan.md Phase 25b). Omitted (or empty)
   * for a module with no headline gauge of its own. */
  orgOverviewTiles?: OrgOverviewTileDef[];
  /** This module's extra sections on `pages/RequirementDetailPage.tsx`'s
   * own Links card (compliance-module-plan.md Phase 34), gated on this
   * project's own `enabled-modules` list the same way `projectOverviewTiles`
   * is. Omitted (or empty) for a module with no requirement-detail
   * contribution of its own. */
  requirementDetailSections?: RequirementDetailSectionDef[];
  /** This module's extra tab(s) in the shared requirement-link picker modal
   * (`components/RequirementLinkPickerModal.tsx`, platform-review-2026-09
   * Phase 7), gated on this project's own `enabled-modules` list the same
   * way `requirementDetailSections` is. Omitted (or empty) for a module
   * with no linkable entity of its own. */
  requirementLinkPickerTabs?: RequirementLinkPickerTabDef[];
  /** This module's own accent colour for `.entity-accent-card`/`.entity-
   * accent-row` styling (`styles/theme.css`) — the left-border stripe a list
   * row showing this module's own entity kind (e.g. a compliance
   * requirement, alongside core requirement-to-requirement links, in
   * `pages/RequirementDetailPage.tsx`'s own mixed Links card) renders with,
   * so a user scanning a list mixing several entity kinds can tell them
   * apart at a glance (see `modules/entityAccentColor.ts`'s own docstring
   * for the full mechanism). One literal hex pair per module, not a CSS
   * variable declared in `theme.css` — `theme.css` is a core file and must
   * never carry a per-module colour token, the same boundary violation as a
   * per-module value hand-added to a core enum/column (`ProjectSequenceCounter
   * .artefact_type`'s own corrected history, CLAUDE.md's "Modular Feature
   * System Boundary") applied to a colour token instead of an enum member —
   * `frontend/src/api/types.ts`'s `ENTITY_ACCENT_COLOR` briefly grew a
   * `"compliance"`/`"decision"` entry this exact way before being corrected
   * back to only the 3 genuinely core-owned kinds (requirement/action/
   * change_request). Keyed implicitly by this definition's own `key` at the
   * call site (`useEntityAccentColor(moduleKey)`) — no separate "kind"
   * identifier, since one module contributes exactly one entity kind today.
   * Omitted for a module with no entity of its own ever shown in a mixed
   * list (falls back to a neutral grey — see `entityAccentColor.ts`). */
  entityAccentColor?: { light: string; dark: string };
}
