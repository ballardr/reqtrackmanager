/**
 * Module: modules/architecture/stateFields
 *
 * Pure helpers of the state fields: the default name of a state added straight to a diagram (unique within it, because the
 * server refuses a repeated name), the blank values, the values of an existing state and the fields an edit changed (the
 * update sends only those).
 */
import { STATE_KIND_LABEL, type ArchitectureState, type StateFieldValues, type StateKind } from "./types";

/** @param kind The kind to preselect. @returns A blank state form; a marker is named for its kind. */
export function blankStateValues(kind: StateKind = "state"): StateFieldValues {
  return {
    name: kind === "state" ? "" : STATE_KIND_LABEL[kind], description: "", kind, entry_action: "", exit_action: "", activity: "", label: "",
  };
}

/** @param state A state. @returns Its editable fields. */
export function valuesFromState(state: ArchitectureState): StateFieldValues {
  return {
    name: state.name, description: state.description, kind: state.kind, entry_action: state.entry_action,
    exit_action: state.exit_action, activity: state.activity, label: state.label,
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

/**
 * The name a state added straight to a diagram starts with, never one another state of the diagram already has (the server
 * compares without regard to case). An ordinary state is "State 1", "State 2" and so on, taking the lowest number not in use;
 * a marker is named for its kind ("Initial state"), with " 2", " 3" and so on when that is taken.
 *
 * @param kind The kind being added.
 * @param taken The names the diagram's states already have.
 * @returns A name not in `taken`.
 */
export function defaultStateName(kind: StateKind, taken: readonly string[]): string {
  const used = new Set(taken.map((name) => name.trim().toLowerCase()));
  const base = STATE_KIND_LABEL[kind];
  const candidate = (n: number) => (kind === "state" ? `${base} ${n}` : n === 1 ? base : `${base} ${n}`);
  let n = 1;
  while (used.has(candidate(n).toLowerCase())) n += 1;
  return candidate(n);
}
