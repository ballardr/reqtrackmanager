import { Building2, History, LayoutDashboard, ListChecks, Settings, FileText, LogOut, GitPullRequest, FolderKanban, ShieldCheck } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { TerminologyProvider, useOrgLogoFileId, useTermPlural } from "../context/TerminologyContext";
import { t } from "../i18n/strings";
import { NotificationBell } from "./NotificationBell";

const strings = t();

/**
 * App shell: a responsive top bar plus collapsible nav (U-P-02, U-P-03).
 * Project-scoped links only render once a project is selected (path
 * contains /projects/:id). The nav rail is a fixed dark "chrome" (see
 * --color-nav-* in theme.css) with a project-context group above a global
 * group, per the reference mock UI design. Wraps content in
 * `TerminologyProvider` (C-C-03) so the nav labels below and every page
 * rendered as `children` can resolve the current project's terminology
 * overrides.
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
  const [menuOpen, setMenuOpen] = useState(false);
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
            <button className="btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Toggle navigation">
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
            className={`nav-dark stack ${menuOpen ? "" : "nav-collapsed"}`}
            style={{ minWidth: 220, position: "sticky", top: "1rem", gap: "0.15rem" }}
          >
            {projectId && (
              <>
                <div className="nav-section-label">Project</div>
                <Link to={`/projects/${projectId}`} className={navLinkClass(`/projects/${projectId}`, true)}>
                  <LayoutDashboard size={16} /> {strings.nav.overview}
                </Link>
                <Link
                  to={`/projects/${projectId}/requirements`}
                  className={navLinkClass(`/projects/${projectId}/requirements`)}
                >
                  <ListChecks size={16} /> {requirementsTerm}
                </Link>
                <Link
                  to={`/projects/${projectId}/change-requests`}
                  className={navLinkClass(`/projects/${projectId}/change-requests`)}
                >
                  <GitPullRequest size={16} /> {changeRequestsTerm}
                </Link>
                <Link to={`/projects/${projectId}/reports`} className={navLinkClass(`/projects/${projectId}/reports`)}>
                  <FileText size={16} /> {strings.nav.reports}
                </Link>
                <Link to={`/projects/${projectId}/history`} className={navLinkClass(`/projects/${projectId}/history`)}>
                  <History size={16} /> {strings.history.title}
                </Link>
                <Link to={`/projects/${projectId}/admin`} className={navLinkClass(`/projects/${projectId}/admin`)}>
                  <Settings size={16} /> {strings.nav.admin}
                </Link>
              </>
            )}
            <div className="nav-section-label">Global</div>
            <Link to="/projects" className={navLinkClass("/projects", true)}>
              <FolderKanban size={16} /> {strings.nav.projects}
            </Link>
            <Link to="/orgs" className={navLinkClass("/orgs")}>
              <Building2 size={16} /> {strings.orgAdmin.organizations}
            </Link>
            {user.is_server_admin && (
              <>
                <div className="nav-section-label">Server Management</div>
                <Link to="/server/organisations" className={navLinkClass("/server/organisations")}>
                  <ShieldCheck size={16} /> Organisations
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
