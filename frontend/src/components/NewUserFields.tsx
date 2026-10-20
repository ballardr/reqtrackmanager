/**
 * Module: components/NewUserFields
 *
 * The email / name / password / role fields of an administrator creating a person's account, shared by
 * Org Admin's "New user" dialog and Server Management's "Add user" dialog so the two stay identical.
 * Purely presentational: the caller owns the values and the submit. `show` hides the fields a mode does
 * not use (an invitee chooses their own name and password; without an organisation there is no role).
 */
import { FormGrid } from "./FormGrid";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ORG_ROLE_LABEL, type OrgRole } from "../api/types";
import type { NewUserValues } from "./newUserValues";
import { t } from "../i18n/strings";

const strings = t();

/**
 * @param values Current field values.
 * @param onChange Called with the changed field(s).
 * @param show Which optional fields to render (all by default); the email is always shown.
 */
export function NewUserFields({
  values, onChange, show,
}: {
  values: NewUserValues;
  onChange: (patch: Partial<NewUserValues>) => void;
  show?: { displayName?: boolean; password?: boolean; role?: boolean };
}) {
  const showName = show?.displayName ?? true;
  const showPassword = show?.password ?? true;
  const showRole = show?.role ?? true;
  return (
    <FormGrid minColumn="18rem">
      <TextField helpNotNeeded
        label={strings.orgAdmin.email}
        value={values.email}
        onChange={(email) => onChange({ email })}
        inputProps={{ autoFocus: true, type: "email" }}
      />
      {showName && (
        <TextField helpNotNeeded label={strings.orgAdmin.name} value={values.displayName} onChange={(displayName) => onChange({ displayName })} />
      )}
      {showPassword && (
        <TextField helpNotNeeded
          label={strings.orgAdmin.password}
          value={values.password}
          onChange={(password) => onChange({ password })}
          hint={strings.orgAdmin.passwordRuleHint}
          inputProps={{ type: "password", autoComplete: "new-password" }}
        />
      )}
      {showRole && (
        <LabeledSelect helpNotNeeded
          label={strings.orgAdmin.role}
          value={values.role}
          onChange={(role) => onChange({ role: role as OrgRole })}
          options={(["member", "project_creator", "org_admin"] as OrgRole[]).map((r) => ({ value: r, label: ORG_ROLE_LABEL[r] }))}
          placeholder={null}
        />
      )}
    </FormGrid>
  );
}
