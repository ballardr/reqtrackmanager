/**
 * Module: components/requirementFieldValues
 *
 * The value shape and helpers behind `RequirementFields`, kept apart from the component so the
 * component file exports only a component (fast refresh).
 */
import type { PrincipalRef, RequirementLevel } from "../api/types";

/** The values `RequirementFields` edits; strings stay strings so the inputs are controlled. */
export interface RequirementFieldValues {
  name: string;
  reasoning: string;
  clarification: string;
  description: string;
  targetStageId: string;
  level: RequirementLevel;
  reviewDate: string;
  reviewLeadDays: string;
  owner: PrincipalRef | null;
  reviewer: PrincipalRef | null;
}

/** The empty value set a create dialog starts from. */
export const EMPTY_REQUIREMENT_FIELDS: RequirementFieldValues = {
  name: "", reasoning: "", clarification: "", description: "", targetStageId: "", level: "requirement",
  reviewDate: "", reviewLeadDays: "", owner: null, reviewer: null,
};

/**
 * Turns the form's review fields into the API shape shared by create and update.
 *
 * @param values The form values.
 * @returns `review_date`, `review_lead_days`, `owner` and `reviewer` as the API takes them.
 */
export function requirementPeopleAndReviewPayload(values: RequirementFieldValues) {
  return {
    review_date: values.reviewDate || null,
    review_lead_days: values.reviewLeadDays ? Number(values.reviewLeadDays) : null,
    owner: values.owner,
    reviewer: values.reviewer,
  };
}
