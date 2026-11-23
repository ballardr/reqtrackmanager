/**
 * Module: pages/ProjectStagePhasesPage
 *
 * Delivery status: each stage and each component's track through the stages, its progress, expected finish and overdue state, kept up to
 * date in place without project administration. Shows stages with phase, owner, progress and range as a table or timeline
 * (`StagePlanTable`; a manager moves a stage and sets dates) and, when component phases are on, every component's track
 * (`ComponentTracksList`; a manager or the track's owner moves it). The view is remembered per person (`useUiPreference`); a link to Project
 * Admin's stages shows only to someone who may change them. Composed in the browser from the bulk reads, so the server alone defines who may
 * move what (`can_move`) and progress and overdue have one definition (`utils/deliveryPlan`).
 */
import { ChartGantt, Settings, Table2 } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Component, ComponentPhases, PhasePlans, ProjectStage, StageWorkflow } from "../api/types";
import { ComponentTracksList } from "../components/ComponentTracksList";
import { Spinner } from "../components/Spinner";
import { StagePlanTable } from "../components/StagePlanTable";
import { Tooltip } from "../components/Tooltip";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { usePhaseRangeEditor } from "../hooks/usePhaseRangeEditor";
import { useUiPreference } from "../hooks/useUiPreference";

export function ProjectStagePhasesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const strings = useStrings();
  const t = strings.stagePhases;
  const [stages, setStages] = useState<ProjectStage[] | null>(null);
  const [state, setState] = useState<ComponentPhases | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [workflows, setWorkflows] = useState<StageWorkflow[]>([]);
  const [plans, setPlans] = useState<PhasePlans | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storedView, setView] = useUiPreference<string>("stage_phases.view", "table");
  const view = storedView === "timeline" ? "timeline" : "table";
  const base = `/api/v1/projects/${projectId}`;

  const load = useCallback(async () => {
    try {
      const [stageList, phases, componentList, workflowList, planList] = await Promise.all([
        api.get<ProjectStage[]>(`${base}/stages`),
        api.get<ComponentPhases>(`${base}/component-stages`),
        api.get<Component[]>(`${base}/components`),
        api.get<StageWorkflow[]>(`${base}/stage-workflows`),
        api.get<PhasePlans>(`${base}/phase-plans`),
      ]);
      setStages(stageList);
      setState(phases);
      setComponents(componentList);
      setWorkflows(workflowList);
      setPlans(planList);
      setError(null);
    } catch (err) {
      setError(toErrorMessage(err, t.loadFailed));
    }
  }, [base, t.loadFailed]);
  useLoadOnChange(load, [base]);
  const rangeEditor = usePhaseRangeEditor(base, () => void load());

  if (error) return <p style={{ color: "var(--color-danger)" }}>{error}</p>;
  if (!stages || !state || !plans) return <Spinner />;

  const canManage = stages.some((stage) => stage.can_lock);
  const planOf = (stageId: string, componentId: string | null, phaseId: string) =>
    plans.plans.find((p) => p.stage_id === stageId && p.component_id === componentId && p.phase_id === phaseId);
  const viewButton = (mode: "table" | "timeline", label: string, icon: ReactNode) => (
    <button className={`btn ${view === mode ? "btn-primary" : ""}`} aria-label={label} title={label} aria-pressed={view === mode} onClick={() => setView(mode)}>
      {icon}
    </button>
  );

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{t.title}</h1>
        <div className="row" role="group" aria-label={strings.deliveryPlan.viewAria} style={{ gap: "var(--space-1)" }}>
          {viewButton("table", strings.deliveryPlan.viewTable, <Table2 />)}
          {viewButton("timeline", strings.deliveryPlan.viewTimeline, <ChartGantt />)}
          {canManage && (
            <Tooltip label={t.settingsLink}>
              <Link to={`/projects/${projectId}/admin/stagesPhases`} className="btn btn-icon" aria-label={t.settingsLink}>
                <Settings />
              </Link>
            </Tooltip>
          )}
        </div>
      </div>
      <section className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t.stagesHeading}</h2>
        {stages.length === 0 ? (
          <p className="text-muted">{t.noStages}</p>
        ) : (
          <StagePlanTable
            projectId={projectId ?? ""} stages={stages} workflows={workflows} plans={plans.plans} canManage={canManage} view={view}
            onChanged={() => void load()}
            onSchedule={canManage ? (stage) => {
              const row = planOf(stage.id, null, stage.phase_id);
              rangeEditor.open({
                stageId: stage.id, componentId: null, phaseId: stage.phase_id, title: strings.phaseSchedule.editTitle(stage.name, stage.phase_name),
                expectedFrom: row?.expected_from ?? null, expectedTo: row?.expected_to ?? null,
              });
            } : undefined}
          />
        )}
      </section>
      {state.mode !== "off" && (
        <section className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t.componentsHeading}</h2>
          {components.length === 0 || stages.length === 0 ? (
            <p className="text-muted">{strings.componentPhases.noTracks}</p>
          ) : (
            <ComponentTracksList
              projectId={projectId ?? ""} state={state} stages={stages} components={components} workflows={workflows}
              plans={plans.plans} view={view} onChanged={() => void load()}
              onSchedule={canManage ? (track) => {
                const stage = stages.find((s) => s.id === track.stage_id);
                const component = components.find((c) => c.id === track.component_id);
                const row = planOf(track.stage_id, track.component_id, track.phase_id);
                rangeEditor.open({
                  stageId: track.stage_id, componentId: track.component_id, phaseId: track.phase_id,
                  title: strings.componentPhases.editTitle(component?.name ?? "", stage?.name ?? ""),
                  expectedFrom: row?.expected_from ?? null, expectedTo: row?.expected_to ?? null,
                });
              } : undefined}
            />
          )}
        </section>
      )}
      {rangeEditor.dialog}
    </div>
  );
}
