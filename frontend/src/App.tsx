import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/Spinner";
import { useAuth } from "./context/AuthContext";
import { useFederatedModules } from "./hooks/useFederatedModules";
import { useProjectEnabledModules } from "./hooks/useProjectEnabledModules";
import { buildModuleRoutes } from "./modules/buildModuleRoutes";
import { ActionDetailPage } from "./pages/ActionDetailPage";
import { ChangeRequestDetailPage } from "./pages/ChangeRequestDetailPage";
import { ChangeRequestsPage } from "./pages/ChangeRequestsPage";
import { FavouritesPage } from "./pages/FavouritesPage";
import { HelpPage } from "./pages/HelpPage";
import { LoginPage } from "./pages/LoginPage";
import { MyReviewsDuePage } from "./pages/MyReviewsDuePage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OidcCompletePage } from "./pages/OidcCompletePage";
import { OrgAdminPage } from "./pages/OrgAdminPage";
import { OrgListPage } from "./pages/OrgListPage";
import { OrgLoginPage } from "./pages/OrgLoginPage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { ProjectActionsPage } from "./pages/ProjectActionsPage";
import { ProjectAdminPage } from "./pages/ProjectAdminPage";
import { ProjectFilesPage } from "./pages/ProjectFilesPage";
import { ProjectHistoryPage } from "./pages/ProjectHistoryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectReviewsDuePage } from "./pages/ProjectReviewsDuePage";
import { ReportsPage } from "./pages/ReportsPage";
import { RequirementDetailPage } from "./pages/RequirementDetailPage";
import { RequirementsPage } from "./pages/RequirementsPage";
import { ServerManagementPage } from "./pages/ServerManagementPage";
import { ServerOrganisationsPage } from "./pages/ServerOrganisationsPage";
import { SignupPage } from "./pages/SignupPage";

function ProtectedRoutes() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;
  const { modules: enabledModules, loaded: modulesLoaded } = useProjectEnabledModules(projectId);
  // Module system follow-up, 2026-09-07 (Tier C / Module Federation): a
  // project-scoped module whose manifest is `"federated"` needs its
  // `TierAModuleDefinition` loaded at runtime before `buildModuleRoutes`
  // below can find it in `installedModules` — see `useFederatedModules`'s
  // own docstring. Called unconditionally, before this component's own
  // `loading`/`!user` early returns.
  const federatedModuleStates = useFederatedModules(enabledModules);
  // Same navigation-race class of bug Phase 13's own notes describe for
  // `modulesLoaded` below, one layer further out: `modulesLoaded` only
  // means "the enabled-modules list itself was fetched," not "every
  // federated module it named has finished its own async remote-entry
  // load" — a fresh navigation straight to a Tier C module's own nav-rail
  // link could otherwise still hit the wildcard `Navigate` below before
  // that load resolves. Folded into the same gate rather than a second,
  // parallel one.
  const federatedModulesStillLoading = Object.values(federatedModuleStates).some((s) => s.status === "loading");

  if (loading) {
    return (
      <div className="container" style={{ marginTop: "3rem" }}>
        <Spinner />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  return (
    <Layout>
      <Routes>
        {buildModuleRoutes(enabledModules, projectId)}
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/favourites" element={<FavouritesPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/orgs" element={<OrgListPage />} />
        <Route path="/orgs/:orgId/admin/:group?" element={<OrgAdminPage />} />
        <Route path="/server/organisations" element={<ServerOrganisationsPage />} />
        <Route path="/server/management/:group?" element={<ServerManagementPage />} />
        <Route path="/my-reviews" element={<MyReviewsDuePage />} />
        <Route path="/projects/:projectId" element={<ProjectOverviewPage />} />
        <Route path="/projects/:projectId/requirements" element={<RequirementsPage />} />
        <Route path="/projects/:projectId/requirements/:requirementId" element={<RequirementDetailPage />} />
        <Route path="/projects/:projectId/change-requests" element={<ChangeRequestsPage />} />
        <Route path="/projects/:projectId/change-requests/:crId" element={<ChangeRequestDetailPage />} />
        <Route path="/projects/:projectId/actions" element={<ProjectActionsPage />} />
        <Route path="/projects/:projectId/actions/:actionId" element={<ActionDetailPage />} />
        <Route path="/projects/:projectId/files" element={<ProjectFilesPage />} />
        <Route path="/projects/:projectId/admin/:group?" element={<ProjectAdminPage />} />
        <Route path="/projects/:projectId/history" element={<ProjectHistoryPage />} />
        <Route path="/projects/:projectId/reports" element={<ReportsPage />} />
        <Route path="/projects/:projectId/reviews-due" element={<ProjectReviewsDuePage />} />
        <Route path="/preferences/:group?" element={<PreferencesPage />} />
        <Route path="/help" element={<HelpPage />} />
        {/* Falls through here for any path that matches none of the routes
            above, including every route `buildModuleRoutes` above would
            contribute once loaded. While a project-scoped path's own
            enabled-modules fetch is still in flight, that list is
            genuinely `[]` (module system Phase 3's own hook) whether or
            not this path is actually a module's route — redirecting to
            /projects here is only correct once we actually know, so this
            renders a brief loading state instead and lets `<Routes>`
            re-match on the next render once `modulesLoaded` flips true and
            the real module route (if any) is spliced in above. See
            `useProjectEnabledModules`'s own docstring for the navigation
            bug this fixes (a project module's own nav-rail link used to
            bounce straight back to /projects on a fresh navigation). */}
        <Route
          path="*"
          element={
            projectId && (!modulesLoaded || federatedModulesStillLoading) ? (
              <div className="container" style={{ marginTop: "3rem" }}>
                <Spinner />
              </div>
            ) : (
              <Navigate to="/projects" replace />
            )
          }
        />
      </Routes>
    </Layout>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login/:slug" element={<OrgLoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/oidc-complete" element={<OidcCompletePage />} />
      <Route path="/*" element={<ProtectedRoutes />} />
    </Routes>
  );
}
