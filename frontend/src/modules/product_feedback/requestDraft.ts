/**
 * Module: modules/product_feedback/requestDraft
 *
 * The values the request form edits (`RequestFields`), kept apart from the component so that file exports only a
 * component.
 */
import type { PrincipalRef } from "../../api/types";
import type { ReferenceDraft } from "./referenceDraft";
import type { LevelDraft } from "./requestLevels";

/** The values the form edits. */
export interface RequestDraft {
  title: string;
  description: string;
  owner: PrincipalRef | null;
  /** The references to add as the request is created (a create form only; an edit changes them on the page). */
  references: ReferenceDraft[];
  levels: LevelDraft;
}

export const BLANK_REQUEST_DRAFT: RequestDraft = {
  title: "", description: "", owner: null, references: [], levels: {},
};
