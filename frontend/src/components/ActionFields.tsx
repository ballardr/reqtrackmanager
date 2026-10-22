/**
 * Module: components/ActionFields
 *
 * The fields of a requirement action (title, description, type, assignee, due date) in one `FormGrid`,
 * shared by the create forms (the Actions page, the "create and link" dialog on a requirement) and the
 * action's own edit card, so the three stay aligned. The caller owns the values and the footer.
 */
import type { OrgUser, PrincipalRef } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { DateField, TextAreaField, TextField } from "./FormFields";
import { FormGrid, FormGridFull } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";
import { PrincipalFormField } from "./PrincipalFormField";

export interface ActionFieldValues {
  title: string;
  description: string;
  actionTypeId: string;
  assignee: PrincipalRef | null;
  dueDate: string;
}

/**
 * @param values The current field values.
 * @param onChange Called with the next values when any field changes.
 * @param actionTypes The action types to offer.
 * @param orgUsers Organisation members offered by the assignee picker.
 * @param organizationId The organisation, for user search and organisation groups.
 * @param projectId The project, for project groups.
 * @param disabled Makes every field read-only (an archived action).
 * @param typePlaceholder Text of a leading empty type option; omit when a type is always chosen.
 * @param assigneeDisplay Name to show for the saved assignee when it is not in `orgUsers`.
 * @param archivedAssignee Rendered instead of the assignee picker when `disabled` (a read-only badge).
 */
export function ActionFields({
  values, onChange, actionTypes, orgUsers, organizationId, projectId, disabled, typePlaceholder, assigneeDisplay, archivedAssignee,
}: {
  values: ActionFieldValues;
  onChange: (next: ActionFieldValues) => void;
  actionTypes: { id: string; name: string }[];
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  disabled?: boolean;
  typePlaceholder?: string;
  assigneeDisplay?: React.ComponentProps<typeof PrincipalFormField>["display"];
  archivedAssignee?: React.ReactNode;
}) {
  const strings = useStrings();
  const set = <K extends keyof ActionFieldValues>(key: K, value: ActionFieldValues[K]) => onChange({ ...values, [key]: value });
  return (
    <FormGrid minColumn="14rem">
      <FormGridFull>
        <TextField helpNotNeeded required={!disabled} label={strings.actions.name} value={values.title} onChange={(next) => set("title", next)} disabled={disabled} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField helpNotNeeded
          label={strings.actions.description} value={values.description} onChange={(next) => set("description", next)}
          rows={3} disabled={disabled}
        />
      </FormGridFull>
      <LabeledSelect helpNotNeeded required={!disabled}
        label={strings.actions.actionType}
        value={values.actionTypeId}
        onChange={(next) => set("actionTypeId", next)}
        options={actionTypes.map((at) => ({ value: at.id, label: at.name }))}
        placeholder={typePlaceholder ?? null}
        disabled={disabled}
      />
      {disabled && archivedAssignee ? (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{strings.actions.assignee}</span>
          {archivedAssignee}
        </div>
      ) : (
        <PrincipalFormField helpNotNeeded
          label={strings.actions.assignee} orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
          value={values.assignee} display={assigneeDisplay} onChange={(next) => set("assignee", next)}
          ariaLabel={strings.actions.assignee} placeholder={strings.reviews.unassigned}
        />
      )}
      <DateField helpNotNeeded label={strings.actions.dueDate} value={values.dueDate} onChange={(next) => set("dueDate", next)} disabled={disabled} />
    </FormGrid>
  );
}
