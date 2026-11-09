/**
 * Module: pages/ProjectStagePhasesPage
 *
 * "Stage phases": where the people who work in a project see which phase each stage is in and move the component tracks they
 * own, without a visit to project administration (a settings page a track's owner may not be able to use).
 *
 * Responsibilities:
 * - List the project's stages with their workflow, current phase and owner (read only; a manager moves a stage in
 *   project administration, where its workflow and schedule are set).
 * - When component phases are on, list every component's track with a phase picker (`ComponentTracksList`), enabled only for
 *   the tracks the person may move (a project manager, or the track's owner), filterable to those.
 *
 * Design decisions: one shared track list serves this page and project administration, so the two cannot drift; the server
 * decides who may move a track (`can_move`), this page only reflects it.
 */
import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Component, ComponentPhases, ProjectStage, StageWorkflow } from "../api/types";
import { Badge } from "../components/Badge";
import { ComponentTracksList } from "../components/ComponentTracksList";
import { PrincipalBadge } from "../components/PrincipalBadge";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { stagePhaseLabel } from "../utils/stageBadge";

export function ProjectStagePhasesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const strings = useStrings();
  const t = strings.stagePhases;
  const [stages, setStages] = useState<ProjectStage[] | null>(null);
  const [state, setState] = useState<ComponentPhases | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [workflows, setWorkflows] = useState<StageWorkflow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const base = `/api/v1/projects/${projectId}`;

  const load = useCallback(async () => {
    try {
      const [stageList, phases, componentList, workflowList] = await Promise.all([
        api.get<ProjectStage[]>(`${base}/stages`),
        api.get<ComponentPhases>(`${base}/component-stages`),
        api.get<Component[]>(`${base}/components`),
        api.get<StageWorkflow[]>(`${base}/stage-workflows`),
      ]);
      setStages(stageList);
      setState(phases);
      setComponents(componentList);
      setWorkflows(workflowList);
      setError(null);
    } catch (err) {
      setError(toErrorMessage(err, t.loadFailed));
    }
  }, [base, t.loadFailed]);
  useLoadOnChange(load, [base]);

  if (error) return <p style={{ color: "var(--color-danger)" }}>{error}</p>;
  if (!stages || !state) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{t.title}</h1>
      <section className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t.stagesHeading}</h2>
        {stages.length === 0 && <p className="text-muted">{t.noStages}</p>}
        {stages.map((stage) => (
          <div key={stage.id} className="row" style={{ justifyContent: "space-between" }}>
            <div className="row">
              <strong style={{ minWidth: "10rem" }}>{stage.name}</strong>
              <Badge>{stagePhaseLabel(stage.phase_name, stage.phase_kind)}</Badge>
              <span className="text-muted">{stage.workflow_name}</span>
            </div>
            <PrincipalBadge principal={stage.owner} placeholder="" />
          </div>
        ))}
      </section>
      <section className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t.componentsHeading}</h2>
        {state.mode === "off" ? (
          <p className="text-muted">{t.componentPhasesOff}</p>
        ) : components.length === 0 || stages.length === 0 ? (
          <p className="text-muted">{strings.componentPhases.noTracks}</p>
        ) : (
          <ComponentTracksList
            projectId={projectId ?? ""} state={state} stages={stages} components={components} workflows={workflows}
            onChanged={() => void load()}
          />
        )}
      </section>
    </div>
  );
}
