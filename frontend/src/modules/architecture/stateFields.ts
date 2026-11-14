/**
 * Module: modules/architecture/stateFields
 *
 * Pure helpers of the state form: the blank values (a marker is named for its kind), the values of an existing state and the
 * fields an edit changed (the update sends only those).
 */
import { STATE_KIND_LABEL, type ArchitectureState, type StateFieldValues, type StateKind } from "./types";

/** @param kind The kind to preselect. @returns A blank state form; a marker is named for its kind. */
export function blankStateValues(kind: StateKind = "state"): StateFieldValues {
  return {
    name: kind === "state" ? "" : STATE_KIND_LABEL[kind], description: "", kind, entry_action: "", exit_action: "", activity: "",
  };
}

/** @param state A state. @returns Its editable fields. */
export function valuesFromState(state: ArchitectureState): StateFieldValues {
  return {
    name: state.name, description: state.description, kind: state.kind, entry_action: state.entry_action,
    exit_action: state.exit_action, activity: state.activity,
  };
}

/** The fields whose value differs between `before` and `after`. */
export function diffStateFields(before: StateFieldValues, after: StateFieldValues): Partial<StateFieldValues> {
  const changed: Partial<StateFieldValues> = {};
  (Object.keys(after) as (keyof StateFieldValues)[]).forEach((key) => {
    if (before[key] !== after[key]) (changed as Record<string, unknown>)[key] = after[key];
  });
  return changed;
}
