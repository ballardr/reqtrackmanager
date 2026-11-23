import type { ComponentType, ReactNode } from "react";

import type { ProjectScope } from "../api/projectScope";
import type { ReportCatalogueEntry, ReportResult, ReportRunValues } from "../api/reports";
import type { ReportFigureActionResolver } from "../components/ReportViewer";
import type { Notification } from "../api/types";

/**
 * One route a Tier A ("installed") module contributes: a plain React Router route spliced into `App.tsx`'s `<Routes>`
 * beside the core pages. `path` must match the `nav_path` of the module's backend `ModuleFrontendManifest`, so the nav
 * entry `Layout.tsx` renders (from `GET /projects/{id}/enabled-modules`) links somewhere.
 */
export interface TierAModuleRoute {
  path: string;
  element: ReactNode;
}

/** A named menu group that several sections of one module can share. */
export interface AdminSectionGroup {
  /** Menu group key and the `:group` URL segment of every section that declares it. Must differ from every core group
   * key and every section key. */
  key: string;
  /** Formal, user-visible name of the group (the module's own area, for example "Risk Management"). */
  label: string;
}

/**
 * One org-admin `ResourceMenu` group a Tier A module contributes to `OrgAdminPage.tsx` (`docs/decisions.md` "Module
 * system follow-up: dynamic org-admin panel registration"). The routing and nav discovery of `TierAModuleRoute` is
 * project-scoped, so this is its organisation-level half, declared by the module and not hand-mounted into
 * `OrgAdminPage.tsx`. It follows `ResourceMenuGroupDef` (`components/ResourceMenu.tsx`): `key` and `label` mirror it
 * (`OrgAdminPage.tsx` derives `href` from `key` as for core groups) and a `render` function hands the parent a piece
 * of UI to mount, as `DirectoryColumn.render` and `DefinitionList`'s `renderExtra` do.
 */
export interface OrgAdminSectionDef {
  /** This section's `ResourceMenu` group key and `/orgs/:orgId/admin/:group` route segment; unique across every
   * installed module's sections and distinct from every core group key `OrgAdminPage.tsx` declares, as
   * `TierAModuleRoute.path` is for project routes. */
  key: string;
  label: string;
  /** The module's sub-component this section configures. The page leaves the section out while that sub-component is
   * switched off for the organisation, so no one is offered settings for a feature they cannot use. */
  subComponent?: string;
  /** Sections that declare the same group are listed under one expandable menu entry, at
   * `/orgs/:orgId/admin/:group/:section`. A section without a group, or the only visible section of its group, is one
   * menu entry at one level. */
  group?: AdminSectionGroup;
  render: (props: { orgId: string }) => ReactNode;
}

/** `OrgAdminSectionDef`'s project-scoped counterpart: the same shape, scoped by `projectId` instead of `orgId`, for
 * `ProjectAdminPage.tsx`'s `ResourceMenu` groups. */
export interface ProjectAdminSectionDef {
  /** This section's `ResourceMenu` group key and `/projects/:projectId/admin/:group` route segment; unique across every
   * installed module's sections and distinct from every core group key `ProjectAdminPage.tsx` declares. */
  key: string;
  label: string;
  /** The module's sub-component this section configures. The page leaves the section out while that sub-component is
   * effectively off for the project (its own switch, else the organisation's). */
  subComponent?: string;
  /** As `OrgAdminSectionDef.group`, at `/projects/:projectId/admin/:group/:section`. */
  group?: AdminSectionGroup;
  render: (props: { projectId: string }) => ReactNode;
}

/**
 * One top-level nav-rail link a Tier A module contributes to `Layout.tsx`'s "Global" section ("Compliance Standards"
 * as a cross-organisation, project-like entity). It has no parent-owned data for the module (`Layout.tsx` does not know
 * which organisation or project a global tab concerns): `railCollapsed` is the only prop, so the link renders like
 * every other rail entry (`NavRailLink`, exported from `components/NavRailLink.tsx`). The module's `render` owns all its
 * visibility logic (Compliance gates its link on `useComplianceNavVisibility()`) and returns `null` when the tab should
 * not show: `Layout.tsx` renders every installed module's global nav items unconditionally and never decides whether
 * one applies.
 */
