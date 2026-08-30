import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ChangeEntry, Project, ProjectMetrics, RequirementStatus } from "../api/types";
import { activityEntityLabel, activityEntryLink, describeActivityEntry, REQUIREMENT_STATUS_LABEL, STAGE_STATUS_LABEL } from "../api/types";
import { Spinner } from "../components/Spinner";
import { StatusPieChart } from "../components/StatusPieChart";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";

/** Project overview dashboard (U-P-05): key metrics, status/outcome charts,
 * per-stage progress, and a recent activity feed at a glance. Every
 * tile/chart-segment/stage-bar navigates to the requirements or change
 * requests list pre-filtered to match what was clicked (UX review) — see
 * the `to` path built alongside each metric below. */
export function ProjectOverviewPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const orgLabelCap = useOrgLabelCapitalized();
  const [project, setProject] = useState<Project | null>(null);
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [activity, setActivity] = useState<ChangeEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setLoadError(null);
    const onError = (err: unknown) => setLoadError(err instanceof ApiError ? err.message : strings.common.error);
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject).catch(onError);
    api.get<ProjectMetrics>(`/api/v1/projects/${projectId}/metrics`).then(setMetrics).catch(onError);
    api
      .get<ChangeEntry[]>(`/api/v1/projects/${projectId}/changes`)
      .then((entries) => setActivity(entries.slice(0, 8)))
      .catch(onError);
  }, [projectId, strings.common.error]);

  if (loadError) return <p style={{ color: "var(--color-danger)" }}>{loadError}</p>;
  if (!project || !metrics) return <Spinner />;

  const requirementsPath = (query?: string) => `/projects/${projectId}/requirements${query ? `?${query}` : ""}`;
  const changeRequestsPath = (status: string) => `/projects/${projectId}/change-requests?status=${status}`;

  const tiles: Array<[string, string | number, string]> = [
    [strings.overview.requirementCount, metrics.requirement_count, requirementsPath()],
    // C-G-11: completion is `Requirement.is_completed`, an independent
    // overlay marker, not a `status` value — links to the requirements
    // list's own "Completed" filter checkbox rather than a status filter
    // (RequirementsPage.tsx seeds `completedFilter` from this same param).
    [strings.overview.percentComplete, `${metrics.requirement_completed_percent}%`, requirementsPath("completed=1")],
    // Links to the project-wide file browser (ProjectFilesPage), not the
    // unfiltered requirements list — a bug flagged separately from this
    // page's other tiles, which correctly link to a requirements/change-
    // requests view that actually reflects what was clicked.
    [strings.overview.fileCount, metrics.file_count, `/projects/${projectId}/files`],
    [strings.overview.crProposed, metrics.change_requests_proposed, changeRequestsPath("active")],
    [strings.overview.crApproved, metrics.change_requests_approved, changeRequestsPath("approved")],
    [strings.overview.crRejected, metrics.change_requests_rejected, changeRequestsPath("rejected")],
  ];

  const statusEntries = Object.entries(metrics.requirements_by_status) as Array<[RequirementStatus, number]>;
  const crStatusEntries: Array<[string, number]> = [
    ["active", metrics.change_requests_proposed],
    ["approved", metrics.change_requests_approved],
    ["rejected", metrics.change_requests_rejected],
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ margin: 0 }}>{project.name}</h1>
          <p className="text-muted">{project.summary}</p>
        </div>
        <Link className="btn btn-primary" to={`/projects/${projectId}/requirements?new=1`}>
          <Plus size={16} /> {strings.requirements.newRequirement}
        </Link>
      </div>
      <div className="grid grid-metrics">
        {tiles.map(([label, value, to]) => (
          <Link
            key={label} to={to} className="card stack"
            style={{ alignItems: "center", textAlign: "center", textDecoration: "none", color: "inherit" }}
          >
            <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
            <div className="text-muted">{label}</div>
          </Link>
        ))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <StatusPieChart
          title={strings.overview.requirementsByStatus}
          segments={statusEntries.map(([status, count]) => [REQUIREMENT_STATUS_LABEL[status] ?? status, count])}
          onSegmentClick={(_, idx) => navigate(requirementsPath(`status=${statusEntries[idx][0]}`))}
        />
        <StatusPieChart
          title={strings.overview.changeRequestsChart}
          segments={[
            [strings.overview.crProposed, metrics.change_requests_proposed],
            [strings.overview.crApproved, metrics.change_requests_approved],
            [strings.overview.crRejected, metrics.change_requests_rejected],
          ]}
          onSegmentClick={(_, idx) => navigate(changeRequestsPath(crStatusEntries[idx][0]))}
        />
        <div className="card stack">
          <div className="text-muted">{strings.overview.stageProgress}</div>
          {metrics.stage_progress.map((s) => (
            <Link
              key={s.stage_id} to={requirementsPath(`stage=${s.stage_id}`)}
              className="stack" style={{ gap: "0.2rem", textDecoration: "none", color: "inherit" }}
            >
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
            </Link>
          ))}
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.overview.projectActivity}</h2>
        {activity && activity.length === 0 && <p className="text-muted">{strings.history.empty}</p>}
        {activity?.map((c, idx) => {
          const link = projectId ? activityEntryLink(c, projectId) : null;
          return (
            <div
              key={idx}
              className="row"
              style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}
            >
              <span>
                <span className="badge">{activityEntityLabel(c.entity_type, orgLabelCap)}</span> {describeActivityEntry(c)}
                {link && (
                  <>
                    {" "}
                    <Link to={link.to}>{link.label}</Link>
                  </>
                )}
              </span>
              <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
