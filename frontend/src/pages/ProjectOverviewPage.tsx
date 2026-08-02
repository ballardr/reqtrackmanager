import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Project, ProjectMetrics } from "../api/types";
import { STAGE_STATUS_LABEL } from "../api/types";
import { DonutChart } from "../components/DonutChart";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

interface ChangeEntry {
  timestamp: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string | null;
  detail: Record<string, unknown> | null;
}

/** Project overview dashboard (U-P-05): key metrics, status/outcome charts,
 * per-stage progress, and a recent activity feed at a glance. */
export function ProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [activity, setActivity] = useState<ChangeEntry[] | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
    api.get<ProjectMetrics>(`/api/v1/projects/${projectId}/metrics`).then(setMetrics);
    api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/changes`).then((entries) => setActivity(entries.slice(0, 8)));
  }, [projectId]);

  if (!project || !metrics) return <Spinner />;

  const tiles: Array<[string, string | number]> = [
    [strings.overview.requirementCount, metrics.requirement_count],
    [strings.overview.percentComplete, `${metrics.requirement_completed_percent}%`],
    [strings.overview.fileCount, metrics.file_count],
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

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <DonutChart title={strings.overview.requirementsByStatus} segments={Object.entries(metrics.requirements_by_status)} />
        <DonutChart
          title={strings.overview.changeRequestsChart}
          segments={[
            [strings.overview.crProposed, metrics.change_requests_proposed],
            [strings.overview.crApproved, metrics.change_requests_approved],
            [strings.overview.crRejected, metrics.change_requests_rejected],
          ]}
        />
        <div className="card stack">
          <div className="text-muted">{strings.overview.stageProgress}</div>
          {metrics.stage_progress.map((s) => (
            <div key={s.stage_id} className="stack" style={{ gap: "0.2rem" }}>
              <div className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
                <span>
                  {s.name} <span className="badge">{STAGE_STATUS_LABEL[s.status]}</span>
                </span>
                <span className="text-muted">{s.completed_percent}%</span>
              </div>
              <div style={{ background: "var(--color-surface-alt)", borderRadius: 4, height: 8, overflow: "hidden" }}>
                <div
                  style={{
                    width: `${s.completed_percent}%`,
                    background: "var(--color-primary)",
                    height: "100%",
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.overview.projectActivity}</h2>
        {activity && activity.length === 0 && <p className="text-muted">{strings.history.empty}</p>}
        {activity?.map((c, idx) => (
          <div
            key={idx}
            className="row"
            style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}
          >
            <span>
              <span className="badge">{c.entity_type}</span> {c.action}
              {c.detail && typeof c.detail.unique_code === "string" && ` — ${c.detail.unique_code}`}
              {c.detail && typeof c.detail.proposed_name === "string" && ` — ${c.detail.proposed_name}`}
            </span>
            <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
