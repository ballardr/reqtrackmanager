import { Building2, CalendarClock, ChevronLeft, ChevronRight, History, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { TerminologyProvider, useOrgLogoFileId, useTermPlural } from "../context/TerminologyContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { t } from "../i18n/strings";
import { NotificationBell } from "./NotificationBell";

const strings = t();

/**
 * App shell: a responsive top bar plus collapsible nav (U-P-02, U-P-03).
 * Project-scoped links only render once a project is selected (path
 * contains /projects/:id). The nav rail uses the same theme-aware surface
 * colours as the rest of the UI (--color-surface/-text/etc in theme.css),
 * with a project-context group above a global group. `railCollapsed`
 * shrinks the whole rail to icons-only, toggled from either the header's
 * hamburger button or the chevron at the foot of the rail (both control
 * the same state, so there's exactly one collapse behaviour, not two
 * competing ones), and persisted via `useUiPreference` (`nav_rail_collapsed`)
 * so it follows the user across devices the same way their theme/landing-
 * page choices already do. Wraps content in `TerminologyProvider` (C-C-03)
 * so the nav labels below and every page rendered as `children` can
 * resolve the current project's terminology overrides.
 */
export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  return (
    <TerminologyProvider projectId={projectId}>
      <LayoutShell>{children}</LayoutShell>
    </TerminologyProvider>
  );
}

function LayoutShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [railCollapsed, setRailCollapsed] = useUiPreference<boolean>("nav_rail_collapsed", false);
  const requirementsTerm = useTermPlural("requirement");
  const changeRequestsTerm = useTermPlural("change_request");
  const orgLogoFileId = useOrgLogoFileId();

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  function navLinkClass(to: string, exact = false): string {
    const active = exact ? location.pathname === to : location.pathname.startsWith(to);
    return `nav-link${active ? " active" : ""}`;
  }

  return (
    <div className="stack" style={{ minHeight: "100%" }}>
      <header className="card" style={{ borderRadius: 0, borderLeft: "none", borderRight: "none", borderTop: "none" }}>
        <div className="container row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <button
              className="btn"
              onClick={() => setRailCollapsed(!railCollapsed)}
              aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
              title={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
            >
              ☰
            </button>
            <Link
              to="/projects"
              className="row"
              style={{ fontWeight: 700, textDecoration: "none", color: "var(--color-text)", gap: "0.5rem" }}
            >
              {/* U-C-02: the current project's organisation logo, when one has
                  been uploaded. Falls back to the text-only wordmark alone
                  outside of a project context or when no logo is set. */}
              {orgLogoFileId && <img src={fileUrl(orgLogoFileId)} alt="" style={{ height: 24 }} />}
              {strings.appName}
            </Link>
          </div>
          {user && (
            <div className="row">
              <span className="text-muted">{user.display_name}</span>
              <NotificationBell />
              <Link to="/preferences" className="btn" title={strings.nav.preferences}>
                <Settings size={16} />
              </Link>
              <button className="btn" onClick={logout} title={strings.nav.signOut}>
                <LogOut size={16} />
              </button>
            </div>
          )}
        </div>
      </header>
      <div className="container row" style={{ alignItems: "flex-start", gap: "1.5rem" }}>
        {user && (
          <nav
            className={`nav-rail stack ${railCollapsed ? "nav-rail-icons" : ""}`}
            style={{ minWidth: railCollapsed ? 56 : 220, position: "sticky", top: "1rem", gap: "0.15rem" }}
          >
            {projectId && (
              <>
                <div className="nav-section-label">Project</div>
                <Link to={`/projects/${projectId}`} className={navLinkClass(`/projects/${projectId}`, true)} title={strings.nav.overview}>
                  <LayoutDashboard size={16} /> <span className="nav-label">{strings.nav.overview}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/requirements`}
                  className={navLinkClass(`/projects/${projectId}/requirements`)}
                  title={requirementsTerm}
                >
                  <ListChecks size={16} /> <span className="nav-label">{requirementsTerm}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/change-requests`}
                  className={navLinkClass(`/projects/${projectId}/change-requests`)}
                  title={changeRequestsTerm}
                >
                  <GitPullRequest size={16} /> <span className="nav-label">{changeRequestsTerm}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/reports`}
                  className={navLinkClass(`/projects/${projectId}/reports`)}
                  title={strings.nav.reports}
                >
                  <FileText size={16} /> <span className="nav-label">{strings.nav.reports}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/reviews-due`}
                  className={navLinkClass(`/projects/${projectId}/reviews-due`)}
                  title={strings.reviews.projectTitle}
                >
                  <CalendarClock size={16} /> <span className="nav-label">{strings.reviews.projectTitle}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/history`}
                  className={navLinkClass(`/projects/${projectId}/history`)}
                  title={strings.history.title}
                >
                  <History size={16} /> <span className="nav-label">{strings.history.title}</span>
                </Link>
                <Link
                  to={`/projects/${projectId}/admin`}
                  className={navLinkClass(`/projects/${projectId}/admin`)}
                  title={strings.nav.admin}
                >
                  <Settings size={16} /> <span className="nav-label">{strings.nav.admin}</span>
                </Link>
              </>
            )}
            <div className="nav-section-label">Global</div>
            <Link to="/projects" className={navLinkClass("/projects", true)} title={strings.nav.projects}>
              <FolderKanban size={16} /> <span className="nav-label">{strings.nav.projects}</span>
            </Link>
            <Link to="/orgs" className={navLinkClass("/orgs")} title={strings.orgAdmin.organizations}>
              <Building2 size={16} /> <span className="nav-label">{strings.orgAdmin.organizations}</span>
            </Link>
            <Link to="/my-reviews" className={navLinkClass("/my-reviews")} title={strings.nav.myReviews}>
              <CalendarClock size={16} /> <span className="nav-label">{strings.nav.myReviews}</span>
            </Link>
            {user.is_server_admin && (
              <>
                <div className="nav-section-label">Server Management</div>
                <Link to="/server/organisations" className={navLinkClass("/server/organisations")} title="Organisations">
                  <ShieldCheck size={16} /> <span className="nav-label">Organisations</span>
                </Link>
                <Link
                  to="/server/access-review"
                  className={navLinkClass("/server/access-review")}
                  title={strings.orgAdmin.accessReview}
                >
                  <ShieldCheck size={16} /> <span className="nav-label">{strings.orgAdmin.accessReview}</span>
                </Link>
              </>
            )}
            <button
              className="btn nav-rail-toggle"
              onClick={() => setRailCollapsed(!railCollapsed)}
              title={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
              aria-label={railCollapsed ? strings.nav.expandNav : strings.nav.collapseNav}
            >
              {railCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            </button>
          </nav>
        )}
        <main style={{ flex: 1, minWidth: 0, width: "100%" }}>{children}</main>
      </div>
    </div>
  );
}
