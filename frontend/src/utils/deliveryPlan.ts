/**
 * Module: utils/deliveryPlan
 *
 * Turns the three reads the delivery plan page already has (stages, component tracks, phase schedule) into one row per
 * stage or per component track: where it is, how far along, when it is expected to finish and whether it is overdue.
 *
 * Responsibilities:
 * - Progress: the phases of the workflow the holder follows that it has completed (a closed phase counts the whole
 *   workflow), so a track in "Review" of five phases reads 20 %.
 * - Expected range: the earliest expected start and latest expected end over the holder's own plan rows for phases of its
 *   workflow. Nothing is inferred: a holder with no dates has `null` for both and shows no bar.
 * - Overdue: the same rule as the overview figure (`phase_attention_counts` on the server): the current phase is not
 *   closed and its own expected end is before the viewer's day.
 * - Timeline bounds and day arithmetic shared by the chart and the table.
 *
 * Time shapes: expected dates are calendar dates (`YYYY-MM-DD`, the planner's own day) compared with the viewer's day
 * (`localToday()`); actual start and completion are past instants in UTC, shown as the viewer's local day. Day numbers
 * here are whole days since the Unix epoch computed from the calendar fields, so no timezone shift can enter a date.
 *
 * Design decisions: computed in the browser from the existing bulk reads, so there is no second server definition of
 * "overdue" or "progress" to drift from the stage and track endpoints (Decided by: User).
 */
import type { ComponentTrack, PhasePlan, ProjectStage, StageWorkflow, StagePhaseKind } from "../api/types";
import { localToday } from "./localDate";

/** One row of the plan: a stage on its own, or one component's track through a stage. */
export interface DeliveryRow {
  /** Stable key: `stageId` for a stage row, `componentId:stageId` for a track. */
  key: string;
  /** Null for a stage row. */
  componentId: string | null;
  stageId: string;
  workflowId: string;
  phaseId: string;
  phaseName: string;
  phaseKind: StagePhaseKind;
  notApplicable: boolean;
  /** Phases of the workflow completed so far, and the number of phases in it. */
  completedPhases: number;
  totalPhases: number;
  /** `completedPhases / totalPhases`, 0 to 1. */
  progress: number;
  expectedFrom: string | null;
  expectedTo: string | null;
  /** The earliest recorded start of any phase, as the viewer's local day, or null. */
  actualFrom: string | null;
  /** When the holder reached a closed phase, as the viewer's local day, or null. */
  actualTo: string | null;
  overdue: boolean;
  /** Whether the holder is in a closed phase. */
  completed: boolean;
  /** Whether the caller may move the holder (tracks: the server's `can_move`; stages: a manager). */
  canMove: boolean;
}

/** What a stage or a track has in common for planning. */
interface Holder {
  componentId: string | null;
  stageId: string;
  workflowId: string;
  phaseId: string;
  phaseName: string;
  phaseKind: StagePhaseKind;
  notApplicable: boolean;
  completedAt: string | null;
  canMove: boolean;
}

/** Whole days since the Unix epoch for a `YYYY-MM-DD` calendar date. */
export function dayNumber(day: string): number {
  const [year, month, date] = day.split("-").map(Number);
  return Math.round(Date.UTC(year, month - 1, date) / 86_400_000);
}

/** The inverse of `dayNumber`: a `YYYY-MM-DD` calendar date. */
export function dayString(number: number): string {
  return new Date(number * 86_400_000).toISOString().slice(0, 10);
}

/** `YYYY-MM-DD` shown in the viewer's locale without any timezone shift (a calendar date has none). */
export function formatDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString();
}

