/**
 * Module: modules/traceability/ReviewSettingsFields
 *
 * The field group that edits one record type's review settings: the longest interval between reviews, how many days
 * before a review is due the reminder is sent, and who is reminded when a record has no reviewer. A profile's tab and a
 * project's section both edit through it, so a field added later reaches both.
 *
 * Responsibilities:
 * - Hold no state: the caller owns the values and receives each change.
 * - An empty number means the setting is unset (`null`).
 * - Offer a user or an organisation group as the default owner and, inside a project, a project group as well.
 *
 * Dependencies: `FormFields` (`TextField`), `PrincipalFormField`, `GOVERNANCE_HELP`.
 */
import type { OrgUser, Principal } from "../../api/types";
import { FormGrid } from "../../components/FormGrid";
import { TextField } from "../../components/FormFields";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { GOVERNANCE_HELP } from "./help";
import { numberOrNull, REVIEW_INTERVAL_MAX_DAYS, REVIEW_LEAD_MAX_DAYS } from "./policyText";
import type { ReviewSettingsValues } from "./types";

/**
 * @param values The settings being edited.
 * @param onChange Called with the new settings after any change.
 * @param orgUsers The organisation's users, so a picked user shows a name.
 * @param organizationId The organisation, for group listing and user search.
 * @param projectId The project, when a project group may be the default owner (a project's own policy only).
 * @param ownerDisplay The resolved default owner as the server returned it, shown until the person picks another.
 */
export function ReviewSettingsFields({
  values, onChange, orgUsers, organizationId, projectId, ownerDisplay,
}: {
  values: ReviewSettingsValues;
  onChange: (values: ReviewSettingsValues) => void;
  orgUsers: OrgUser[];
  organizationId: string | undefined;
  projectId?: string;
  ownerDisplay?: Principal | null;
}) {
  const display = ownerDisplay && values.default_owner && ownerDisplay.id === values.default_owner.id ? ownerDisplay : undefined;
  return (
    <FormGrid minColumn="14rem">
      <TextField
        label="Review interval (days)" help={GOVERNANCE_HELP.reviewInterval} value={values.interval_days?.toString() ?? ""}
        inputProps={{ type: "number", min: 1, max: REVIEW_INTERVAL_MAX_DAYS, step: 1 }}
        onChange={(text) => onChange({ ...values, interval_days: numberOrNull(text) })}
      />
      <TextField
        label="Reminder lead (days)" help={GOVERNANCE_HELP.reviewLead} value={values.lead_days?.toString() ?? ""}
        inputProps={{ type: "number", min: 0, max: REVIEW_LEAD_MAX_DAYS, step: 1 }}
        onChange={(text) => onChange({ ...values, lead_days: numberOrNull(text) })}
      />
      <PrincipalFormField
        label="Default owner" help={GOVERNANCE_HELP.reviewOwner} ariaLabel="Default owner" orgUsers={orgUsers}
        organizationId={organizationId} projectId={projectId} value={values.default_owner} display={display}
        kinds={projectId ? ["user", "org_group", "project_group"] : ["user", "org_group"]} emptyLabel="Not set"
        onChange={(owner) => onChange({ ...values, default_owner: owner })}
      />
    </FormGrid>
  );
}
