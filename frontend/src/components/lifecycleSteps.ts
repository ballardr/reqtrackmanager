/**
 * Module: components/lifecycleSteps
 *
 * Pure helpers for `LifecycleTrack`: the state of each step from the record's current key.
 */
import type { LifecycleStep, LifecycleTrackProps } from "./LifecycleTrack";

export type StepState = "done" | "current" | "later";

/**
 * Works out each step's state from the current key.
 *
 * @param steps The main path.
 * @param current Key of the current step.
 * @param offPath The branch step, when there is one.
 * @returns The steps to draw (the branch step appended when it is current) with their states.
 */
export function trackSteps(
  steps: LifecycleStep[], current: string, offPath?: LifecycleTrackProps["offPath"],
): Array<{ step: LifecycleStep; state: StepState }> {
  const onBranch = !!offPath && offPath.key === current;
  const reached = onBranch
    ? steps.findIndex((s) => s.key === offPath.after)
    : steps.findIndex((s) => s.key === current);
  const main = steps.map((step, i) => ({
    step,
    state: (!onBranch && i === reached ? "current" : i < reached || (onBranch && i <= reached) ? "done" : "later") as StepState,
  }));
  return onBranch ? [...main, { step: offPath, state: "current" as StepState }] : main;
}

/**
 * Builds a record type's main path from its ordered status values and the type's label map, so a page declares its
 * lifecycle in one place and the formal labels stay those the status badges use.
 *
 * @param order The main path, in order (a subset of the type's statuses; branch states are `offPath`, not here).
 * @param labels The type's `*_STATUS_LABEL` map.
 * @param options `descriptions` (what each state means, shown as its tooltip) and `locked` (a reason per state in
 *   which the record cannot be edited directly, shown beside a padlock).
 * @returns The steps for `RecordHeader`'s `lifecycle.steps`.
 */
export function lifecycleSteps<K extends string>(
  order: readonly K[],
  labels: Record<K, string>,
  options: { descriptions?: Partial<Record<K, string>>; locked?: Partial<Record<K, string>> } = {},
): LifecycleStep[] {
  return order.map((key) => ({
    key,
    label: labels[key],
    description: options.descriptions?.[key],
    locked: options.locked?.[key] !== undefined,
    lockedReason: options.locked?.[key],
  }));
}
