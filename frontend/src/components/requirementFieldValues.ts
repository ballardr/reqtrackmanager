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
  /** The chosen requirement type's id in the project's list; `""` for none. */
  typeId: string;
  reviewDate: string;
  reviewLeadDays: string;
  owner: PrincipalRef | null;
  reviewer: PrincipalRef | null;
}

/** The empty value set a create dialog starts from. */
export const EMPTY_REQUIREMENT_FIELDS: RequirementFieldValues = {
  name: "", reasoning: "", clarification: "", description: "", targetStageId: "", level: "requirement", typeId: "",
  reviewDate: "", reviewLeadDays: "", owner: null, reviewer: null,
};

/**
 * The choices of the requirement type select: the project's enabled types, plus the requirement's own type when it is
 * no longer on that list (disabled, hidden or from another project), so an edit shows and keeps it.
 *
 * @param types The project's effective requirement type list.
 * @param current The requirement's own type, when it has one.
 * @returns Options in the list's order.
 */
export function requirementTypeOptions(
  types: readonly { id: string; name: string; is_enabled: boolean }[],
  current?: { id: string | null; name: string | null },
): { value: string; label: string }[] {
  const options = types.filter((t) => t.is_enabled || t.id === current?.id).map((t) => ({ value: t.id, label: t.name }));
  if (current?.id && current.name && !options.some((o) => o.value === current.id)) {
    options.push({ value: current.id, label: current.name });
  }
  return options;
}

/**
 * The id to select for a requirement's type: its own id when that is on the list, else the entry with the same name
 * (a project whose list was copied for its own use holds new ids), else its own id.
 *
 * @param types The project's effective requirement type list.
 * @param current The requirement's `type_id` and `type_name`.
 * @returns The id for the form, `""` when the requirement is untyped.
 */
export function requirementTypeSelection(
  types: readonly { id: string; name: string }[],
  current: { type_id: string | null; type_name: string | null },
): string {
  if (!current.type_id) return "";
  return types.find((t) => t.id === current.type_id)?.id ?? types.find((t) => t.name === current.type_name)?.id ?? current.type_id;
}

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