function buildRow(holder: Holder, workflows: StageWorkflow[], plans: PhasePlan[], today: string): DeliveryRow {
  const phases = workflows.find((w) => w.id === holder.workflowId)?.phases ?? [];
  const phaseIds = new Set(phases.map((p) => p.id));
  const own = plans.filter((p) =>
    p.stage_id === holder.stageId && p.component_id === holder.componentId && phaseIds.has(p.phase_id));
  const starts = own.flatMap((p) => (p.expected_from ?? p.expected_to) ? [(p.expected_from ?? p.expected_to) as string] : []).sort();
  const ends = own.flatMap((p) => (p.expected_to ?? p.expected_from) ? [(p.expected_to ?? p.expected_from) as string] : []).sort();
  const started = own.flatMap((p) => (p.started_at ? [localToday(new Date(p.started_at))] : [])).sort();
  const completed = holder.phaseKind === "closed";
  const index = [...phases].sort((a, b) => a.sort_order - b.sort_order).findIndex((p) => p.id === holder.phaseId);
  const completedPhases = completed ? phases.length : Math.max(index, 0);
  const current = own.find((p) => p.phase_id === holder.phaseId);
  return {
    key: holder.componentId ? `${holder.componentId}:${holder.stageId}` : holder.stageId,
    componentId: holder.componentId, stageId: holder.stageId, workflowId: holder.workflowId, phaseId: holder.phaseId,
    phaseName: holder.phaseName, phaseKind: holder.phaseKind, notApplicable: holder.notApplicable,
    completedPhases, totalPhases: phases.length, progress: phases.length ? completedPhases / phases.length : 0,
    expectedFrom: starts[0] ?? null, expectedTo: ends[ends.length - 1] ?? null,
    actualFrom: started[0] ?? null,
    actualTo: completed && holder.completedAt ? localToday(new Date(holder.completedAt)) : null,
    overdue: !holder.notApplicable && !completed && !!current?.expected_to && current.expected_to < today,
    completed, canMove: holder.canMove,
  };
}

/**
 * One row per stage, from the stage's own phase and schedule.
 *
 * @param stages The project's stages.
 * @param workflows Every workflow a stage or track may follow.
 * @param plans The project's phase plan rows.
 * @param canMove Whether the caller may move a stage (a project manager).
 * @param today The viewer's calendar day (`localToday()`).
 */
export function stageRows(
  stages: ProjectStage[], workflows: StageWorkflow[], plans: PhasePlan[], canMove: boolean, today: string = localToday(),
): DeliveryRow[] {
  return stages.map((stage) => buildRow({
    componentId: null, stageId: stage.id, workflowId: stage.workflow_id, phaseId: stage.phase_id, phaseName: stage.phase_name,
    phaseKind: stage.phase_kind, notApplicable: false, completedAt: stage.completed_at, canMove,
  }, workflows, plans, today));
}

/**
 * One row per component track, from the track's own phase and schedule.
 *
 * @param tracks The component tracks (`component-stages`).
 * @param workflows Every workflow a track may follow.
 * @param plans The project's phase plan rows.
 * @param today The viewer's calendar day (`localToday()`).
 */
export function trackRows(
  tracks: ComponentTrack[], workflows: StageWorkflow[], plans: PhasePlan[], today: string = localToday(),
): DeliveryRow[] {
  return tracks.map((track) => buildRow({
    componentId: track.component_id, stageId: track.stage_id, workflowId: track.workflow_id, phaseId: track.phase_id,
    phaseName: track.phase_name, phaseKind: track.phase_kind, notApplicable: track.not_applicable,
    completedAt: track.completed_at, canMove: track.can_move,
  }, workflows, plans, today));
}

/**
 * The span the timeline covers: every expected and actual date of the rows and today, padded by a few days so no bar
 * touches the edge.
 *
 * @returns First and last day numbers, or null when no row has a date (the chart then has nothing to draw).
 */
export function timelineBounds(rows: DeliveryRow[], today: string): { from: number; to: number } | null {
  const days = rows.flatMap((r) => [r.expectedFrom, r.expectedTo, r.actualFrom, r.actualTo])
    .filter((d): d is string => d !== null).map(dayNumber);
  if (days.length === 0) return null;
  days.push(dayNumber(today));
  const from = Math.min(...days);
  const to = Math.max(...days);
  const pad = Math.max(3, Math.round((to - from) * 0.03));
  return { from: from - pad, to: to + pad };
}
