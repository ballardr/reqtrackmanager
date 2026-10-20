/**
 * Module: modules/stakeholders/StakeholderFromUserModal
 *
 * "Add from org user": picks an organisation member and
 * creates a Stakeholder for them with their name and email prefilled, linked to
 * their account (`user_id`). It removes the friction of retyping a colleague
 * who is also a stakeholder; most stakeholders have no account and use the
 * ordinary create form instead. Optional role and type can be set up front;
 * everything else is edited afterwards.
 */
import { useState } from "react";

import type { OrgUser } from "../../api/types";
import { userPrincipal } from "../../api/types";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";

export function StakeholderFromUserModal({
  scopeLabel,
  orgUsers,
  typeOptions,
  error,
  onCancel,
  onSave,
}: {
  /** e.g. "organisation" / "project", shown in the title. */
  scopeLabel: string;
  orgUsers: OrgUser[];
  typeOptions: { value: string; label: string }[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: { user_id: string; stakeholder_type_id: string | null; role: string; activate?: boolean }) => void;
}) {
  const [userId, setUserId] = useState<string | null>(null);
  const [typeId, setTypeId] = useState("");
  const [role, setRole] = useState("");

  return (
    <Modal title={`Add Stakeholder from organisation user (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <p className="text-muted" style={{ margin: 0 }}>
              Creates a Stakeholder with this person's name and email filled in, linked to their account.
            </p>
          </FormGridFull>
          <PrincipalFormField helpNotNeeded required
            label="Organisation user" kinds={["user"]} orgUsers={orgUsers} value={userPrincipal(userId)}
            onChange={(principal) => setUserId(principal?.id ?? null)} ariaLabel="Organisation user" placeholder="Search users…"
          />
          <LabeledSelect helpNotNeeded label="Type" value={typeId} onChange={setTypeId} options={typeOptions} placeholder="No type" />
          <TextField helpNotNeeded label="Role" value={role} onChange={setRole} />
        </FormGrid>
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() => userId && onSave({ user_id: userId, stakeholder_type_id: typeId || null, role })}
          onSaveAndActivate={() => userId && onSave({ user_id: userId, stakeholder_type_id: typeId || null, role, activate: true })}
          saveLabel="Add Stakeholder"
          saveDisabled={!userId}
        />
      </div>
    </Modal>
  );
}