export interface GlobalNavItemDef {
  /** Must be unique across every installed module's global nav items; used only as the React list `key`. */
  key: string;
  render: (props: { railCollapsed: boolean }) => ReactNode;
}

/**
 * One "standalone workspace" nav-rail section a Tier A module contributes: a project-like drill-down entity that is
 * not a `Project` (Compliance's "Standard" section: Overview/Details, Versions, History, rendered beside the "Project"
 * section, not inside it, whenever a Standard's id is in the URL). `Layout.tsx` tests `matchPath` against the current
 * path for every installed module's workspaces and renders the first match; it has no notion of what a "Standard" is,
 * and the module supplies the URL shape and the nav markup.
 */
export interface StandaloneWorkspaceDef {
  /** Must be unique across every installed module's standalone workspaces; used only as the React list `key`. */
  key: string;
  /** Tested against `location.pathname`; the workspace is active when it matches, and its first capture group is
   * passed to `render` as `entityId` (the id in the URL selects the entity, as `Layout.tsx`'s `projectId` regex does,
   * but with a module-declared pattern). */
  matchPath: RegExp;
  render: (props: { entityId: string; railCollapsed: boolean }) => ReactNode;
}

/**
 * A widget type a module contributes to the project overview (`TierAModuleDefinition.overviewWidgets`), for example
 * Compliance's per-standard status tiles or a risk heat map. The backend declares the same key in
 * `ModuleDefinition.overview_widgets`, so the server validates a stored layout and offers the type only where the
 * module is enabled; this is the renderer. The overview never imports the module: it looks the renderer up by
 * `<module key>:<key>`.
 */
export interface ProjectOverviewWidgetDef {
  /** Unique within the module; the widget's type is `<module key>:<key>`. */
  key: string;
  /** Draws the widget. `config` is the settings stored with the widget (opaque to the core); `title` is its
   * title, already defaulted. Return a card, as the built-in widgets are. */
  render: (props: { projectId: string; projectScope: ProjectScope; title: string; config: Record<string, unknown> }) => ReactNode;
}

/** A search scope a module offers beyond the built-in "This project" and "All projects" (`TierAModuleDefinition.searchScopes`); requests carry it as `<module key>:<key>:<ref id>`. */
export interface SearchScopeDefinition {
  /** Identifies the scope within its module (`"standard"`); matches the backend `search_scopes` key. */
  key: string;
  /** What the Scope filter calls it ("This standard"). */
  label: string;
  /** Which scope is the default where several match the current page: the highest wins. The built-ins are
   * All projects 0 and This project 100; a unit inside a project or organisation is usually narrower. Default 200. */
  narrowness?: number;
  /** The id of the unit the page at `pathname` is inside (a standard's id), or `null` when it is not inside one. */
  match: (pathname: string) => string | null;
}

/**
 * A widget type a module contributes to an organisation's overview dashboards (`TierAModuleDefinition.orgOverviewWidgets`),
 * the organisation counterpart of `ProjectOverviewWidgetDef`: the module hands the page a render function and the page
 * never imports the module. The backend declares the same key in `ModuleDefinition.org_overview_widgets`, so the
 * server validates a stored layout and offers the type only while the organisation has the module enabled. It is
 * looked up by `<module key>:<key>`.
 */
export interface OrgOverviewWidgetDef {
  /** Unique within the module; the widget's type is `<module key>:<key>`. */
  key: string;
  /** Draws the widget for the organisation. `config` is the settings stored with the widget (opaque to the core);
   * `title` is its title, already defaulted. The widget reads the module's own endpoints, and returns a card. */
  render: (props: { orgId: string; title: string; config: Record<string, unknown> }) => ReactNode;
}

/**
 * One extra section a Tier A module contributes to `pages/RequirementDetailPage.tsx`'s "Links" card (first consumer:
 * Compliance's linked compliance requirements list with a picker to add one). Like `ProjectOverviewWidgetDef`, the
 * module hands the parent a render function and the parent does not know what is inside it, gated by the project's
 * enabled modules; `render` decides everything it shows, including nothing. `RequirementDetailPage.tsx` never imports
 * a module's entity (CLAUDE.md "Modular Feature System Boundary").
 */
