/**
 * Module: components/StagePlanTable
 *
 * The project's stages on the delivery status page: each stage's current phase (movable in place by a project manager),
 * owner, progress, expected range and overdue state, as a table or, with `view="timeline"`, as bars on the shared axis.
 *
 * Responsibilities:
 * - One row per stage from `utils/deliveryPlan.stageRows`; the phase picker moves a stage through the shared
 *   `usePhaseMove` (a closed phase first asks about completing its requirements).
 * - A locked phase is shown unavailable, with the reason, to a person who cannot enter or leave it (the server enforces it).
 * - `onSchedule` adds a control to set the current phase's expected range, for a manager.
 *
 * Design decisions: the same columns and wording as the component track list (`ComponentTracksList`), so a stage and a
 * track read alike; the stage's workflow, owner and name are still edited in project administration.
 */
import { CalendarRange } from "lucide-react";

import type { PhasePlan, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { usePhaseMove } from "../hooks/usePhaseMove";
import { formatDay, stageRows, type DeliveryRow } from "../utils/deliveryPlan";
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

  const columns: DirectoryColumn<ProjectStage>[] = [
    { key: "stage", label: strings.componentPhases.stageColumn, render: (stage) => <strong>{stage.name}</strong> },
    {
      key: "phase", label: t.currentPhaseColumn,
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
            options={phases.map((p) => {
              // Entering or leaving a locked phase needs a project manager: show the choice as unavailable, with why.
              const locked = !stage.can_lock && p.id !== stage.phase_id && (p.kind === "locked" || stage.phase_kind === "locked");
              return { value: p.id, label: locked ? strings.stageWorkflows.lockedNeedsManager(p.name) : p.name, disabled: locked };
            })}
          />
        );
      },
    },
    { key: "owner", label: strings.componentPhases.owner, render: (stage) => <PrincipalBadge principal={stage.owner} placeholder="" /> },
    {
      key: "progress", label: t.progressColumn,
      render: (stage) => {
        const row = rows.get(stage.id);
        return row ? <ProgressMeter value={row.completedPhases} max={row.totalPhases} label={t.progress(row.completedPhases, row.totalPhases)} /> : "";
      },
    },
    {
      key: "expected", label: t.expectedColumn,
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

  return (
    <>
      <DirectoryTable
        ariaLabel={t.stagesTable} columns={columns} rows={stages} rowKey={(stage) => stage.id}
        emptyState={<div className="text-muted">{strings.stagePhases.noStages}</div>}
      />
      {phaseMove.dialog}
    </>
  );
}
