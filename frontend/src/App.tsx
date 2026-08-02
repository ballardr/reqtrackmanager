import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/Spinner";
import { useAuth } from "./context/AuthContext";
import { ChangeRequestDetailPage } from "./pages/ChangeRequestDetailPage";
import { ChangeRequestsPage } from "./pages/ChangeRequestsPage";
import { LoginPage } from "./pages/LoginPage";
import { MyReviewsDuePage } from "./pages/MyReviewsDuePage";
import { OidcCompletePage } from "./pages/OidcCompletePage";
import { OrgAdminPage } from "./pages/OrgAdminPage";
import { OrgListPage } from "./pages/OrgListPage";
import { OrgLoginPage } from "./pages/OrgLoginPage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { ProjectAdminPage } from "./pages/ProjectAdminPage";
import { ProjectHistoryPage } from "./pages/ProjectHistoryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectReviewsDuePage } from "./pages/ProjectReviewsDuePage";
import { ReportsPage } from "./pages/ReportsPage";
import { RequirementDetailPage } from "./pages/RequirementDetailPage";
import { RequirementsPage } from "./pages/RequirementsPage";
import { ServerAccessReviewPage } from "./pages/ServerAccessReviewPage";
import { ServerOrganisationsPage } from "./pages/ServerOrganisationsPage";

function ProtectedRoutes() {
  const { user, loading } = useAuth();
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
      <div className="container" style={{ padding: "1.5rem 0" }}>
        <Routes>
          <Route path="/projects" element={<ProjectListPage />} />
          <Route path="/orgs" element={<OrgListPage />} />
          <Route path="/orgs/:orgId/admin" element={<OrgAdminPage />} />
          <Route path="/server/organisations" element={<ServerOrganisationsPage />} />
          <Route path="/server/access-review" element={<ServerAccessReviewPage />} />
          <Route path="/my-reviews" element={<MyReviewsDuePage />} />
          <Route path="/projects/:projectId" element={<ProjectOverviewPage />} />
          <Route path="/projects/:projectId/requirements" element={<RequirementsPage />} />
          <Route path="/projects/:projectId/requirements/:requirementId" element={<RequirementDetailPage />} />
          <Route path="/projects/:projectId/change-requests" element={<ChangeRequestsPage />} />
          <Route path="/projects/:projectId/change-requests/:crId" element={<ChangeRequestDetailPage />} />
          <Route path="/projects/:projectId/admin" element={<ProjectAdminPage />} />
          <Route path="/projects/:projectId/history" element={<ProjectHistoryPage />} />
          <Route path="/projects/:projectId/reports" element={<ReportsPage />} />
          <Route path="/projects/:projectId/reviews-due" element={<ProjectReviewsDuePage />} />
          <Route path="/preferences" element={<PreferencesPage />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </div>
    </Layout>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login/:slug" element={<OrgLoginPage />} />
      <Route path="/oidc-complete" element={<OidcCompletePage />} />
      <Route path="/*" element={<ProtectedRoutes />} />
    </Routes>
  );
}
