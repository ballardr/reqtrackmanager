import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Project, ProjectMetrics } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Project overview dashboard (U-P-05): key metrics at a glance. */
export function ProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
    api.get<ProjectMetrics>(`/api/v1/projects/${projectId}/metrics`).then(setMetrics);
  }, [projectId]);

  if (!project || !metrics) return <Spinner />;

  const tiles: Array<[string, string | number]> = [
    [strings.overview.requirementCount, metrics.requirement_count],
    [strings.overview.percentComplete, `${metrics.requirement_completed_percent}%`],
    [strings.overview.crProposed, metrics.change_requests_proposed],
    [strings.overview.crApproved, metrics.change_requests_approved],
    [strings.overview.crRejected, metrics.change_requests_rejected],
  ];

  return (
    <div className="stack">
      <div>
        <h1 style={{ margin: 0 }}>{project.name}</h1>
        <p className="text-muted">{project.summary}</p>
      </div>
      <div className="grid grid-metrics">
        {tiles.map(([label, value]) => (
          <div key={label} className="card stack" style={{ alignItems: "center", textAlign: "center" }}>
            <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
            <div className="text-muted">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
