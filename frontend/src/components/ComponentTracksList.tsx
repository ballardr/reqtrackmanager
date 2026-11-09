/**
 * Module: components/ComponentTracksList
 *
 * Every component's track through the stages when component phases are on, with a phase picker for each: the list shared by
 * project administration (where it also edits a track) and the "Stage phases" page (where a track's owner moves theirs).
 *
 * Responsibilities:
 * - Show one flat table row per component and stage (component, stage, phase, workflow, owner, state), in component then
 *   stage order; filter by stage and by "tracks I can move" so a project with many components and stages stays readable.
 * - Move a track (a closed phase first asks whether to complete the component's approved requirements too) and report it
 *   through `onChanged`; the server decides who may move (`can_move`), this list only disables the picker.
 *
 * Design decisions: a locked-phase move by a person who cannot make it is not offered as a choice; the server enforces it
 * regardless. Editing a track (workflow, applicability, owner) is offered only where the host passes `onEdit`.
 */
import { Pencil } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { Component, ComponentPhases, ComponentTrack, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useMutation } from "../hooks/useMutation";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { CheckboxField } from "./FormFields";
import { FilterSelect } from "./FilterSelect";
import { InlineSelect } from "./LabeledSelect";
import { PrincipalBadge } from "./PrincipalBadge";

/**
 * @param projectId The project.
 * @param state The component-phases state (its tracks).
 * @param stages The project's stages, in order.
 * @param components The project's components.
 * @param workflows The workflows the project may use (each track's phases come from its workflow).
 * @param onChanged Called after a move, so the host reloads.
 * @param onEdit Opens the host's track editor; omit it where the person cannot edit a track.
 */
export function ComponentTracksList({
  projectId, state, stages, components, workflows, onChanged, onEdit,
}: {
  projectId: string;
  state: ComponentPhases;
  stages: ProjectStage[];
  components: Component[];
  workflows: StageWorkflow[];
  onChanged: () => void;
  onEdit?: (track: ComponentTrack) => void;
}) {
  const strings = useStrings();
  const t = strings.componentPhases;
  const run = useMutation();
  const [stageFilter, setStageFilter] = useState("");
  const [movableOnly, setMovableOnly] = useState(false);
  const [closing, setClosing] = useState<{ track: ComponentTrack; phaseId: string; phaseName: string } | null>(null);
  const [cascade, setCascade] = useState(false);
  const base = `/api/v1/projects/${projectId}`;

  const rows = useMemo(() => {
    const componentOrder = new Map(components.map((c, index) => [c.id, index]));
    const stageOrder = new Map(stages.map((st, index) => [st.id, index]));
    return state.tracks
      .filter((track) => componentOrder.has(track.component_id) && stageOrder.has(track.stage_id))
      .filter((track) => (!stageFilter || track.stage_id === stageFilter) && (!movableOnly || track.can_move))
      .sort((x, y) =>
        (componentOrder.get(x.component_id) ?? 0) - (componentOrder.get(y.component_id) ?? 0)
        || (stageOrder.get(x.stage_id) ?? 0) - (stageOrder.get(y.stage_id) ?? 0));
  }, [state.tracks, components, stages, stageFilter, movableOnly]);

  async function move(track: ComponentTrack, phaseId: string, cascadeToRequirements: boolean) {
    const path = `${base}/components/${track.component_id}/stages/${track.stage_id}/transition`;
    if (await run(() => api.post(path, { phase_id: phaseId, cascade_to_requirements: cascadeToRequirements }), "save", t.nounSingular)) {
      onChanged();
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

  const nameOf = (list: { id: string; name: string }[], id: string) => list.find((item) => item.id === id)?.name ?? "";
  const columns: DirectoryColumn<ComponentTrack>[] = [
    { key: "component", label: t.component, render: (track) => <strong>{nameOf(components, track.component_id)}</strong> },
    { key: "stage", label: strings.componentPhases.stageColumn, render: (track) => nameOf(stages, track.stage_id) },
    {
      key: "phase", label: t.phaseColumn,
      render: (track) => {
        if (track.not_applicable) return <span className="text-muted">{t.noPhase}</span>;
        const phases = workflows.find((w) => w.id === track.workflow_id)?.phases ?? [{ id: track.phase_id, name: track.phase_name, kind: track.phase_kind }];
        return (
          <InlineSelect
            ariaLabel={t.track(nameOf(components, track.component_id), nameOf(stages, track.stage_id))} value={track.phase_id}
            placeholder={null} autoWidth disabled={!track.can_move} onChange={(next) => requestMove(track, next)}
            options={phases.map((p) => ({ value: p.id, label: p.name }))}
          />
        );
      },
    },
    { key: "workflow", label: t.workflow, render: (track) => track.workflow_name },
    { key: "owner", label: t.owner, render: (track) => <PrincipalBadge principal={track.owner} placeholder="" /> },
    {
      key: "state", label: t.stateColumn,
      render: (track) => (
        <span className="row">
          {track.not_applicable && <Badge>{t.notApplicableBadge}</Badge>}
          {track.customised && <Badge>{t.customisedBadge}</Badge>}
          {track.previous_closed && <Badge tone="info">{t.previousClosedBadge}</Badge>}
        </span>
      ),
    },
  ];
  if (onEdit) {
    columns.push({
      key: "actions", label: <span className="sr-only">{t.actionsColumn}</span>,
      render: (track) => {
        const name = t.editTrack(nameOf(components, track.component_id), nameOf(stages, track.stage_id));
        return <button className="btn" aria-label={name} title={name} onClick={() => onEdit(track)}><Pencil /></button>;
      },
    });
  }

  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        <FilterSelect
          label={t.filterStage} help={t.filterStageHelp} value={stageFilter} onChange={setStageFilter} allLabel={t.allStages}
          options={stages.map((s) => ({ value: s.id, label: s.name }))}
        />
        <CheckboxField help={t.movableOnlyHelp} label={t.movableOnly} checked={movableOnly} onChange={setMovableOnly} />
      </div>
      <DirectoryTable
        ariaLabel={t.tracksTable} columns={columns} rows={rows}
        rowKey={(track) => `${track.component_id}:${track.stage_id}`}
        emptyState={<div className="text-muted">{movableOnly ? t.noMovable : t.noTracks}</div>}
      />
      {closing && (
        <ConfirmDialog
          title={t.completeStage}
          message={<CheckboxField help={strings.help.cascadeToRequirementsComponent} label={t.cascadeToRequirements} checked={cascade} onChange={setCascade} />}
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
