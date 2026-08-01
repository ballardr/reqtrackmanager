import { Building2, History, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { NotificationBell } from "./NotificationBell";

const strings = t();

/**
 * App shell: a responsive top bar plus collapsible nav (U-P-02, U-P-03).
 * Project-scoped links only render once a project is selected (path
 * contains /projects/:id).
 */
export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  return (
    <div className="stack" style={{ minHeight: "100%" }}>
      <header className="card" style={{ borderRadius: 0, borderLeft: "none", borderRight: "none", borderTop: "none" }}>
        <div className="container row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <button className="btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Toggle navigation">
              ☰
            </button>
            <Link to="/projects" style={{ fontWeight: 700, textDecoration: "none", color: "var(--color-text)" }}>
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
            className={`card stack ${menuOpen ? "" : "nav-collapsed"}`}
            style={{ minWidth: 200, position: "sticky", top: "1rem" }}
          >
            <Link to="/projects" className="row">
              <FolderKanban size={16} /> {strings.nav.projects}
            </Link>
            <Link to="/orgs" className="row">
              <Building2 size={16} /> {strings.orgAdmin.organizations}
            </Link>
            {projectId && (
              <>
                <Link to={`/projects/${projectId}`} className="row">
                  <LayoutDashboard size={16} /> {strings.nav.overview}
                </Link>
                <Link to={`/projects/${projectId}/requirements`} className="row">
                  <ListChecks size={16} /> {strings.nav.requirements}
                </Link>
                <Link to={`/projects/${projectId}/change-requests`} className="row">
                  <GitPullRequest size={16} /> {strings.nav.changeRequests}
                </Link>
                <Link to={`/projects/${projectId}/reports`} className="row">
                  <FileText size={16} /> {strings.nav.reports}
                </Link>
                <Link to={`/projects/${projectId}/history`} className="row">
                  <History size={16} /> {strings.history.title}
                </Link>
                <Link to={`/projects/${projectId}/admin`} className="row">
                  <Settings size={16} /> {strings.nav.admin}
                </Link>
              </>
            )}
          </nav>
        )}
        <main style={{ flex: 1, minWidth: 0, width: "100%" }}>{children}</main>
      </div>
      <style>{`
        @media (max-width: 720px) {
          nav.nav-collapsed { display: none; }
        }
      `}</style>
    </div>
  );
}
