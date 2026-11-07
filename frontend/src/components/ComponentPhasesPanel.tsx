/**
 * Module: components/ComponentPhasesPanel
 *
 * Project administration of component phases. A switch (off, on, or follow the parent project) decides
 * whether each component follows its own workflow for each stage; when it is on, every component lists its
 * track per stage with a phase picker (moving it applies the phase kind's behaviour on the server: a locked
 * phase approves only that component's requirements for the stage), its owner and an edit dialog for the
 * workflow, applicability and owner. Progression between stages is advisory: a badge says when the previous
 * stage has closed for the component, and nothing is blocked otherwise.
 */
import { Pencil } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { Component, ComponentPhases, ComponentTrack, OrgUser, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { Badge } from "./Badge";
import { ComponentTrackEditor, type ComponentTrackChanges } from "./ComponentTrackEditor";
import { ConfirmDialog } from "./ConfirmDialog";
import { CheckboxField } from "./FormFields";
import { InlineSelect, LabeledSelect } from "./LabeledSelect";
import { PrincipalBadge } from "./PrincipalBadge";

const INHERIT = "inherit";

/**
 * @param projectId The project being administered.
 * @param organizationId Its organisation (owner picker).
 * @param orgUsers The organisation's users (owner picker).
 * @param onChanged Called after any change, so a page showing stage state elsewhere can reload.
 */
export function ComponentPhasesPanel({
  projectId, organizationId, orgUsers, onChanged,
}: { projectId: string; organizationId: string; orgUsers: OrgUser[]; onChanged?: () => void }) {
  const strings = useStrings();
  const run = useMutation();
  const [state, setState] = useState<ComponentPhases | null>(null);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [workflows, setWorkflows] = useState<StageWorkflow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ComponentTrack | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [closing, setClosing] = useState<{ track: ComponentTrack; phaseId: string; phaseName: string } | null>(null);
  const [cascade, setCascade] = useState(false);
  const base = `/api/v1/projects/${projectId}`;

  const reload = useCallback(async () => {
    try {
      const [phases, stageList, componentList, workflowList] = await Promise.all([
        api.get<ComponentPhases>(`${base}/component-stages`),
        api.get<ProjectStage[]>(`${base}/stages`),
        api.get<Component[]>(`${base}/components`),
        api.get<StageWorkflow[]>(`${base}/stage-workflows`),
      ]);
      setState(phases);
      setStages(stageList);
      setComponents(componentList);
      setWorkflows(workflowList);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, strings.componentPhases.loadFailed));
    }
  }, [base, strings.componentPhases.loadFailed]);

  useLoadOnChange(reload, [base]);

  async function setMode(value: string) {
    const mode = value === INHERIT ? null : value;
    if (await run(() => api.put(`${base}/component-phases-settings`, { mode }), "save", strings.componentPhases.nounModeSetting)) {
      await reload();
      onChanged?.();
    }
  }

  async function move(track: ComponentTrack, phaseId: string, cascadeToRequirements: boolean) {
    const path = `${base}/components/${track.component_id}/stages/${track.stage_id}/transition`;
    if (await run(() => api.post(path, { phase_id: phaseId, cascade_to_requirements: cascadeToRequirements }), "save", strings.componentPhases.nounSingular)) {
      await reload();
      onChanged?.();
    }
  }

  function requestMove(track: ComponentTrack, phaseId: string) {
    const phase = workflows.find((w) => w.id === track.workflow_id)?.phases.find((p) => p.id === phaseId);
    if (phase?.kind === "closed") {
      setCascade(false);
      setClosing({ track, phaseId, phaseName: phase.name });
    } else {
      void move(track, phaseId, false);
    }
  }

  async function save(track: ComponentTrack, changes: ComponentTrackChanges) {
    setSaveError(null);
    if (Object.keys(changes).length > 0) {
      try {
        await api.patch(`${base}/components/${track.component_id}/stages/${track.stage_id}/track`, changes);
      } catch (err) {
        setSaveError(toErrorMessage(err, strings.mutation.failure("save", strings.componentPhases.nounSingular)));
        return;
      }
    }
    setEditing(null);
    await reload();
    onChanged?.();
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!state) return null;
  const modeLabel = state.mode === "on" ? strings.componentPhases.modeOn : strings.componentPhases.modeOff;
  const editingComponent = editing ? components.find((c) => c.id === editing.component_id) : undefined;
  const editingStage = editing ? stages.find((s) => s.id === editing.stage_id) : undefined;
  return (
    <div className="stack">
      <LabeledSelect
        label={strings.componentPhases.mode} help={strings.help.componentPhasesMode} placeholder={null}
        value={state.own_mode ?? INHERIT} onChange={(value) => void setMode(value)}
        options={[
          { value: "off", label: strings.componentPhases.modeOff },
          { value: "on", label: strings.componentPhases.modeOn },
          { value: INHERIT, label: strings.componentPhases.modeInherit },
        ]}
      />
      {state.own_mode === null && <div className="text-muted">{strings.componentPhases.inheritedNote(modeLabel)}</div>}
      {state.mode === "off" && <div className="text-muted">{strings.componentPhases.off}</div>}
      {state.mode === "on" && (components.length === 0 || stages.length === 0) && (
        <div className="text-muted">{strings.componentPhases.noTracks}</div>
      )}
      {state.mode === "on" && components.map((component) => (
        <div key={component.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}>
          <strong>{component.name}</strong>
          {stages.map((stage) => {
            const track = state.tracks.find((t) => t.component_id === component.id && t.stage_id === stage.id);
            if (!track) return null;
            const phases = workflows.find((w) => w.id === track.workflow_id)?.phases ?? [{ id: track.phase_id, name: track.phase_name }];
            return (
              <div key={stage.id} className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <span style={{ minWidth: "10rem" }}>{stage.name}</span>
                  {track.not_applicable ? (
                    <Badge>{strings.componentPhases.notApplicableBadge}</Badge>
                  ) : (
                    <InlineSelect
                      ariaLabel={strings.componentPhases.track(component.name, stage.name)} value={track.phase_id} placeholder={null}
                      maxWidth={220} disabled={!track.can_move} onChange={(next) => requestMove(track, next)}
                      options={phases.map((p) => ({ value: p.id, label: p.name }))}
                    />
                  )}
                  {track.customised && <Badge>{track.workflow_name}</Badge>}
                  {track.previous_closed && <Badge tone="info">{strings.componentPhases.previousClosedBadge}</Badge>}
                </div>
                <div className="row">
                  <PrincipalBadge principal={track.owner} placeholder="" />
                  <button
                    className="btn" aria-label={strings.componentPhases.editTrack(component.name, stage.name)}
                    title={strings.componentPhases.editTrack(component.name, stage.name)}
                    onClick={() => { setSaveError(null); setEditing(track); }}
                  >
                    <Pencil />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ))}
      {editing && editingComponent && editingStage && (
        <ComponentTrackEditor
          track={editing} componentName={editingComponent.name} stageName={editingStage.name} workflows={workflows}
          orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} error={saveError}
          onCancel={() => setEditing(null)} onSave={(changes) => void save(editing, changes)}
        />
      )}
      {closing && (
        <ConfirmDialog
          title={strings.componentPhases.completeStage}
          message={<CheckboxField helpNotNeeded label={strings.componentPhases.cascadeToRequirements} checked={cascade} onChange={setCascade} />}
          confirmLabel={closing.phaseName}
          onConfirm={() => {
            const { track, phaseId } = closing;
            setClosing(null);
            void move(track, phaseId, cascade);
          }}
          onCancel={() => setClosing(null)}
        />
      )}
    </div>
  );
}
