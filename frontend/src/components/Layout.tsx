import { BarChart3, Bell, Building2, CalendarClock, CheckSquare, Clock, Files, History, HelpCircle, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban, PanelLeftClose, PanelLeftOpen, Star, Wrench } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type { SystemVersion } from "../api/types";
import builtInLogo from "../assets/logo.svg";
import { useAuth } from "../context/AuthContext";
import { BrandingProvider, useBranding, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { FavouritesProvider, useFavourites } from "../context/FavouritesContext";
import { TerminologyProvider, useStrings } from "../context/TerminologyContext";
import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { useProjectEnabledModules } from "../hooks/useProjectEnabledModules";
import { useUiPreference } from "../hooks/useUiPreference";
import { resolveNavIcon } from "../modules/navIcons";
import type { ProjectNavItem } from "../navigation/projectNav";
import { installedModules } from "../modules/registry";
import { APP_VERSION, BUILD_DATE, GIT_SHA } from "../version";
import { NotificationBell } from "./NotificationBell";
import { NavRailLink } from "./NavRailLink";
import { ProjectNavSection } from "./ProjectNavSection";
import { Tooltip } from "./Tooltip";

// Matches theme.css's `@media (max-width: 860px)` nav-rail breakpoint, which force-collapses
// the rail to icon-only regardless of the user's own `nav_rail_collapsed` preference (not
// enough room for a full-width rail alongside content below this width). Anything that decides
// "is the rail showing icon-only right now" needs to account for this CSS-only forced
// collapse too, not just the JS preference (see `railIconOnly` below) — otherwise a user with
// the rail set to expanded gets no tooltips once the CSS has forced their links to icons.
const MOBILE_BREAKPOINT_PX = 860;

/**
 * App shell: a fixed top bar plus a pinned, full-height nav rail (U-P-02,
 * U-P-03). Project-scoped links only render once a project is selected
 * (path contains /projects/:id). The nav rail uses the same theme-aware
 * surface colours as the rest of the UI (--color-surface/-text/etc in
 * theme.css), with a project-context group above a global group. The rail
 * is `position: fixed` against the true left edge, full viewport height
 * below the header, and stays on-screen while the content column scrolls
 * (rather than living inside the same centred/padded container as the
 * page content). `railCollapsed` shrinks it to icons-only, toggled from a
 * small circular button (`.nav-rail-toggle`, theme.css) fixed to the
 * viewport and centred on the rail/content divider, not part of the
 * rail's own scrolling content, so it stays put regardless of rail scroll
 * position or content length. Its `left` is set inline here from
 * `railCollapsed` (`var(--nav-rail-width)` / `var(--nav-rail-width-
 * collapsed)`, the same tokens `.app-content`'s own margin uses) rather
 * than via a CSS sibling selector on `.nav-rail`, because the button
 * renders inside `Tooltip`'s own wrapping span and so isn't actually a
 * DOM sibling of `.nav-rail` — the header's hamburger button was removed
 * as a pure duplicate of that same control — and persisted via
 * `useUiPreference` (`nav_rail_collapsed`)
 * so it follows the user across devices the same way their theme/
 * landing-page choices already do.
 * `contentBoxed` (`useUiPreference("content_boxed", false)`) is a second,
 * independent display preference: content fills the space next to the
 * rail by default, or a user can opt into the previous capped/centred
 * 1200px width from Preferences. Wraps content in `TerminologyProvider`
 * (C-C-03) so the nav labels below and every page rendered as `children`
 * can resolve the current project's terminology overrides.
 */
export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  return (
    <TerminologyProvider projectId={projectId}>
      <BrandingProvider projectId={projectId}>
        <FavouritesProvider>
          <LayoutShell>{children}</LayoutShell>
        </FavouritesProvider>
      </BrandingProvider>
    </TerminologyProvider>
  );
}

function LayoutShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const strings = useStrings();
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useUiPreference<boolean>("nav_rail_collapsed", false);
  const isNarrowViewport = useNarrowViewport(MOBILE_BREAKPOINT_PX);
  // Whether the rail is actually rendering icon-only right now, whether that's
  // by the user's own preference or because the viewport is too narrow for a
  // full-width rail (see `MOBILE_BREAKPOINT_PX` above) — the value every
  // nav-rail-link tooltip decision should use instead of the raw preference.
  const railIconOnly = railCollapsed || isNarrowViewport;
  const [contentBoxed] = useUiPreference<boolean>("content_boxed", false);
  const branding = useBranding();
  const orgLabelPlural = useOrgLabelPlural();
  const orgLabelCap = useOrgLabelCapitalized();
  // Reactive to a favourite being toggled anywhere in the app, not just on
  // arrival at /projects or /favourites — see `FavouritesContext`.
  const { hasFavourites } = useFavourites();
  const [backendVersion, setBackendVersion] = useState<SystemVersion | null>(null);

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;
  const { modules: enabledModules } = useProjectEnabledModules(projectId);
  // Every installed module's own top-level nav links (`globalNavItems`) and
  // "standalone workspace" nav sections (`standaloneWorkspaces`,
  // `modules/types.ts`) — a generic mechanism a module registers into
  // (compliance-module-plan.md Phase 18 is its first user, "Compliance
  // Standards"/"Standard"), the same "core doesn't hardcode a specific
  // module's UI" boundary `orgAdminSections` already establishes for
  // `OrgAdminPage.tsx`. Each global nav item owns its own visibility
  // (returns `null` when not applicable, e.g. Compliance's own nav-
  // visibility check) — `Layout.tsx` invites every one of them to render
  // unconditionally rather than deciding on any module's behalf. At most
  // one standalone workspace is active at a time: the first one (in
  // installed-module order) whose own `matchPath` matches the current
  // path, mirroring how the "Project" section above is likewise gated on a
  // single regex match rather than several independent ones.
  const globalNavItems = installedModules.flatMap((m) => m.globalNavItems ?? []);
  let activeStandaloneWorkspace: { entityId: string; render: (props: { entityId: string; railCollapsed: boolean }) => ReactNode } | null = null;
  for (const workspace of installedModules.flatMap((m) => m.standaloneWorkspaces ?? [])) {
    const match = workspace.matchPath.exec(location.pathname);
    if (match?.[1]) {
      activeStandaloneWorkspace = { entityId: match[1], render: workspace.render };
      break;
    }
  }

  // The Project nav section's items, in product-default order: the core entries, then one per
  // (module, nav entry) pair for every currently-enabled module that declares a frontend
  // manifest, Tier A or Tier B alike (compliance-module-plan.md Phase 3; several entries per
  // module since Module 1 — Context & Strategy — Phase 7.1). A module whose manifest was
  // rejected (e.g. a Tier B frame_url outside the deployment's allowlist) simply has no entry,
  // since `get_frontend_manifest` already omitted it server-side. `ProjectNavSection` applies
  // the user's order/"More" preference to this list without knowing what any item is.
  const projectNavItems: ProjectNavItem[] = projectId
    ? [
        { key: "overview", to: `/projects/${projectId}`, exact: true, label: strings.nav.overview, icon: <LayoutDashboard size={16} /> },
        { key: "requirements", to: `/projects/${projectId}/requirements`, label: strings.nav.requirements, icon: <ListChecks size={16} /> },
        { key: "change-requests", to: `/projects/${projectId}/change-requests`, label: strings.nav.changeRequests, icon: <GitPullRequest size={16} /> },
        { key: "actions", to: `/projects/${projectId}/actions`, label: strings.nav.actions, icon: <CheckSquare size={16} /> },
        { key: "files", to: `/projects/${projectId}/files`, label: strings.files.title, icon: <Files size={16} /> },
        { key: "reports", to: `/projects/${projectId}/reports`, label: strings.nav.reports, icon: <FileText size={16} /> },
        { key: "reviews-due", to: `/projects/${projectId}/reviews-due`, label: strings.reviews.projectTitle, icon: <Clock size={16} /> },
        { key: "history", to: `/projects/${projectId}/history`, label: strings.history.title, icon: <History size={16} /> },
        { key: "admin", to: `/projects/${projectId}/admin`, label: strings.nav.admin, icon: <Settings size={16} /> },
        ...enabledModules.flatMap((moduleEntry) => {
          const manifest = moduleEntry.frontend_manifest;
          if (!manifest) return [];
          const entries = [
            { nav_label: manifest.nav_label, nav_path: manifest.nav_path, nav_icon: manifest.nav_icon },
            ...(manifest.additional_nav_entries ?? []),
          ];
          return entries.map((entry) => {
            const EntryIcon = resolveNavIcon(entry.nav_icon);
            return {
              key: `${moduleEntry.module_key}:${entry.nav_path}`,
              to: entry.nav_path,
              label: entry.nav_label,
              icon: <EntryIcon size={16} />,
            };
          });
        }),
      ]
    : [];

  useEffect(() => {
    if (!user) return;
    api.get<SystemVersion>("/api/v1/system/version").then(setBackendVersion);
  }, [user]);

  return (
    <div style={{ minHeight: "100%" }}>
      <header className="app-header" style={{ justifyContent: "space-between" }}>
        <Link
          to="/projects"
          className="row"
          style={{ fontWeight: 700, textDecoration: "none", color: "var(--color-header-text)", gap: "0.5rem" }}
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
            <NotificationBell />
            <Tooltip label={strings.nav.help}>
              <Link to="/help" className="btn" aria-label={strings.nav.help}>
                <HelpCircle size={16} />
              </Link>
            </Tooltip>
            <Tooltip label={strings.nav.preferences}>
              <Link
                to="/preferences"
                className="row"
                style={{ color: "var(--color-header-text)", textDecoration: "none", gap: "0.4rem" }}
                title={strings.nav.preferences}
                aria-label={`${user.display_name} — ${strings.nav.preferences}`}
              >
                {user.display_name}
              </Link>
            </Tooltip>
            <Tooltip label={strings.nav.signOut}>
              <button className="btn" onClick={logout} aria-label={strings.nav.signOut}>
                <LogOut size={16} />
              </button>
            </Tooltip>
          </div>
        )}
      </header>
      {user && (
        <nav
          className={`nav-rail stack ${railIconOnly ? "nav-rail-icons" : ""}`}
          style={{ gap: "0.15rem" }}
        >
          {projectId && <ProjectNavSection projectId={projectId} items={projectNavItems} railCollapsed={railIconOnly} />}
          {/* A module-contributed "standalone workspace" section (Phase
              18's "Standard" is the first one) — a sibling structural
              pattern to "Project" above, not nested inside it. See this
              file's own `activeStandaloneWorkspace` computation above. */}
          {activeStandaloneWorkspace &&
            activeStandaloneWorkspace.render({ entityId: activeStandaloneWorkspace.entityId, railCollapsed: railIconOnly })}
          <div className="nav-section-label">Global</div>
          <NavRailLink to="/projects" exact label={strings.nav.projects} icon={<FolderKanban size={16} />} railCollapsed={railIconOnly} />
          {/* "Organisation Overview" (Phase 19) — a core, always-visible
              nav-rail link (unlike Phase 18's "Compliance Standards" tab
              below, this one carries general-purpose org stats every org
              has regardless of compliance, so it's shown unconditionally,
              the same precedent as the always-shown Projects link above —
              see docs/decisions.md's "Compliance module, human review
              follow-ups" entry). `/org-overview` reuses `OrgListPage`'s own
              single-org/multi-org auto-redirect convention as its entry
              point, the same way `/orgs` already does for org admin. */}
          <NavRailLink to="/org-overview" exact label={strings.nav.orgOverview(orgLabelCap)} icon={<BarChart3 size={16} />} railCollapsed={railIconOnly} />
          {/* Module-contributed top-level nav links (Phase 18's "Compliance
              Standards" is the first one) — each item owns its own
              visibility and may render nothing at all; see this file's own
              `globalNavItems` computation above. */}
          {globalNavItems.map((item) => (
            <Fragment key={item.key}>{item.render({ railCollapsed: railIconOnly })}</Fragment>
          ))}
          {hasFavourites && (
            <NavRailLink to="/favourites" exact label={strings.nav.favourites} icon={<Star size={16} />} railCollapsed={railIconOnly} />
          )}
          <NavRailLink to="/my-reviews" label={strings.nav.myReviews} icon={<CalendarClock size={16} />} railCollapsed={railIconOnly} />
          <NavRailLink to="/notifications" exact label={strings.notifications.title} icon={<Bell size={16} />} railCollapsed={railIconOnly} />
          {/* The only path to org administration (U-P-02-adjacent IA gap
              found in the 2026-08 UX audit): /orgs already auto-redirects
              straight to a single org's admin page, or lists every org a
              user belongs to otherwise — it just had no rail entry before
              this, for anyone but a server admin drilling in through
              /server/organisations. See docs/ux-style-guide.md, "Pattern:
              wayfinding". */}
          <NavRailLink to="/orgs" exact label={strings.nav.myOrganizations(orgLabelPlural)} icon={<Building2 size={16} />} railCollapsed={railIconOnly} />
          {user.is_server_admin && (
            <>
              <div className="nav-section-label">Administration</div>
              <NavRailLink to="/server/organisations" label={strings.orgAdmin.organizations(orgLabelPlural)} icon={<Building2 size={16} />} railCollapsed={railIconOnly} />
              <NavRailLink to="/server/management" label={strings.nav.serverManagement} icon={<Wrench size={16} />} railCollapsed={railIconOnly} />
            </>
          )}
          {/* Build identity — "a way to see the version and date of the
              frontend and backend in the UI" (2026-08 UX audit follow-up).
              Pinned to the bottom of the rail via `marginTop: auto` on the
              flex-column `<nav>`; hidden in icon-only mode rather than
              squeezed into it, same as every other rail label. The sha/date
              detail lives in `title` (plain hover text, not the shared
              `Tooltip`) since this is supplementary static text, not an
              interactive control needing an accessible name. */}
          {!railIconOnly && (
            <div
              className="text-muted"
              style={{ marginTop: "auto", paddingTop: "0.75rem", fontSize: "0.7rem", lineHeight: 1.6 }}
            >
              <div title={strings.nav.frontendBuildDetail(GIT_SHA, BUILD_DATE)}>{strings.nav.frontendVersion(APP_VERSION)}</div>
              <div title={backendVersion ? strings.nav.backendBuildDetail(backendVersion.git_sha, backendVersion.build_date) : undefined}>
                {backendVersion ? strings.nav.backendVersion(backendVersion.version) : strings.nav.backendVersionLoading}
              </div>
            </div>
          )}
        </nav>
      )}
      {user && (
        <Tooltip
          label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
          className="nav-rail-toggle-wrapper"
          style={{ left: `var(${railCollapsed ? "--nav-rail-width-collapsed" : "--nav-rail-width"})` }}
        >
          <button
            className="btn nav-rail-toggle"
            onClick={() => setRailCollapsed(!railCollapsed)}
            aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
          >
            {railCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </Tooltip>
      )}
      <main className={`app-content${contentBoxed ? " boxed" : ""}`}>
        {contentBoxed ? <div className="content-inner">{children}</div> : children}
      </main>
    </div>
  );
}
