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
   * project-scoped UI of its own doesn't need to declare any. */
  routes?: TierAModuleRoute[];
  /** This module's org-admin `ResourceMenu` groups, if any — merged into
   * `OrgAdminPage.tsx`'s own fixed core groups and filtered to this org's
   * actually-enabled modules. Omitted (or empty) for a module with no
   * org-level admin surface. */
  orgAdminSections?: OrgAdminSectionDef[];
}
