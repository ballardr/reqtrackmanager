/**
 * Module: components/ComponentTracksList
 *
 * Every component's track through the stages when component phases are on, with a phase picker for each: the list shared by
 * project administration (where it also edits a track) and the "Delivery status" page (where a track's owner moves theirs).
 *
 * Responsibilities:
 * - Show one flat table row per component and stage (component, stage, phase, workflow, owner, state), in component then
 *   stage order; filter by stage and by "tracks I can move" so a project with many components and stages stays readable.
 * - Move a track (a closed phase first asks whether to complete the component's approved requirements too) and report it
 *   through `onChanged`; the server decides who may move (`can_move`), this list only disables the picker.
 * - With `plans`, also show each track's progress, expected range and overdue state (`utils/deliveryPlan`), and offer the
 *   same rows as a timeline (`view="timeline"`); `onSchedule` adds a control to set the current phase's expected range.
 *
 * Design decisions: a locked-phase move by a person who cannot make it is not offered as a choice; the server enforces it
 * regardless. Editing a track (workflow, applicability, owner) is offered only where the host passes `onEdit`.
 */
import { CalendarRange, Pencil } from "lucide-react";
import { useMemo, useState } from "react";

import type { Component, ComponentPhases, ComponentTrack, PhasePlan, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { usePhaseMove } from "../hooks/usePhaseMove";
import { formatDay, trackRows, type DeliveryRow } from "../utils/deliveryPlan";
import { Badge } from "./Badge";
import { DeliveryTimeline } from "./DeliveryTimeline";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { ProgressMeter } from "./ProgressMeter";
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
 * @param plans The project's phase plan rows; when given the list shows progress and dates.
 * @param view `"table"` (default) or `"timeline"`; the filters above apply to both.
 * @param onSchedule Opens the host's expected-range editor for a track's current phase; omit it where the person cannot.
 */
export function ComponentTracksList({
  projectId, state, stages, components, workflows, onChanged, onEdit, plans, view = "table", onSchedule,
}: {
  projectId: string;
  state: ComponentPhases;
  stages: ProjectStage[];
  components: Component[];
  workflows: StageWorkflow[];
  onChanged: () => void;
  onEdit?: (track: ComponentTrack) => void;
  plans?: PhasePlan[];
  view?: "table" | "timeline";
  onSchedule?: (track: ComponentTrack) => void;
}) {
  const strings = useStrings();
  const t = strings.componentPhases;
  const [stageFilter, setStageFilter] = useState("");
  const [movableOnly, setMovableOnly] = useState(false);
  const phaseMove = usePhaseMove(
    { title: t.completeStage, cascade: t.cascadeToRequirements, cascadeHelp: strings.help.cascadeToRequirementsComponent },
    "save", onChanged,
  );
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

  const planRows = useMemo(() => {
    const byKey = new Map<string, DeliveryRow>();
    if (plans) for (const row of trackRows(rows, workflows, plans)) byKey.set(row.key, row);
    return byKey;
  }, [plans, rows, workflows]);

  function requestMove(track: ComponentTrack, phaseId: string) {
    const phase = workflows.find((w) => w.id === track.workflow_id)?.phases.find((p) => p.id === phaseId);
    if (!phase) return;
    phaseMove.requestMove({ path: `${base}/components/${track.component_id}/stages/${track.stage_id}/transition`, phase, noun: t.nounSingular });
  }

  const nameOf = (list: { id: string; name: string }[], id: string) => list.find((item) => item.id === id)?.name ?? "";
  const columns: DirectoryColumn<ComponentTrack>[] = [
    { key: "component", label: t.component, render: (track) => <strong>{nameOf(components, track.component_id)}</strong> },
    { key: "stage", label: strings.componentPhases.stageColumn, render: (track) => nameOf(stages, track.stage_id) },
    {
      key: "phase", label: plans ? strings.deliveryPlan.currentPhaseColumn : t.phaseColumn,
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
    ...(plans ? planColumns(planRows, strings.deliveryPlan, (track) => [nameOf(components, track.component_id), nameOf(stages, track.stage_id)], onSchedule) : []),
    ...(plans ? [] : [{ key: "workflow", label: t.workflow, render: (track: ComponentTrack) => track.workflow_name }]),
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
      {plans && view === "timeline" ? (
        rows.length === 0 ? (
          <div className="text-muted">{movableOnly ? t.noMovable : t.noTracks}</div>
        ) : (
          <DeliveryTimeline
            items={rows.flatMap((track) => {
              const row = planRows.get(`${track.component_id}:${track.stage_id}`);
              return row ? [{ row, title: nameOf(components, track.component_id), subtitle: nameOf(stages, track.stage_id) }] : [];
            })}
            actions={onSchedule ? (item) => {
              const track = rows.find((r) => `${r.component_id}:${r.stage_id}` === item.row.key);
              return track && !track.not_applicable ? <ScheduleButton label={strings.deliveryPlan.scheduleAria(item.title, item.subtitle ?? "")} onClick={() => onSchedule(track)} /> : null;
            } : undefined}
          />
        )
      ) : (
        <DirectoryTable
          ariaLabel={plans ? strings.deliveryPlan.tracksTable : t.tracksTable} columns={columns} rows={rows}
          rowKey={(track) => `${track.component_id}:${track.stage_id}`}
          emptyState={<div className="text-muted">{movableOnly ? t.noMovable : t.noTracks}</div>}
        />
      )}
      {phaseMove.dialog}
    </div>
  );
}

/** The icon button that opens the expected-range editor of a row's current phase. */
function ScheduleButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button className="btn" aria-label={label} title={label} onClick={onClick}><CalendarRange /></button>;
}

/** Progress, expected range and overdue columns, read from the rows `trackRows` built. */
function planColumns(
  rows: Map<string, DeliveryRow>, t: ReturnType<typeof useStrings>["deliveryPlan"],
  namesOf: (track: ComponentTrack) => [string, string], onSchedule?: (track: ComponentTrack) => void,
): DirectoryColumn<ComponentTrack>[] {
  const rowOf = (track: ComponentTrack) => rows.get(`${track.component_id}:${track.stage_id}`);
  return [
    {
      key: "progress", label: t.progressColumn,
      render: (track) => {
        const row = rowOf(track);
        return row && !track.not_applicable
          ? <ProgressMeter value={row.completedPhases} max={row.totalPhases} label={t.progress(row.completedPhases, row.totalPhases)} />
          : "";
      },
    },
    {
      key: "expected", label: t.expectedColumn,
      render: (track) => {
        const row = rowOf(track);
        if (!row || track.not_applicable) return "";
        return (
          <span className="row" style={{ gap: "var(--space-2)" }}>
            {row.expectedFrom && row.expectedTo
              ? t.expectedRange(formatDay(row.expectedFrom), formatDay(row.expectedTo))
              : <span className="text-muted">{t.noDates}</span>}
            {row.overdue && <Badge tone="danger">{t.overdue}</Badge>}
            {onSchedule && <ScheduleButton label={t.scheduleAria(...namesOf(track))} onClick={() => onSchedule(track)} />}
          </span>
        );
      },
    },
  ];
}
