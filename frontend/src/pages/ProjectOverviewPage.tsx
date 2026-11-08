import { Plus, SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { OverviewLayout, Project, ProjectAncestor, ProjectHierarchySummary, ProjectListItem } from "../api/types";
import { EntitySwitcher } from "../components/EntitySwitcher";
import { OverviewEditor } from "../components/overview/OverviewEditor";
import { OverviewWidgetGrid } from "../components/overview/OverviewWidgetGrid";
import { ProjectHierarchyLabels } from "../components/ProjectHierarchyLabels";
import { ReportsButton } from "../components/ReportsButton";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useOverviewMetrics } from "../hooks/useOverviewMetrics";
import { loadProjectSwitcherOptions } from "../utils/entitySwitcherLoaders";
import { Badge } from "../components/Badge";
import { Tooltip } from "../components/Tooltip";
import { useResetOnChange } from "../hooks/useResetOnChange";

/** Project overview dashboard (U-P-05): the widgets of the layout in force, which a project manager arranges
 * ("Customise overview"). The built-in layout is the key metrics, a total-records chart split by record type,
 * status and outcome charts, per-stage progress and a recent activity feed. Every tile, chart segment and
 * stage bar navigates to the list it summarises, pre-filtered to match what was clicked (UX review).
 * The figures of every visible widget arrive in one batched request (`useOverviewMetrics`); a module's tiles
 * and widgets come from the registry, so this page never imports a specific module. */
export function ProjectOverviewPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [layout, setLayout] = useState<OverviewLayout | null>(null);
  const [editing, setEditing] = useState(false);
  // Hierarchical projects (docs/decisions.md): root-first ancestor
  // breadcrumb and "Child of/Parent of" labels, previously shown on
  // ProjectListPage/FavouritesPage but never here. Both default to `[]`
  // rather than `null` — an empty result (no parent/no children, or every
  // ancestor redacted) is a normal, renderable state, not a loading one,
  // so these don't gate the page's initial `<Spinner />` the way
  // project/layout do.
  const [ancestors, setAncestors] = useState<ProjectAncestor[]>([]);
  const [children, setChildren] = useState<ProjectListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Each figure is read in its widget's project scope, else the overview's (set in "Customise overview").
  const metrics = useOverviewMetrics(projectId, layout?.widgets ?? null, layout?.scope ?? "this", strings.common.error);

  useResetOnChange([projectId], () => setLoadError(null));

  const loadLayout = useCallback(() => {
    if (!projectId) return;
    api
      .get<OverviewLayout>(`/api/v1/projects/${projectId}/overview-layout`)
      .then(setLayout)
      .catch((err: unknown) => setLoadError(err instanceof ApiError ? err.message : strings.common.error));
  }, [projectId, strings.common.error]);

  useEffect(() => {
    if (!projectId) return;
    const onError = (err: unknown) => setLoadError(err instanceof ApiError ? err.message : strings.common.error);
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject).catch(onError);
    api.get<ProjectAncestor[]>(`/api/v1/projects/${projectId}/ancestors`).then(setAncestors).catch(onError);
    api.get<ProjectListItem[]>(`/api/v1/projects/${projectId}/children`).then(setChildren).catch(onError);
    loadLayout();
  }, [projectId, strings.common.error, loadLayout]);

  if (loadError) return <p style={{ color: "var(--color-danger)" }}>{loadError}</p>;
  if (!project || !layout || !metrics.results) return <Spinner />;

  // Built from the single-`Project` GET response plus the `children` list
  // fetched above — `ProjectOverviewPage` has no `ProjectListItem` of its
  // own (list-only fields like `current_stage_name`/`my_roles` don't apply
  // to a single-project dashboard), so this assembles just the fields
  // `ProjectHierarchyLabels` actually needs (see `ProjectHierarchySummary`).
  const hierarchySummary: ProjectHierarchySummary = {
    id: project.id,
    parent_project_id: project.parent_project_id,
    parent_project_name: project.parent_project_name,
    children,
  };

  return (
    <div className="stack">
      {ancestors.length > 0 && (
        <div className="text-muted" style={{ fontSize: "0.85rem" }}>
          {ancestors.map((a) => (
            <span key={a.id}>
              <Link to={`/projects/${a.id}`}>{a.name}</Link>
              {" / "}
            </span>
          ))}
          {project.name}
        </div>
      )}
      <div className="row" style={{ alignItems: "center", flexWrap: "wrap", gap: "var(--space-2)" }}>
        <h1 style={{ margin: 0 }}>{project.name}</h1>
        {project.is_template && (
          <Tooltip label={strings.projects.templateReadOnlyHelp} wrap>
            <Badge>{strings.projects.template}</Badge>
          </Tooltip>
        )}
        <EntitySwitcher
          label="Switch project"
          currentId={project.id}
          loadOptions={() => loadProjectSwitcherOptions("overview")}
        />
        {!editing && (
          <div className="row" style={{ marginLeft: "auto", alignItems: "center" }}>
            {layout.can_customise && (
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                <SlidersHorizontal /> {strings.overviewWidgets.customise}
              </button>
            )}
            <ReportsButton scope={{ kind: "project", id: project.id }} organizationId={project.organization_id} project={project} />
            <Link className="btn btn-primary" to={`/projects/${projectId}/requirements?new=1`}>
              <Plus /> {strings.requirements.newRequirement}
            </Link>
          </div>
        )}
      </div>
      <div>
        <p className="text-muted" style={{ margin: 0 }}>{project.summary}</p>
        <ProjectHierarchyLabels project={hierarchySummary} />
      </div>
      {metrics.error && <p style={{ color: "var(--color-danger)" }}>{metrics.error}</p>}
      {editing && projectId ? (
        <OverviewEditor
          target={{ kind: "project", projectId }} onCancel={() => setEditing(false)}
          onSaved={() => { setEditing(false); loadLayout(); }}
        />
      ) : (
        <OverviewWidgetGrid widgets={layout.widgets} scope={layout.scope} metrics={metrics} projectId={project.id} />
      )}
    </div>
  );
}
