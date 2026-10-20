/**
 * Module: pages/AddUserModal
 *
 * Server Management → Users → "Add user": a server administrator creates an account, either by emailing
 * an invite (the person sets their own password) or with a password the administrator types. Either way
 * the account may belong to no organisation.
 *
 * Responsibilities: collect the fields, call `POST /api/v1/system/users`, report the outcome through the
 * parent's `onCreated`. It never shows or stores the typed password beyond the form's own state.
 * Dependencies: `NewUserFields` (shared with Org Admin), `Modal`, `FormActions`.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { FormActions } from "../components/FormActions";
import { LabeledSelect } from "../components/LabeledSelect";
import { Modal } from "../components/Modal";
import { NewUserFields } from "../components/NewUserFields";
import { EMPTY_NEW_USER, type NewUserValues } from "../components/newUserValues";
import { useOrgLabel, useOrgLabelCapitalized } from "../context/BrandingContext";
import { toErrorMessage } from "../context/ToastContext";
import { t } from "../i18n/strings";

const strings = t();

export type AddUserMode = "invite" | "password";

/**
 * @param onClose Called when the dialog is cancelled or after a successful create.
 * @param onCreated Called once with the new person's email and how they were added.
 */
export function AddUserModal({
  onClose, onCreated,
}: {
  onClose: () => void;
  onCreated: (email: string, mode: AddUserMode) => void;
}) {
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [orgId, setOrgId] = useState("");
  const [mode, setMode] = useState<AddUserMode>("password");
  const [values, setValues] = useState<NewUserValues>(EMPTY_NEW_USER);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get<Organization[]>("/api/v1/orgs").then(
      (list) => { if (!cancelled) setOrgs(list); },
      (err) => { if (!cancelled) setError(toErrorMessage(err, strings.common.error)); },
    );
    return () => { cancelled = true; };
  }, []);

  const invite = mode === "invite";
  const hasOrg = orgId !== "";
  const valid = invite
    ? values.email !== ""
    : values.email !== "" && values.displayName !== "" && values.password !== "";

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/api/v1/system/users", {
        mode,
        email: values.email,
        organization_id: hasOrg ? orgId : null,
        ...(invite ? {} : { display_name: values.displayName, password: values.password, role: values.role }),
      });
      onCreated(values.email.toLowerCase(), mode);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={strings.system.addUser} onClose={onClose} size="lg">
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>{strings.system.addUserHint(orgLabel)}</p>
        <LabeledSelect helpNotNeeded
          label={strings.system.addUserModeLabel}
          value={mode}
          onChange={(next) => setMode(next as AddUserMode)}
          options={[
            { value: "password", label: strings.system.addUserModePassword },
            { value: "invite", label: strings.system.addUserModeInvite },
          ]}
          placeholder={null}
          hint={invite ? strings.system.addUserInviteHint : strings.system.addUserPasswordHint}
        />
        <LabeledSelect help={strings.help.addUserOrganization}
          label={orgLabelCap}
          value={orgId}
          onChange={setOrgId}
          options={orgs.map((o) => ({ value: o.id, label: o.name }))}
          placeholder={strings.system.addUserNoOrg(orgLabel)}
          hint={!hasOrg ? strings.system.addUserNoOrgHint(orgLabel) : undefined}
        />
        <NewUserFields
          values={values}
          onChange={(patch) => setValues((prev) => ({ ...prev, ...patch }))}
          show={{ displayName: !invite, password: !invite, role: !invite && hasOrg }}
        />
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={submit}
          saveLabel={invite ? strings.orgAdmin.sendInvite : strings.common.create}
          saveDisabled={!valid || saving}
        />
      </div>
    </Modal>
  );
}
