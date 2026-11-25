import { BarChart3, Building2, CalendarClock, CheckSquare, Clock, Files, History, HelpCircle, Layers, Library, LayoutDashboard, ListChecks, Settings, LogOut, GitPullRequest, FolderKanban, PanelLeftClose, PanelLeftOpen, Star, Wrench } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { fileUrl } from "../api/client";
import builtInLogo from "../assets/logo.svg";
import { useAuth } from "../context/AuthContext";
import { BrandingProvider, useBranding, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { FavouritesProvider, useFavourites } from "../context/FavouritesContext";
import { NavLabelProvider } from "../context/NavLabelContext";
import { useNavLabeler } from "../context/NavLabelValue";
import { PolicyAcceptanceProvider } from "../context/PolicyAcceptanceContext";
import { TerminologyProvider, useStrings } from "../context/TerminologyContext";
import { useClientConfig } from "../hooks/useClientConfig";
import { useHasReviewsDue } from "../hooks/useHasReviewsDue";
import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { useServerAccess } from "../hooks/useServerAccess";
import { useProjectEnabledModules } from "../hooks/useProjectEnabledModules";
import { useProjectHasStages } from "../hooks/useProjectHasStages";
import { useUiPreference } from "../hooks/useUiPreference";
import { resolveNavIcon } from "../modules/navIcons";
import type { ProjectNavItem } from "../navigation/projectNav";
import { installedModules } from "../modules/registry";
import { AnnouncementBanner } from "./AnnouncementBanner";
import { AppFooter } from "./AppFooter";
import { HeaderSearch } from "./HeaderSearch";
import { NotificationBell } from "./NotificationBell";
import { ReportRunsIndicator } from "./ReportRunsIndicator";
import { NavGroup } from "./NavGroup";
import { NavRailLink } from "./NavRailLink";
import { PolicyAcceptNotice } from "./PolicyAcceptNotice";
import { ProjectNavSection } from "./ProjectNavSection";
import { Tooltip } from "./Tooltip";

// Matches theme.css's `@media (max-width: 860px)` nav-rail breakpoint, which force-collapses the rail to icons
// regardless of the `nav_rail_collapsed` preference. Anything deciding "is the rail icon-only now" must include
// this CSS-only collapse (see `railIconOnly`), or links get no tooltips once CSS has forced them to icons.
const MOBILE_BREAKPOINT_PX = 860;

/**
 * App shell: a fixed top bar plus a pinned, full-height nav rail (U-P-02, U-P-03). Project-scoped links render only
 * once a project is selected (path contains /projects/:id). The rail uses the theme's surface colours, with a
 * project-context group above a global group, is `position: fixed` against the left edge below the header and
 * stays on screen while the content scrolls. `railCollapsed` shrinks it to icons, toggled from a small circular
 * button (`btn btn-icon btn-sm btn-round`) fixed to the viewport and centred on the rail/content divider, so it
 * stays put whatever the rail scroll or content length. Its `left` is set inline from `railCollapsed`
 * (`var(--nav-rail-width)` / `var(--nav-rail-width-collapsed)`, the tokens `.app-content`'s margin uses) because
 * the button renders inside `Tooltip`'s wrapping span and is not a DOM sibling of `.nav-rail`. The choice persists
 * through `useUiPreference` (`nav_rail_collapsed`) across devices.
 * `contentBoxed` (`useUiPreference("content_boxed", false)`) is a second display preference: content fills the
 * space beside the rail, or is capped and centred at 1200px. Wraps content in `TerminologyProvider` (C-C-03) so the
 * nav labels and every page in `children` resolve the project's terminology overrides.
 */
export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  return (
    <TerminologyProvider projectId={projectId}>
      <BrandingProvider projectId={projectId}>
        <NavLabelProvider projectId={projectId}>
          <FavouritesProvider>
            <PolicyAcceptanceProvider>
              <LayoutShell>{children}</LayoutShell>
            </PolicyAcceptanceProvider>
          </FavouritesProvider>
        </NavLabelProvider>
      </BrandingProvider>
    </TerminologyProvider>
  );
}

function LayoutShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const strings = useStrings();
  const navLabel = useNavLabeler();
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useUiPreference<boolean>("nav_rail_collapsed", false);
  const isNarrowViewport = useNarrowViewport(MOBILE_BREAKPOINT_PX);
  // Whether the rail is rendering icon-only now, by preference or because the viewport is narrower than
  // `MOBILE_BREAKPOINT_PX`: the value every nav-rail-link tooltip decision uses instead of the raw preference.
  const railIconOnly = railCollapsed || isNarrowViewport;
  const [contentBoxed] = useUiPreference<boolean>("content_boxed", false);
  const branding = useBranding();
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();
  // Reactive to a favourite being toggled anywhere in the app, not just on
  // arrival at /projects or /favourites — see `FavouritesContext`.
  const { hasFavourites } = useFavourites();
  const hasReviewsDue = useHasReviewsDue(!!user);
  const serverAccess = useServerAccess(!!user);
  const showServerManagement = !!serverAccess && (serverAccess.can_administer_server || serverAccess.can_manage_entitlements);
  const clientConfig = useClientConfig(!!user);

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;
  const { modules: enabledModules } = useProjectEnabledModules(projectId);
  // Delivery status has nothing to show until the project goes beyond its default stage, so its entry waits for that.
  const hasStages = useProjectHasStages(projectId ?? null);
  // Every installed module's top-level nav links (`globalNavItems`) and "standalone workspace" nav sections
  // (`standaloneWorkspaces`, `modules/types.ts`): a generic registration, so core hardcodes no module's UI
  // (as `orgAdminSections` for `OrgAdminPage.tsx`). Each global nav item owns its visibility (returns `null` when
  // not applicable), so every one renders unconditionally. At most one standalone workspace is active: the first
  // (in installed-module order) whose `matchPath` matches the current path, as the "Project" section above is
  // gated on a single regex match.
  const globalNavItems = installedModules.flatMap((m) => m.globalNavItems ?? []);
  let activeStandaloneWorkspace: { entityId: string; render: (props: { entityId: string; railCollapsed: boolean }) => ReactNode } | null = null;
  for (const workspace of installedModules.flatMap((m) => m.standaloneWorkspaces ?? [])) {
    const match = workspace.matchPath.exec(location.pathname);
    if (match?.[1]) {
      activeStandaloneWorkspace = { entityId: match[1], render: workspace.render };
      break;
    }
  }

  // The Project nav section's items in product-default order: the core work items, then one per (module, nav
  // entry) pair for every enabled module with a frontend manifest (Tier A or B). A module whose manifest the server
  // rejected (a Tier B frame_url outside the allowlist) has no entry. History and Project admin come last.
  // `ProjectNavSection` applies the user's order and "More" preference without knowing what any item is.
  const projectNavItems: ProjectNavItem[] = projectId
    ? [
        { key: "overview", to: `/projects/${projectId}`, exact: true, label: navLabel(`/projects/${projectId}`, strings.nav.overview), icon: <LayoutDashboard size={16} /> },
        { key: "requirements", to: `/projects/${projectId}/requirements`, label: navLabel(`/projects/${projectId}/requirements`, strings.nav.requirements), icon: <ListChecks size={16} /> },
        { key: "change-requests", to: `/projects/${projectId}/change-requests`, label: navLabel(`/projects/${projectId}/change-requests`, strings.nav.changeRequests), icon: <GitPullRequest size={16} /> },
        { key: "actions", to: `/projects/${projectId}/actions`, label: navLabel(`/projects/${projectId}/actions`, strings.nav.actions), icon: <CheckSquare size={16} /> },
        { key: "files", to: `/projects/${projectId}/files`, label: navLabel(`/projects/${projectId}/files`, strings.files.title), icon: <Files size={16} /> },
        { key: "reviews-due", to: `/projects/${projectId}/reviews-due`, label: navLabel(`/projects/${projectId}/reviews-due`, strings.reviews.projectTitle), icon: <Clock size={16} /> },
        ...enabledModules.flatMap((moduleEntry) => {
          const manifest = moduleEntry.frontend_manifest;
          if (!manifest) return [];
          const entries = [
            {
              nav_label: manifest.nav_label, nav_path: manifest.nav_path, nav_icon: manifest.nav_icon,
              sub_component: manifest.nav_sub_component, sub_components_any: manifest.nav_sub_components_any,
            },
            ...(manifest.additional_nav_entries ?? []),
          ];
          // An entry whose sub-component is off for this project is hidden: its API routes 404, so the
          // link would lead to a page that cannot load. A page serving several sub-components
          // (`sub_components_any`) goes only when all of them are off. Generic; no module is named here.
          const disabled = moduleEntry.disabled_sub_components ?? [];
          const visible = (entry: (typeof entries)[number]) =>
            (!entry.sub_component || !disabled.includes(entry.sub_component)) &&
            (!entry.sub_components_any?.length || entry.sub_components_any.some((key) => !disabled.includes(key)));
          return entries.filter(visible).map((entry) => {
            const EntryIcon = resolveNavIcon(entry.nav_icon);
            return {
              key: `${moduleEntry.module_key}:${entry.nav_path}`,
              to: entry.nav_path,
              label: navLabel(entry.nav_path, entry.nav_label),
              icon: <EntryIcon size={16} />,
            };
          });
        }),
        ...(hasStages
          ? [{ key: "stage-phases", to: `/projects/${projectId}/stage-phases`, label: navLabel(`/projects/${projectId}/stage-phases`, strings.stagePhases.title), icon: <Layers size={16} /> }]
          : []),
        { key: "history", to: `/projects/${projectId}/history`, label: navLabel(`/projects/${projectId}/history`, strings.history.title), icon: <History size={16} /> },
        { key: "admin", to: `/projects/${projectId}/admin`, label: navLabel(`/projects/${projectId}/admin`, strings.nav.admin), icon: <Settings size={16} /> },
      ]
    : [];

  return (
    <div style={{ minHeight: "100%" }}>
      {user && <AnnouncementBanner organizationId={branding.organizationId} />}
      {user && <PolicyAcceptNotice />}
      <header className="app-header" style={{ justifyContent: "space-between" }}>
        <Link
          to="/projects"
          className="row"
          style={{ fontWeight: 700, textDecoration: "none", color: "var(--color-header-text)", gap: "var(--space-3)" }}
        >
          {/* U-C-02: resolved org/platform branding (BrandingContext) — an
              org's own logo/title, falling back to the platform default,
              falling back again to the built-in logo mark. */}
          <img
            src={branding.logoFileId ? fileUrl(branding.logoFileId) : builtInLogo}
            alt=""
            style={{ height: 24 }}
          />
          {branding.headerTitle}
        </Link>
        {user && (
          <div className="row">
            <HeaderSearch />
            <ReportRunsIndicator />
            <NotificationBell />
            {clientConfig?.help_enabled && (
              <Tooltip label={strings.nav.help}>
                <a
                  href={clientConfig.help_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn"
                  aria-label={strings.nav.helpNewTab}
                >
                  <HelpCircle />
                </a>
              </Tooltip>
            )}
            <Tooltip label={strings.nav.preferences}>
              <Link
                to="/preferences"
                className="row"
                style={{ color: "var(--color-header-text)", textDecoration: "none", gap: "var(--space-2)" }}
                title={strings.nav.preferences}
                aria-label={`${user.display_name} — ${strings.nav.preferences}`}
              >
                {user.display_name}
              </Link>
            </Tooltip>
            <Tooltip label={strings.nav.signOut}>
              <button className="btn" onClick={logout} aria-label={strings.nav.signOut}>
                <LogOut />
              </button>
            </Tooltip>
          </div>
        )}
      </header>
      {user && (
        <nav
          className={`nav-rail ${railIconOnly ? "nav-rail-icons" : ""}`}
        >
          {/* The item list is the scroll container; it leaves the strip under the fixed collapse
              toggle free so neither a link nor the scrollbar runs under it (see `.nav-rail-scroll`, theme.css). */}
          <div className="nav-rail-scroll stack" style={{ gap: "0.15rem" }}>
            {projectId && <ProjectNavSection projectId={projectId} items={projectNavItems} railCollapsed={railIconOnly} />}
            {/* A module-contributed "standalone workspace" section, a sibling of "Project" above, not nested in it
                (see `activeStandaloneWorkspace`). */}
            {activeStandaloneWorkspace &&
              activeStandaloneWorkspace.render({ entityId: activeStandaloneWorkspace.entityId, railCollapsed: railIconOnly })}
            <NavGroup groupKey="global" label="Global" railCollapsed={railIconOnly}>
              <NavRailLink to="/projects" exact label={strings.nav.projects} icon={<FolderKanban size={16} />} railCollapsed={railIconOnly} />
              {/* "Files" — the files of every project the person can open in their organisation. Shown to every
                  member, as the page is (it lists only files the caller may see); `/org-files` resolves the
                  organisation the way `/org-overview` does, and the entry stays active on the page itself. */}
              <NavRailLink to="/org-files" exact alsoActiveOn={/^\/orgs\/[^/]+\/files(\/|$)/} label={strings.files.title} icon={<Files size={16} />} railCollapsed={railIconOnly} />
              {/* Module-contributed top-level nav links; each item owns its visibility and may render nothing (see
                  `globalNavItems`). */}
              {globalNavItems.map((item) => (
                <Fragment key={item.key}>{item.render({ railCollapsed: railIconOnly })}</Fragment>
              ))}
              {hasFavourites && (
                <NavRailLink to="/favourites" exact label={strings.nav.favourites} icon={<Star size={16} />} railCollapsed={railIconOnly} />
              )}
              {/* Shown only when a review is due (`useHasReviewsDue`); the page stays reachable by address and from
                  notifications. The full Notifications page has no entry here: the header bell links to it. */}
              {hasReviewsDue && (
                <NavRailLink to="/my-reviews" label={strings.nav.myReviews} icon={<CalendarClock size={16} />} railCollapsed={railIconOnly} />
              )}
              {/* "Organisation Overview": a core, always-visible nav-rail link carrying general org stats every
                  organisation has, shown unconditionally like the Projects link above (docs/decisions.md,
                  "Compliance module, human review follow-ups"). `/org-overview` reuses `OrgListPage`'s
                  single-org/multi-org auto-redirect, as `/orgs` does for org admin. */}
              <NavRailLink to="/org-overview" exact alsoActiveOn={/^\/orgs\/[^/]+\/overview(\/|$)/} label={strings.nav.orgOverview(orgLabelCap)} icon={<BarChart3 size={16} />} railCollapsed={railIconOnly} />
              {/* "Org Resources" — the records and content the organisation shares with its projects; its sections
                  are contributed through the module registry (`orgResourceSections`), so this entry names no module. */}
              <NavRailLink to="/org-resources" exact alsoActiveOn={/^\/orgs\/[^/]+\/resources(\/|$)/} label={strings.nav.orgResources(orgLabelCap)} icon={<Library size={16} />} railCollapsed={railIconOnly} />
              {/* The path to org administration for anyone but a server admin (who drills in through
                  /server/organisations): /orgs auto-redirects to a single org's admin page or lists every org the
                  user belongs to. See docs/ux-style-guide.md, "Pattern: wayfinding". */}
              <NavRailLink to="/orgs" exact label={strings.nav.orgSettings(orgLabelCap)} icon={<Building2 size={16} />} railCollapsed={railIconOnly} />
            </NavGroup>
            {/* Each entry shows only to someone the server says may use it (`useServerAccess`): a Platform
                subscription manager or Subscription removal authority sees Organisations, a Module administrator
                sees Server management (Modules only), a server administrator sees both. */}
            {serverAccess && (serverAccess.can_view_organizations || showServerManagement) && (
              <NavGroup groupKey="administration" label="Administration" railCollapsed={railIconOnly}>
                {serverAccess.can_view_organizations && (
                  <NavRailLink to="/server/organisations" label={strings.orgAdmin.organizations(orgLabelPlural)} icon={<Building2 size={16} />} railCollapsed={railIconOnly} />
                )}
                {showServerManagement && (
                  <NavRailLink to="/server/management" label={strings.nav.serverManagement} icon={<Wrench size={16} />} railCollapsed={railIconOnly} />
                )}
              </NavGroup>
            )}
          </div>
        </nav>
      )}
      {user && (
        <Tooltip
          label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
          className="nav-rail-toggle-wrapper"
          style={{ left: `var(${railCollapsed ? "--nav-rail-width-collapsed" : "--nav-rail-width"})` }}
        >
          <button
            className="btn btn-icon btn-sm btn-round"
            onClick={() => setRailCollapsed(!railCollapsed)}
            aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
          >
            {railCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </button>
        </Tooltip>
      )}
      <main className={`app-content${contentBoxed ? " boxed" : ""}`}>
        <div className="app-content-body">
          {contentBoxed ? <div className="content-inner">{children}</div> : children}
        </div>
        <AppFooter />
      </main>
    </div>
  );
}
