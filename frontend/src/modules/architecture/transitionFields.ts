/**
 * Module: modules/architecture/transitionFields
 *
 * Pure helpers of the transition form: the blank values with the ends given, the values of an existing transition and the
 * fields an edit changed (the update sends only those).
 */
import type { StateTransition, TransitionFieldValues } from "./types";

/** @returns A blank transition form with the ends given. */
export function blankTransitionValues(sourceId = "", targetId = ""): TransitionFieldValues {
  return { source_state_id: sourceId, target_state_id: targetId, event: "", guard: "", action: "", description: "" };
}

/** @param transition A transition. @returns Its editable fields. */
export function valuesFromTransition(transition: StateTransition): TransitionFieldValues {
  return {
    source_state_id: transition.source_state_id, target_state_id: transition.target_state_id, event: transition.event,
    guard: transition.guard, action: transition.action, description: transition.description,
  };
}

/** The fields whose value differs between `before` and `after`. */
export function diffTransitionFields(before: TransitionFieldValues, after: TransitionFieldValues): Partial<TransitionFieldValues> {
  const changed: Partial<TransitionFieldValues> = {};
  (Object.keys(after) as (keyof TransitionFieldValues)[]).forEach((key) => {
    if (before[key] !== after[key]) changed[key] = after[key];
  });
  return changed;
}
