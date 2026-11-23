import { useEffect, useRef, type RefObject } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/Spinner";
import { useAuth } from "./context/AuthContext";
import { useFederatedModules } from "./hooks/useFederatedModules";
import { useProjectEnabledModules } from "./hooks/useProjectEnabledModules";
import { useUnhandledRequestFailures } from "./hooks/useUnhandledRequestFailures";
import { rememberReturnTo } from "./utils/returnTo";
import { buildModuleRoutes } from "./modules/buildModuleRoutes";
import { installedModules } from "./modules/registry";
import { ActionDetailPage } from "./pages/ActionDetailPage";
import { ChangeRequestDetailPage } from "./pages/ChangeRequestDetailPage";
import { ChangeRequestsPage } from "./pages/ChangeRequestsPage";
import { FavouritesPage } from "./pages/FavouritesPage";
import { LoginPage } from "./pages/LoginPage";
import { MyReviewsDuePage } from "./pages/MyReviewsDuePage";
import { NotificationOpenPage } from "./pages/NotificationOpenPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OidcCompletePage } from "./pages/OidcCompletePage";
import { OrgAdminPage } from "./pages/OrgAdminPage";
import { OrgListPage } from "./pages/OrgListPage";
import { OrgLoginPage } from "./pages/OrgLoginPage";
import { OrgOverviewPage } from "./pages/OrgOverviewPage";
import { OrgResourcesPage } from "./pages/OrgResourcesPage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { HelpRedirectPage } from "./pages/HelpRedirectPage";
import { ReportRunPage } from "./pages/ReportRunPage";
import { ProjectActionsPage } from "./pages/ProjectActionsPage";
import { ProjectAdminPage } from "./pages/ProjectAdminPage";
import { ProjectStagePhasesPage } from "./pages/ProjectStagePhasesPage";
import { OrgFilesPage } from "./pages/OrgFilesPage";
import { ProjectFilesPage } from "./pages/ProjectFilesPage";
import { ProjectHistoryPage } from "./pages/ProjectHistoryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectReviewsDuePage } from "./pages/ProjectReviewsDuePage";
import { PoliciesPage, PublicPoliciesPage } from "./pages/PoliciesPage";
import { ReportLayoutDesignerPage } from "./pages/ReportLayoutDesignerPage";
import { ReportPackPage } from "./pages/ReportPackPage";
import { SearchPage } from "./pages/SearchPage";
import { RequirementDetailPage } from "./pages/RequirementDetailPage";
import { RequirementsPage } from "./pages/RequirementsPage";
import { ServerManagementPage } from "./pages/ServerManagementPage";
import { ServerOrganisationsPage } from "./pages/ServerOrganisationsPage";
import { ConfirmEmailPage } from "./pages/ConfirmEmailPage";
import { ForcedPasswordChangePage } from "./pages/ForcedPasswordChangePage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { SignupPage } from "./pages/SignupPage";

/**
 * Sends the Org Admin "Templates & reports" address (`/orgs/:orgId/admin/templates-reports`) to the reports
 * group, so a bookmarked address still lands on the reports.
 */
function OldOrgReportsRedirect() {
  const { orgId } = useParams<{ orgId: string }>();
  return <Navigate to={`/orgs/${orgId}/resources/reports`} replace />;
}

/**
 * Sends a person who is not signed in to the sign-in page.
 *
 * Args:
 *     signedInBefore: Set once this tab has had a signed-in person. When it is not set the person arrived by a link,
 *         so the address they asked for is remembered and signing in returns them to it.
 */
function RedirectToLogin({ signedInBefore }: { signedInBefore: RefObject<boolean> }) {
  const location = useLocation();
  const asked = location.pathname + location.search + location.hash;
  useEffect(() => {
    if (!signedInBefore.current) rememberReturnTo(asked);
  }, [asked, signedInBefore]);
  return <Navigate to="/login" replace />;
}

