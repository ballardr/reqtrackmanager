/**
 * Module: modules/architecture/stateMachineFieldValues
 *
 * Pure helpers of the state machine diagram form: the blank values, the values of an existing diagram and the fields an edit
 * changed (the update sends only those).
 */
import type { StateMachineFieldValues } from "./types";

/** @returns A blank state machine diagram form; `elementId` preselects the element. */
export function blankStateMachineValues(elementId = ""): StateMachineFieldValues {
  return { name: "", description: "", element_id: elementId };
}

/** @param diagram A state machine diagram. @returns Its editable fields. */
export function valuesFromStateMachine(diagram: { name: string; description: string; element_id: string }): StateMachineFieldValues {
  return { name: diagram.name, description: diagram.description, element_id: diagram.element_id };
}

/** The fields whose value differs between `before` and `after`. */
export function diffStateMachineFields(before: StateMachineFieldValues, after: StateMachineFieldValues): Partial<StateMachineFieldValues> {
  const changed: Partial<StateMachineFieldValues> = {};
  (Object.keys(after) as (keyof StateMachineFieldValues)[]).forEach((key) => {
    if (before[key] !== after[key]) changed[key] = after[key];
  });
  return changed;
}