export interface RequirementDetailSectionDef {
  /** Must be unique across every installed module's requirement-detail sections; used only as the React list `key`. */
  key: string;
  render: (props: {
    projectId: string;
    requirementId: string;
    organizationId: string;
    /** Bumped by `RequirementDetailPage.tsx` whenever a link involving the page reloads (e.g. after a change request is
     * decided). A section that owns its own link list (e.g. Compliance's `RequirementTraceabilityLinksSection`) should
     * re-fetch when it changes; it is a plumbing signal, and core does not know what changed. */
    refreshToken: number;
  }) => ReactNode;
}

/**
 * Props a module's custom report view receives. The shared `ReportRunner` runs the report, owns loading, error and
 * empty states, the parameter form and downloads, and hands the view the collected `result` plus its context. A table
 * of `result.sections` needs no view (`ReportViewer` is the fallback).
 */
export interface ReportViewProps {
  entry: ReportCatalogueEntry;
  result: ReportResult;
  /** What the report ran against: a project or an organisation. */
  scope: { kind: "project" | "organization"; id: string };
  /** The current run-time values (declared parameters plus `include_children`). */
  values: ReportRunValues;
  /** Changes one value and re-runs the report; only meaningful for a name in `ReportViewDef.ownedParams`. */
  onValueChange: (name: string, value: string | number | boolean | null) => void;
  /** What clicking a headline figure does; forward it to `ReportSummary` so figures link like the generic view's. */
  figureAction?: ReportFigureActionResolver;
}

/** One custom on-screen view for a module's report, keyed by the backend `ReportDefinition.key` in `TierAModuleDefinition.reportViews`. */
export interface ReportViewDef {
  component: ComponentType<ReportViewProps>;
  /** Declared parameters the view draws its own controls for (e.g. a scoring-model switcher); the shared parameter form hides them so one parameter never has two controls. */
  ownedParams?: string[];
}

/** What the Links panel hands a module's create dialog (`TierAModuleDefinition.linkedRecordCreators`). */
export interface LinkedRecordCreatorProps {
  projectId: string;
  /** The record whose Links panel opened the dialog, for a form that pre-fills from it (a Change Request's affected
   * Requirement, a Finding's Engagement); the panel links the new record to it either way. */
  pageRecord: { type: string; id: string };
  /** Called with the new record's id once it is created (the panel then links it and closes the dialog). */
  onCreated: (id: string) => void;
  /** Called when the person dismisses the dialog without creating anything. */
  onCancel: () => void;
}

/** One record type a module can create from the Links panel. */
export interface LinkedRecordCreator {
  /** Names the type in the panel's "Create new" list (e.g. "Pain Point"). */
  label: string;
  /** Renders the module's own create dialog; it must create the record itself and report its id. */
  render: (props: LinkedRecordCreatorProps) => ReactNode;
}

/**
 * A first-party (or npm-installed third-party) Tier A module's frontend registration: it ships its route components and
 * registers them here, as `App.tsx` declares the core pages, with no dynamic or remote loading (that is Tier B,
 * `<ModuleFrame>`). See `registry.ts`.
 */