function ProtectedRoutes() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const projectMatch = location.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;
  // `!loading` (the hook's `ready` argument) defers the fetch until `AuthProvider` has set a bearer token. The
  // hook is called unconditionally, before the `loading`/`!user` early returns below, as the Rules of Hooks
  // require.
  const { modules: enabledModules, loaded: modulesLoaded } = useProjectEnabledModules(projectId, !loading);
  // Tier C (Module Federation): a project-scoped module whose manifest is `"federated"` needs its
  // `TierAModuleDefinition` loaded at runtime before `buildModuleRoutes` can find it in `installedModules` (see
  // `useFederatedModules`). Called unconditionally, before the `loading`/`!user` early returns.
  const federatedModuleStates = useFederatedModules(enabledModules);
  // Whether this tab has had a signed-in person: a redirect to sign-in after that is a lapsed session or a deliberate
  // sign-out (the 401 handler and `logout` manage the remembered page); one before it is a followed link.
  const signedInBefore = useRef(false);
  useEffect(() => {
    if (user) signedInBefore.current = true;
  }, [user]);
  // `modulesLoaded` means the enabled-modules list was fetched, not that every federated module it names has
  // finished its remote-entry load; without this gate a fresh navigation to a Tier C module's nav link could hit
  // the wildcard `Navigate` first. It is folded into the same gate as `modulesLoaded`.
  const federatedModulesStillLoading = Object.values(federatedModuleStates).some((s) => s.status === "loading");

  if (loading) {
    return (
      <div className="container" style={{ marginTop: "3rem" }}>
        <Spinner />
      </div>
    );
  }
  // The Policies page is public: the people a privacy policy concerns most have not signed in yet.
  if (!user && /^\/policies(\/|$)/.test(location.pathname)) return <PublicPoliciesPage />;
  if (!user) return <RedirectToLogin signedInBefore={signedInBefore} />;
  // An administrator-set password is changed before anything else is shown (the server refuses every other request).
  if (user.must_change_password) return <ForcedPasswordChangePage />;

  return (
    <Layout>
      <Routes>
        {buildModuleRoutes(enabledModules, projectId)}
        <Route path="/policies/*" element={<PoliciesPage />} />
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/favourites" element={<FavouritesPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/notifications/:notificationId" element={<NotificationOpenPage />} />
        <Route path="/report-runs/:runId" element={<ReportRunPage />} />
        <Route path="/orgs" element={<OrgListPage />} />
        <Route path="/org-files" element={<OrgListPage target="files" />} />
        <Route path="/orgs/:orgId/files" element={<OrgFilesPage />} />
        <Route path="/orgs/:orgId/admin/templates-reports" element={<OldOrgReportsRedirect />} />
        <Route path="/orgs/:orgId/admin/:group?/:section?" element={<OrgAdminPage />} />
        <Route path="/orgs/:orgId/report-layouts/:layoutId" element={<ReportLayoutDesignerPage />} />
        <Route path="/orgs/:orgId/report-packs/:packId" element={<ReportPackPage />} />
        {/* "Organisation Overview" reuses `OrgListPage`'s single-org/multi-org auto-redirect
            (`target="overview"`) as its entry point, as `/orgs` does for `/orgs/:orgId/admin`. */}
        <Route path="/org-overview" element={<OrgListPage target="overview" />} />
        <Route path="/orgs/:orgId/overview/:group?" element={<OrgOverviewPage />} />
        {/* "Org Resources" — what the organisation owns and shares with its projects; its sections come from the
            module registry (`orgResourceSections`). Same single-org/multi-org entry convention. */}
        <Route path="/org-resources" element={<OrgListPage target="resources" />} />
        <Route path="/orgs/:orgId/resources/:group?/:section?" element={<OrgResourcesPage />} />
        {/* Every installed module's always-mounted top-level routes
            (`TierAModuleDefinition.globalRoutes`). Unlike the project-scoped `buildModuleRoutes`, these are
            plain top-level routes like `/projects` and `/orgs`, for a module surface with no single
            project or org to key an enablement check off (Compliance's `/standards`). `App.tsx` never imports a
            module's page components: each module registers its `globalRoutes` in its `module.ts`. */}
        {installedModules.flatMap((m) => m.globalRoutes ?? []).map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
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
        <Route path="/projects/:projectId/admin/:group?/:section?" element={<ProjectAdminPage />} />
        <Route path="/projects/:projectId/stage-phases" element={<ProjectStagePhasesPage />} />
        <Route path="/projects/:projectId/history" element={<ProjectHistoryPage />} />
        <Route path="/projects/:projectId/report-layouts/:layoutId" element={<ReportLayoutDesignerPage />} />
        <Route path="/projects/:projectId/report-packs/:packId" element={<ReportPackPage />} />
        <Route path="/projects/:projectId/reviews-due" element={<ProjectReviewsDuePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/preferences/:group?" element={<PreferencesPage />} />
        <Route path="/help" element={<HelpRedirectPage />} />
        {/* Any path matching no route above, including every route `buildModuleRoutes` contributes once
            loaded. While a project-scoped path's enabled-modules fetch is in flight the list is `[]`
            whether or not the path is a module's route, so redirecting to /projects is correct only once it is
            known: a brief loading state renders instead, and `<Routes>` re-matches once `modulesLoaded` is true
            and the module route (if any) is spliced in. See `useProjectEnabledModules`. */}
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
  useUnhandledRequestFailures();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login/:slug" element={<OrgLoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/confirm-email" element={<ConfirmEmailPage />} />
      <Route path="/oidc-complete" element={<OidcCompletePage />} />
      <Route path="/*" element={<ProtectedRoutes />} />
    </Routes>
  );
}
