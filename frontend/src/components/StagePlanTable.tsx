/**
 * Module: components/StagePlanTable
 *
 * The project's stages on the delivery status page: each stage's current phase (movable in place by a project manager),
 * owner, progress, expected range and overdue state (the stage always; the rest through the column chooser), as a
 * table or, with `view="timeline"`, as bars on the shared axis.
 *
 * Responsibilities: one row per stage from `utils/deliveryPlan.stageRows`; the phase picker moves a stage through the
 * shared `usePhaseMove` (a closed phase first asks about completing its requirements); a locked phase is shown
 * unavailable with the reason to a person who cannot enter or leave it (the server enforces it), as is a phase the
 * project's lifecycle does not allow (`utils/phaseOptions`); `onSchedule` adds a control to set the current phase's
 * expected range, for a manager.
 *
 * Design decision: the same columns and wording as `ComponentTracksList`; a stage's workflow, owner and name are edited
 * in project administration.
 */
import { CalendarRange } from "lucide-react";

import type { PhasePlan, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useOptionalColumns } from "../hooks/useOptionalColumns";
import { usePhaseMove } from "../hooks/usePhaseMove";
import { useTableSort } from "../hooks/useTableSort";
import { formatDay, stageRows, type DeliveryRow } from "../utils/deliveryPlan";
import { phaseOptions } from "../utils/phaseOptions";
import { Badge } from "./Badge";
import { DeliveryTimeline } from "./DeliveryTimeline";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { InlineSelect } from "./LabeledSelect";
import { PrincipalBadge } from "./PrincipalBadge";
import { ProgressMeter } from "./ProgressMeter";

/**
 * @param projectId The project.
 * @param stages The project's stages, in order.
 * @param workflows The workflows the stages follow (each stage's phases come from its workflow).
 * @param plans The project's phase plan rows.
 * @param canManage Whether the caller manages the project (may move a stage and set its dates).
 * @param view `"table"` (default) or `"timeline"`.
 * @param onChanged Called after a move, so the host reloads.
 * @param onSchedule Opens the host's expected-range editor for a stage's current phase; omit it where the person cannot.
 */
export function StagePlanTable({
  projectId, stages, workflows, plans, canManage, view = "table", onChanged, onSchedule,
}: {
  projectId: string;
  stages: ProjectStage[];
  workflows: StageWorkflow[];
  plans: PhasePlan[];
  canManage: boolean;
  view?: "table" | "timeline";
  onChanged: () => void;
  onSchedule?: (stage: ProjectStage) => void;
}) {
  const strings = useStrings();
  const t = strings.deliveryPlan;
  const phaseMove = usePhaseMove(
    { title: strings.admin.completeStage, cascade: strings.admin.cascadeToRequirements, cascadeHelp: strings.help.cascadeToRequirementsStage },
    "move", onChanged,
  );
  const rows = new Map<string, DeliveryRow>(stageRows(stages, workflows, plans, canManage).map((row) => [row.key, row]));
  const scheduleLabel = (stage: ProjectStage) => t.scheduleAria(stage.name, "");
  const table = useTableSort(stages, {
    stage: (stage) => stage.name,
    phase: (stage) => stage.phase_name,
    owner: (stage) => stage.owner?.label ?? null,
    progress: (stage) => rows.get(stage.id)?.progress ?? null,
    expected: (stage) => rows.get(stage.id)?.expectedFrom ?? null,
  });

  const columns: DirectoryColumn<ProjectStage>[] = [
    { key: "stage", label: strings.componentPhases.stageColumn, sortable: true, render: (stage) => <strong>{stage.name}</strong> },
    {
      key: "phase", label: t.currentPhaseColumn, sortable: true, optional: true,
      render: (stage) => {
        const phases = workflows.find((w) => w.id === stage.workflow_id)?.phases ?? [{ id: stage.phase_id, name: stage.phase_name, kind: stage.phase_kind }];
        return (
          <InlineSelect
            ariaLabel={strings.stageWorkflows.changePhaseAria(stage.name)} value={stage.phase_id} placeholder={null} autoWidth
            disabled={!canManage}
            onChange={(next) => {
              const phase = phases.find((p) => p.id === next);
              if (phase && phase.id !== stage.phase_id) {
                phaseMove.requestMove({ path: `/api/v1/projects/${projectId}/stages/${stage.id}/transition`, phase, noun: "{stage}" });
              }
            }}
            options={phaseOptions(strings.stageWorkflows, phases, stage, Boolean(stage.can_lock))}
          />
        );
      },
    },
    { key: "owner", label: strings.componentPhases.owner, sortable: true, optional: true, render: (stage) => <PrincipalBadge principal={stage.owner} placeholder="" /> },
    {
      key: "progress", label: t.progressColumn, sortable: true, optional: true,
      render: (stage) => {
        const row = rows.get(stage.id);
        return row ? <ProgressMeter value={row.completedPhases} max={row.totalPhases} label={t.progress(row.completedPhases, row.totalPhases)} /> : "";
      },
    },
    {
      key: "expected", label: t.expectedColumn, sortable: true, optional: true,
      render: (stage) => {
        const row = rows.get(stage.id);
        if (!row) return "";
        return (
          <span className="row" style={{ gap: "var(--space-2)" }}>
            {row.expectedFrom && row.expectedTo
              ? t.expectedRange(formatDay(row.expectedFrom), formatDay(row.expectedTo))
              : <span className="text-muted">{t.noDates}</span>}
            {row.overdue && <Badge tone="danger">{t.overdue}</Badge>}
            {onSchedule && (
              <button className="btn" aria-label={scheduleLabel(stage)} title={scheduleLabel(stage)} onClick={() => onSchedule(stage)}><CalendarRange /></button>
            )}
          </span>
        );
      },
    },
  ];

  const chosen = useOptionalColumns("stage_plan", columns);

  if (view === "timeline") {
    return (
      <DeliveryTimeline
        items={stages.flatMap((stage) => {
          const row = rows.get(stage.id);
          return row ? [{ row, title: stage.name }] : [];
        })}
        actions={onSchedule ? (item) => {
          const stage = stages.find((s) => s.id === item.row.key);
          return stage ? <button className="btn" aria-label={scheduleLabel(stage)} title={scheduleLabel(stage)} onClick={() => onSchedule(stage)}><CalendarRange /></button> : null;
        } : undefined}
      />
    );
  }

  return (
    <>
      {chosen.chooser && <div className="row" style={{ justifyContent: "flex-end" }}>{chosen.chooser}</div>}
      <DirectoryTable
        ariaLabel={t.stagesTable} columns={chosen.columns} rows={table.rows} rowKey={(stage) => stage.id}
        sort={table.sort} onSort={table.onSort}
        emptyState={<div className="text-muted">{strings.stagePhases.noStages}</div>}
      />
      {phaseMove.dialog}
    </>
  );
}
