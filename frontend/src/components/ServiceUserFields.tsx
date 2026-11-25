/**
 * Module: components/ServiceUserFields
 *
 * The fields of a service user, shared by the create and the edit form (`ServiceUserFormModal`) so a field added
 * later reaches both: name, description, the optional notification address and the responsible user or group.
 * The name is the only required field; a blank address means the service user receives no email.
 */
import type { ServiceUserDraft } from "../api/serviceUsers";
import type { Principal } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormGrid, FormGridFull } from "./FormGrid";
import { TextAreaField, TextField } from "./FormFields";
import { PrincipalFormField } from "./PrincipalFormField";

/**
 * @param draft The current values.
 * @param onChange Called with the patch to apply.
 * @param organizationId The organisation, which scopes the responsible user and group search.
 * @param responsibleDisplay The stored responsible party's resolved label, shown until a new one is chosen.
 */
export function ServiceUserFields({
  draft, onChange, organizationId, responsibleDisplay,
}: {
  draft: ServiceUserDraft;
  onChange: (patch: Partial<ServiceUserDraft>) => void;
  organizationId: string;
  responsibleDisplay?: Principal | null;
}) {
  const strings = useStrings();
  const text = strings.serviceUsers;
  return (
    <FormGrid minColumn="18rem">
      <TextField
        label={text.name} value={draft.name} onChange={(name) => onChange({ name })} required
        help={strings.help.serviceUserName} inputProps={{ maxLength: 255 }}
      />
      <TextField
        label={text.email} value={draft.email} onChange={(email) => onChange({ email })}
        help={strings.help.serviceUserEmail} inputProps={{ type: "email", maxLength: 255 }}
      />
      <FormGridFull>
        <TextAreaField
          label={text.description} value={draft.description} onChange={(description) => onChange({ description })}
          help={strings.help.serviceUserDescription} inputProps={{ maxLength: 1000 }}
          plainText="A short note, at most 1,000 characters, shown in the service user list and the access review."
        />
      </FormGridFull>
      <FormGridFull>
        <PrincipalFormField
          label={text.responsible} help={strings.help.serviceUserResponsible}
          orgUsers={[]} organizationId={organizationId} kinds={["user", "org_group"]}
          value={draft.responsible} display={draft.responsible && responsibleDisplay && responsibleDisplay.id === draft.responsible.id ? responsibleDisplay : undefined}
          onChange={(responsible) => onChange({ responsible })}
          ariaLabel={text.responsibleAria}
        />
      </FormGridFull>
    </FormGrid>
  );
}
