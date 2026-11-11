/**
 * Module: pages/ProjectStagePhasesPage
 *
 * Delivery status: where the people who work in a project see each stage and each component's track through the stages,
 * how far along it is, when it is expected to finish and whether it is overdue, and keep its state up to date in place,
 * without a visit to project administration (a settings page a track's owner may not be able to use).
 *
 * Responsibilities:
 * - Show the stages with their current phase, owner, progress and expected range, as a table or a timeline
 *   (`StagePlanTable`); a project manager moves a stage and sets its dates here.
 * - When component phases are on (and only then), show a second section with every component's track the same way (`ComponentTracksList`), with a phase picker
 *   enabled only for the tracks the person may move (a project manager, or the track's owner) and, for a manager, the
 *   expected range of the track's current phase.
 * - Remember the table or timeline choice per person (`useUiPreference`).
 *
 * Design decisions: composed in the browser from the existing bulk reads (stages, component tracks, phase plans), so there
 * is one server definition of who may move what and no second one of progress or overdue (`utils/deliveryPlan`); the
 * server decides who may move a track (`can_move`) and set a date, this page only reflects it.
 */
import { ChartGantt, Table2 } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Component, ComponentPhases, PhasePlans, ProjectStage, StageWorkflow } from "../api/types";
import { ComponentTracksList } from "../components/ComponentTracksList";
import { Spinner } from "../components/Spinner";
import { StagePlanTable } from "../components/StagePlanTable";
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
