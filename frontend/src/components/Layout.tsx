import { Building2, CalendarClock, Clock, History, HelpCircle, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban, Palette, PanelLeftClose, PanelLeftOpen, ShieldCheck, UserCog } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { BrandingProvider, useBranding } from "../context/BrandingContext";
import { TerminologyProvider, useTermPlural } from "../context/TerminologyContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { t } from "../i18n/strings";
import { NotificationBell } from "./NotificationBell";
import { Tooltip } from "./Tooltip";

const strings = t();

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
 * the chevron at its foot — the header's hamburger button was removed as a
 * pure duplicate of that same control — and persisted via
 * `useUiPreference` (`nav_rail_collapsed`) so it follows the user across
 * devices the same way their theme/landing-page choices already do.
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
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useUiPreference<boolean>("nav_rail_collapsed", false);
  const [contentBoxed] = useUiPreference<boolean>("content_boxed", false);
  const requirementsTerm = useTermPlural("requirement");
  const changeRequestsTerm = useTermPlural("change_request");
  const branding = useBranding();

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  function navLinkClass(to: string, exact = false): string {
    const active = exact ? location.pathname === to : location.pathname.startsWith(to);
    return `nav-link${active ? " active" : ""}`;
  }

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
              falling back again to the built-in wordmark. */}
          {branding.logoFileId && <img src={fileUrl(branding.logoFileId)} alt="" style={{ height: 24 }} />}
          {branding.headerTitle}
        </Link>
        {user && (
          <div className="row">
            <span className="text-muted">{user.display_name}</span>
            <NotificationBell />
            <Tooltip label={strings.nav.help}>
              <Link to="/help" className="btn" aria-label={strings.nav.help}>
                <HelpCircle size={16} />
              </Link>
            </Tooltip>
            <Tooltip label={strings.nav.preferences}>
              <Link to="/preferences" className="btn" aria-label={strings.nav.preferences}>
                <Settings size={16} />
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
          {projectId && (
            <>
              <div className="nav-section-label">Project</div>
              <Tooltip label={strings.nav.overview}>
                <Link to={`/projects/${projectId}`} className={navLinkClass(`/projects/${projectId}`, true)} aria-label={strings.nav.overview}>
                  <LayoutDashboard size={16} /> <span className="nav-label">{strings.nav.overview}</span>
                </Link>
              </Tooltip>
              <Tooltip label={requirementsTerm}>
                <Link
                  to={`/projects/${projectId}/requirements`}
                  className={navLinkClass(`/projects/${projectId}/requirements`)}
                  aria-label={requirementsTerm}
                >
                  <ListChecks size={16} /> <span className="nav-label">{requirementsTerm}</span>
                </Link>
              </Tooltip>
              <Tooltip label={changeRequestsTerm}>
                <Link
                  to={`/projects/${projectId}/change-requests`}
                  className={navLinkClass(`/projects/${projectId}/change-requests`)}
                  aria-label={changeRequestsTerm}
                >
                  <GitPullRequest size={16} /> <span className="nav-label">{changeRequestsTerm}</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.nav.reports}>
                <Link
                  to={`/projects/${projectId}/reports`}
                  className={navLinkClass(`/projects/${projectId}/reports`)}
                  aria-label={strings.nav.reports}
                >
                  <FileText size={16} /> <span className="nav-label">{strings.nav.reports}</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.reviews.projectTitle}>
                <Link
                  to={`/projects/${projectId}/reviews-due`}
                  className={navLinkClass(`/projects/${projectId}/reviews-due`)}
                  aria-label={strings.reviews.projectTitle}
                >
                  <Clock size={16} /> <span className="nav-label">{strings.reviews.projectTitle}</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.history.title}>
                <Link
                  to={`/projects/${projectId}/history`}
                  className={navLinkClass(`/projects/${projectId}/history`)}
                  aria-label={strings.history.title}
                >
                  <History size={16} /> <span className="nav-label">{strings.history.title}</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.nav.admin}>
                <Link
                  to={`/projects/${projectId}/admin`}
                  className={navLinkClass(`/projects/${projectId}/admin`)}
                  aria-label={strings.nav.admin}
                >
                  <Settings size={16} /> <span className="nav-label">{strings.nav.admin}</span>
                </Link>
              </Tooltip>
            </>
          )}
          <div className="nav-section-label">Global</div>
          <Tooltip label={strings.nav.projects}>
            <Link to="/projects" className={navLinkClass("/projects", true)} aria-label={strings.nav.projects}>
              <FolderKanban size={16} /> <span className="nav-label">{strings.nav.projects}</span>
            </Link>
          </Tooltip>
          <Tooltip label={strings.orgAdmin.organizations}>
            <Link to="/orgs" className={navLinkClass("/orgs")} aria-label={strings.orgAdmin.organizations}>
              <Building2 size={16} /> <span className="nav-label">{strings.orgAdmin.organizations}</span>
            </Link>
          </Tooltip>
          <Tooltip label={strings.nav.myReviews}>
            <Link to="/my-reviews" className={navLinkClass("/my-reviews")} aria-label={strings.nav.myReviews}>
              <CalendarClock size={16} /> <span className="nav-label">{strings.nav.myReviews}</span>
            </Link>
          </Tooltip>
          {user.is_server_admin && (
            <>
              <div className="nav-section-label">Server management</div>
              <Tooltip label="Organisations">
                <Link to="/server/organisations" className={navLinkClass("/server/organisations")} aria-label="Organisations">
                  <ShieldCheck size={16} /> <span className="nav-label">Organisations</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.orgAdmin.accessReview}>
                <Link
                  to="/server/access-review"
                  className={navLinkClass("/server/access-review")}
                  aria-label={strings.orgAdmin.accessReview}
                >
                  <UserCog size={16} /> <span className="nav-label">{strings.orgAdmin.accessReview}</span>
                </Link>
              </Tooltip>
              <Tooltip label={strings.serverSettings.title}>
                <Link
                  to="/server/settings"
                  className={navLinkClass("/server/settings")}
                  aria-label={strings.serverSettings.title}
                >
                  <Palette size={16} /> <span className="nav-label">{strings.serverSettings.title}</span>
                </Link>
              </Tooltip>
            </>
          )}
          <Tooltip label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}>
            <button
              className="btn nav-rail-toggle"
              onClick={() => setRailCollapsed(!railCollapsed)}
              aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
            >
              {railCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          </Tooltip>
        </nav>
      )}
      <main className={`app-content${contentBoxed ? " boxed" : ""}`}>
        {contentBoxed ? <div className="content-inner">{children}</div> : children}
      </main>
    </div>
  );
}
