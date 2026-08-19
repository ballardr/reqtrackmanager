import { Bell, Building2, CalendarClock, CheckSquare, Clock, History, HelpCircle, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban, PanelLeftClose, PanelLeftOpen, Star, Wrench } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type { ProjectListItem, SystemVersion } from "../api/types";
import builtInLogo from "../assets/logo.svg";
import { useAuth } from "../context/AuthContext";
import { BrandingProvider, useBranding, useOrgLabelPlural } from "../context/BrandingContext";
import { TerminologyProvider, useStrings } from "../context/TerminologyContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { APP_VERSION, BUILD_DATE, GIT_SHA } from "../version";
import { NotificationBell } from "./NotificationBell";
import { Tooltip } from "./Tooltip";

/**
 * One nav-rail row. The tooltip only wraps the link while the rail is
 * collapsed to icons-only — while expanded, the link already shows its own
 * text label (`nav-label`), so a hover tooltip repeating that same text is
 * pure noise, exactly the complaint that motivated this. `.nav-link` itself
 * is `width: 100%` (see theme.css) so the whole row is clickable/highlit,
 * not just the icon+text's own shrink-wrapped width.
 */
function NavRailLink({
  to, label, icon, exact = false, railCollapsed,
}: { to: string; label: string; icon: ReactNode; exact?: boolean; railCollapsed: boolean }) {
  const location = useLocation();
  const active = exact ? location.pathname === to : location.pathname.startsWith(to);
  const link = (
    <Link to={to} className={`nav-link${active ? " active" : ""}`} aria-label={label}>
      {icon} <span className="nav-label">{label}</span>
    </Link>
  );
  return railCollapsed ? <Tooltip label={label}>{link}</Tooltip> : link;
}

/**
 * App shell: a fixed top bar plus a pinned, full-height nav rail (U-P-02,
 * U-P-03). Project-scoped links only render once a project is selected
 * (path contains /projects/:id). The nav rail uses the same theme-aware
 * surface colours as the rest of the UI (--color-surface/-text/etc in
 * theme.css), with a project-context group above a global group. The rail
 * is `position: fixed` against the true left edge, full viewport height
 * below the header, and stays on-screen while the content column scrolls
 * (rather than living inside the same centred/padded container as the
 * page content). `railCollapsed` shrinks it to icons-only, toggled from
 * the icon button pinned top-right of the rail (above the section links,
 * so it's reachable without scrolling past a long project section first)
 * — the header's hamburger button was removed as a pure duplicate of that
 * same control — and persisted via `useUiPreference` (`nav_rail_collapsed`)
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
        <LayoutShell>{children}</LayoutShell>
      </BrandingProvider>
    </TerminologyProvider>
  );
}

function LayoutShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const strings = useStrings();
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useUiPreference<boolean>("nav_rail_collapsed", false);
  const [contentBoxed] = useUiPreference<boolean>("content_boxed", false);
  const branding = useBranding();
  const orgLabelPlural = useOrgLabelPlural();
  const [hasFavourites, setHasFavourites] = useState(false);
  const [backendVersion, setBackendVersion] = useState<SystemVersion | null>(null);

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  const onFavouritableRoute = location.pathname === "/projects" || location.pathname === "/favourites";

  useEffect(() => {
    if (!user) return;
    api.get<SystemVersion>("/api/v1/system/version").then(setBackendVersion);
  }, [user]);

  useEffect(() => {
    if (!user) return;
    // Checked once on mount (so the link can appear no matter which page a
    // session starts on) and again on every arrival at /projects or
    // /favourites — the only two places a favourite can be toggled — since
    // this shell never remounts across routes and would otherwise leave a
    // freshly (un)favourited project unreflected until a hard refresh.
    // Deliberately NOT re-checked on every navigation: that would fire this
    // same request on every single route change for the entire session.
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(
      (list) => setHasFavourites(list.some((p) => p.is_favorite))
    );
  }, [user, onFavouritableRoute]);

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
          className={`nav-rail stack ${railCollapsed ? "nav-rail-icons" : ""}`}
          style={{ gap: "0.15rem" }}
        >
          <div className="row nav-rail-toggle-row" style={{ justifyContent: "flex-end" }}>
            <Tooltip label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}>
              <button
                className="btn"
                onClick={() => setRailCollapsed(!railCollapsed)}
                aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
              >
                {railCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              </button>
            </Tooltip>
          </div>
          {projectId && (
            <>
              <div className="nav-section-label">{strings.nav.projectSectionLabel}</div>
              <NavRailLink to={`/projects/${projectId}`} exact label={strings.nav.overview} icon={<LayoutDashboard size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/requirements`} label={strings.nav.requirements} icon={<ListChecks size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/change-requests`} label={strings.nav.changeRequests} icon={<GitPullRequest size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/actions`} label={strings.nav.actions} icon={<CheckSquare size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/reports`} label={strings.nav.reports} icon={<FileText size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/reviews-due`} label={strings.reviews.projectTitle} icon={<Clock size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/history`} label={strings.history.title} icon={<History size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to={`/projects/${projectId}/admin`} label={strings.nav.admin} icon={<Settings size={16} />} railCollapsed={railCollapsed} />
            </>
          )}
          <div className="nav-section-label">Global</div>
          <NavRailLink to="/projects" exact label={strings.nav.projects} icon={<FolderKanban size={16} />} railCollapsed={railCollapsed} />
          {hasFavourites && (
            <NavRailLink to="/favourites" exact label={strings.nav.favourites} icon={<Star size={16} />} railCollapsed={railCollapsed} />
          )}
          <NavRailLink to="/my-reviews" label={strings.nav.myReviews} icon={<CalendarClock size={16} />} railCollapsed={railCollapsed} />
          <NavRailLink to="/notifications" exact label={strings.notifications.title} icon={<Bell size={16} />} railCollapsed={railCollapsed} />
          {/* The only path to org administration (U-P-02-adjacent IA gap
              found in the 2026-08 UX audit): /orgs already auto-redirects
              straight to a single org's admin page, or lists every org a
              user belongs to otherwise — it just had no rail entry before
              this, for anyone but a server admin drilling in through
              /server/organisations. See docs/ux-style-guide.md, "Pattern:
              wayfinding". */}
          <NavRailLink to="/orgs" exact label={strings.nav.myOrganizations(orgLabelPlural)} icon={<Building2 size={16} />} railCollapsed={railCollapsed} />
          {user.is_server_admin && (
            <>
              <div className="nav-section-label">Administration</div>
              <NavRailLink to="/server/organisations" label={strings.orgAdmin.organizations(orgLabelPlural)} icon={<Building2 size={16} />} railCollapsed={railCollapsed} />
              <NavRailLink to="/server/management" label={strings.nav.serverManagement} icon={<Wrench size={16} />} railCollapsed={railCollapsed} />
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
          {!railCollapsed && (
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
      <main className={`app-content${contentBoxed ? " boxed" : ""}`}>
        {contentBoxed ? <div className="content-inner">{children}</div> : children}
      </main>
    </div>
  );
}
