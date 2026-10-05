/**
 * Module: pages/ReportsPage
 *
 * The project's single Reports destination (`/projects/:projectId/reports`).
 * The requirement report (templates, intro/chapters/appendices, filters; see
 * `RequirementReportPanel`) is always offered, first, and every other report
 * the backend catalogue lists for this project (module enabled, sub-component
 * enabled) is offered beside it in the same picker (`ReportCatalogue`,
 * Module 1 Phase 13). Nothing here names a module or a report: with no
 * catalogue reports the page is the requirement report alone, as before.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Project } from "../api/types";
import { ReportCatalogue } from "../components/ReportCatalogue";
import { RequirementReportPanel } from "../components/RequirementReportPanel";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useReportCatalogue } from "../hooks/useReportCatalogue";

export function ReportsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const catalogue = useReportCatalogue("project", projectId);

  useEffect(() => {
    if (!projectId) return;
    api
      .get<Project>(`/api/v1/projects/${projectId}`)
      .then(setProject)
      .catch((err) => showToast(toErrorMessage(err, strings.common.error), "error"));
  }, [projectId, showToast, strings.common.error]);

  if (!projectId || !project || catalogue.loading) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.reports.title}</h1>
      <ReportCatalogue
        entries={catalogue.entries}
        scope={{ kind: "project", id: projectId }}
        organizationId={project.organization_id}
        extraEntries={[
          {
            key: "requirements",
            title: "Requirements report",
            description: "The project's requirements as a document, with introduction, chapters, appendices and filters.",
            render: () => <RequirementReportPanel project={project} />,
          },
        ]}
      />
    </div>
  );
}
