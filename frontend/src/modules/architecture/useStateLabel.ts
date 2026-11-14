/**
 * Module: modules/architecture/useStateLabel
 *
 * How the state machine editor names a state in text (a list option, a heading, a table cell, a pin's anchor): its code
 * through the one record-code display rule (`useRecordCode`, which adds the project code when the organisation or the person
 * asks for it), then its name. A canvas caption and a comment's anchor name use the same functions, so the code reads one way
 * everywhere on the page.
 */
import { useRecordCode, type RecordCodeFormatters } from "../../hooks/useRecordCode";
import type { ArchitectureState } from "./types";

/** The part of a state the labels need. */
export type LabelledState = Pick<ArchitectureState, "unique_code" | "name"> & { from_project_code?: string | null };

/** The two ways to name a state: `code` for the code alone, `label` for the code and the name. */
export interface StateLabels {
  code: (state: LabelledState) => string;
  label: (state: LabelledState) => string;
}

/** @param formatCode The record-code formatter. @returns The state labels built on it (also used where no hook can be called). */
export function stateLabelsWith(formatCode: RecordCodeFormatters["code"]): StateLabels {
  const code = (state: LabelledState) => formatCode(state.unique_code, state.from_project_code);
  return { code, label: (state) => `${code(state)} ${state.name}`.trim() };
}

/** @returns The state labels for the project the viewer is in and the viewer's preference. */
export function useStateLabel(): StateLabels {
  return stateLabelsWith(useRecordCode().code);
}