export interface TierAModuleDefinition {
  /** Must match the `module_key` the backend `ModuleDefinition` registers (`backend/app/modules/registry.py`), so
   * `App.tsx` can look up the routes to mount for an enabled module and `OrgAdminPage.tsx` can tell whether the module
   * is enabled for the organisation before showing its `orgAdminSections`. */
  key: string;
  /** This module's project-scoped routes. Defaults to none: a module contributing only org-admin sections needs none.
   * Mounted only for a project where the backend reports the module enabled (`buildModuleRoutes`, keyed off
   * `useProjectEnabledModules`'s `enabledModules`), unlike `globalRoutes`, which is always mounted. */
  routes?: TierAModuleRoute[];
  /** This module's always-mounted, top-level routes, with `TierAModuleRoute`'s `{path, element}` shape, spliced into
   * `App.tsx`'s `<Routes>` for every installed module and not gated on a project's or organisation's enabled modules as
   * `routes` is. For a cross-organisation surface with no single project or organisation to check enablement against
   * (Compliance Standards' `/standards`, `/standards/:standardId`, `/standards/settings/:orgId`). `App.tsx` consumes
   * this generically (`installedModules.flatMap(m => m.globalRoutes ?? [])`) and never imports a module's pages, which
   * live in the module's directory, never under `frontend/src/pages/`. Omitted (or empty) for a module with no such
   * route. */
  globalRoutes?: TierAModuleRoute[];
  /** This module's org-admin `ResourceMenu` groups, merged into `OrgAdminPage.tsx`'s fixed core groups and filtered to
   * the organisation's enabled modules. Omitted (or empty) for a module with no organisation-level admin surface. */
  orgAdminSections?: OrgAdminSectionDef[];
  /** This module's `ResourceMenu` groups on `pages/ProjectAdminPage.tsx`, merged into that page's fixed groups and
   * filtered to the project's enabled modules, as `orgAdminSections` but scoped by `projectId` (a distinct interface
   * from `OrgAdminSectionDef`). Omitted (or empty) for a module with no project-level admin surface. */
  projectAdminSections?: ProjectAdminSectionDef[];
  /** This module's top-level nav-rail links, rendered in `Layout.tsx`'s "Global" section. Omitted (or empty) for a
   * module with no global tab. */
  globalNavItems?: GlobalNavItemDef[];
  /** This module's "standalone workspace" nav-rail sections, rendered beside `Layout.tsx`'s "Project" section when the
   * current path matches one. Omitted (or empty) for a module with no such entity. */
  standaloneWorkspaces?: StandaloneWorkspaceDef[];
  /** Widget types this module adds to the project overview's "Add widget" list, rendered by
   * `components/overview/OverviewWidgetGrid.tsx` through the registry; each is an ordinary widget the person can
   * place, size, hide or remove. Declared on the backend too (`ModuleDefinition.overview_widgets`). Omitted for a
   * module with no overview widget. */
  overviewWidgets?: ProjectOverviewWidgetDef[];
  /** This module's `ResourceMenu` sections on `pages/OrgResourcesPage.tsx` (Org Resources): the records and content an
   * organisation owns and shares with its projects (an organisation Strategy list, a request inbox, a status table over
   * every project). It has `OrgAdminSectionDef`'s shape, since both pages need a menu entry and the content to draw,
   * and is filtered to the organisation's enabled modules and sub-components as `orgAdminSections` is. Keys must be
   * unique across modules, distinct from the page's core sections (Reports, Tags) and from every `orgAdminSections`
   * key. Omitted for a module with no organisation-owned content. Configuration (vocabularies, scoring, defaults) stays
   * in `orgAdminSections`; computed figures are `orgOverviewWidgets`. */
  orgResourceSections?: OrgAdminSectionDef[];
  /** This module's widgets for an organisation's overview dashboards, offered only while the organisation has the
   * module enabled. Omitted (or empty) for a module with no organisation-level figures of its own. */
  orgOverviewWidgets?: OrgOverviewWidgetDef[];
  /** This module's extra sections on `pages/RequirementDetailPage.tsx`'s Links card, gated on the project's
   * `enabled-modules` list as `overviewWidgets` are. Omitted for a module with no requirement-detail contribution. */
  requirementDetailSections?: RequirementDetailSectionDef[];
  /** This module's accent colour for `.entity-accent-card` / `.entity-accent-row` styling (`styles/theme.css`): the
   * left-border stripe of a list row showing this module's entity kind among others (see
   * `modules/entityAccentColor.ts`). One literal hex pair per module, never a CSS variable in `theme.css`: a core file
   * must not carry a per-module colour token, the same boundary violation as a per-module value in a core enum
   * (CLAUDE.md "Modular Feature System Boundary"). `frontend/src/api/types.ts`'s `ENTITY_ACCENT_COLOR` holds only the
   * three core kinds (requirement, action, change_request). Keyed by this definition's `key` at the call site
   * (`useEntityAccentColor(moduleKey)`), since a module contributes one entity kind. Omitted for a module with no
   * entity shown in a mixed list (falls back to neutral grey). */
  entityAccentColor?: { light: string; dark: string };
  /** Where each of this module's artefact types has its detail page, keyed by the backend's artefact-type string (e.g.
   * `"pain_point"`), so another module's relationship list can link to a record it does not own
   * (`modules/artefactPaths.ts`, the frontend counterpart of the backend's `artefact_summary_providers`). Omitted for a
   * module whose records nothing else links to. */
  artefactPaths?: Record<string, (projectId: string, id: string) => string>;
  /** Where a notification kind only this module can open leads, keyed by the target kind the backend's
   * `ModuleDefinition.notification_target_kinds` declares (e.g. `"standard"`): given the notification, the page to
   * open, or `null` when it lacks the data (the next kind its type lists is then tried). Core never names these kinds
   * (`modules/notificationTargets.ts`). Omitted for a module that declares none. */
  notificationTargets?: Record<string, (notification: Notification) => string | null>;
  /** Record types this module can create from another record's Links panel, keyed by artefact type (e.g.
   * `"pain_point"`): the panel offers "Create new" for a type a link type from the page's record reaches (the server
   * has left out types of a module or sub-component that is off), shows the module's create dialog and links the new
   * record. The module owns the dialog, its validation and permission errors (`modules/linkedRecordCreators.ts`). */
  linkedRecordCreators?: Record<string, LinkedRecordCreator>;
  /** The relationship this module's records prefer when another record is created and linked from their Links panel
   * (`linkedRecordCreators`), keyed by this module's artefact type then the other record's type, as it reads from this
   * record (its `phrase`, e.g. `"Addresses"`). Several relationships can reach a type and only the owner of the page's
   * record knows which carries meaning; the person can pick another. Omitted where the first specific one will do. */
  preferredLinkPhrases?: Record<string, Record<string, string>>;
  /** Where each of this module's artefact types has its list page in a project, keyed by artefact type
   * (`modules/artefactPaths.ts`'s `getArtefactListPath`), so core views that summarise records by type (the project
   * overview's total-records chart) can open a list without naming a module's URL. A type with no list page names the
   * page it appears on. */
  artefactListPaths?: Record<string, (projectId: string) => string>;
  /** Where each of this module's organisation-owned artefact types with an organisation-level page opens, keyed by
   * artefact type. The global search uses it for a result that belongs to the organisation and was not found through
   * a project (`modules/artefactPaths.ts`'s `getSearchHitPath`). Omitted for a module with no such type. */
  orgArtefactPaths?: Record<string, (organizationId: string, id: string) => string>;
  /** Display labels for the lifecycle status of each of this module's artefact types, keyed by artefact type then
   * backend status string, so the shared Links panel shows a linked record's status without a raw enum string
   * (`modules/artefactPaths.ts`'s `getArtefactStatusLabel`). Omitted for a module whose records carry no status; a
   * type or status with no entry shows no badge. */
  artefactStatusLabels?: Record<string, Record<string, string>>;
  /** Statuses that mean a record is no longer live (superseded, retired, rejected, withdrawn...), keyed by artefact
   * type, for the views that offer to hide such records (the link trace). A type with no entry is never inactive by
   * status; an archived record is inactive whatever its status. Resolved by `modules/artefactPaths.ts`'s
   * `isArtefactInactive`. */
  artefactInactiveStatuses?: Record<string, string[]>;
  /** Extra scopes this module adds to the global search's Scope filter (Compliance: one standard), the frontend half
   * of the backend's `ModuleDefinition.search_scopes`. Core asks every registered `match` which scopes apply to the
   * page the viewer is on (`modules/searchScopes.ts`). Omitted for a module with no such unit. */
  searchScopes?: SearchScopeDefinition[];
  /** Custom on-screen views for this module's reports, keyed by the backend `ReportDefinition.key`. The Reports pages
   * render `ReportViewer` (a generic table view) for any report with no entry here, so a module adds a view only where
   * a table fails the reader. Core resolves it through `getReportView` in `registry.ts` and never imports a view. */
  reportViews?: Record<string, ReportViewDef>;
}
