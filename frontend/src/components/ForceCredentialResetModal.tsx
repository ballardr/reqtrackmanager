/**
 * Module: components/ForceCredentialResetModal
 *
 * Server Management → Users → "Force a credential reset…": a server administrator ends the sessions of a
 * group of accounts, revokes their access tokens and requires a new password, after an incident or a restore
 * of data that may be exposed (`POST /system/credentials/force-reset`).
 *
 * Responsibilities: choose the scope (everyone, one organisation, the server administrators), whether to
 * clear two-factor enrolment and whether to email each person a new link; then a Tier 2 confirmation (type
 * the word) because the effect is immediate and wide, and a toast with the counts. The same operation
 * exists on the command line for when no administrator can sign in.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ForceResetResult, Organization } from "../api/types";
import { useOrgLabel, useOrgLabelCapitalized } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { ConfirmDialog } from "./ConfirmDialog";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

const strings = t();

type Scope = "all" | "organization" | "server_admins";

/**
 * @param onClose Called when the dialog is cancelled or the reset has run.
 * @param onDone Called after a successful reset, with what it did (so the caller can refresh its list).
 */
export function ForceCredentialResetModal({
  onClose, onDone,
}: {
  onClose: () => void;
  onDone?: (result: ForceResetResult) => void;
}) {
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const { showToast } = useToast();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [scope, setScope] = useState<Scope>("all");
  const [orgId, setOrgId] = useState("");
  const [reset2fa, setReset2fa] = useState(false);
  const [sendLinks, setSendLinks] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<Organization[]>("/api/v1/orgs").then(
      (list) => { if (!cancelled) setOrgs(list); },
      (err) => { if (!cancelled) setError(toErrorMessage(err, strings.common.error)); },
    );
    return () => { cancelled = true; };
  }, []);

  const valid = scope !== "organization" || orgId !== "";

  async function apply() {
    setConfirming(false);
    setError(null);
    try {
      const result = await api.post<ForceResetResult>("/api/v1/system/credentials/force-reset", {
        scope,
        organization_id: scope === "organization" ? orgId : null,
        reset_2fa: reset2fa,
        send_links: sendLinks,
      });
      showToast(
        sendLinks
          ? strings.passwordReset.forceResult(result.accounts, result.emailed)
          : `${strings.passwordReset.forceResult(result.accounts, 0)}. ${strings.passwordReset.forceNoEmail}`,
      );
      onDone?.(result);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }

  return (
    <>
      <Modal title={strings.passwordReset.forcePanelTitle} onClose={onClose}>
        <div className="stack">
          <p className="text-muted" style={{ margin: 0 }}>{strings.passwordReset.forcePanelHint}</p>
          <LabeledSelect help={strings.help.forceResetWho}
            label={strings.passwordReset.forceWho}
            value={scope}
            onChange={(v) => setScope(v as Scope)}
            placeholder={null}
            options={[
              { value: "all", label: strings.passwordReset.forceScopeAll },
              { value: "organization", label: strings.passwordReset.forceScopeOrg(orgLabel) },
              { value: "server_admins", label: strings.passwordReset.forceScopeAdmins },
            ]}
          />
          {scope === "organization" && (
            <LabeledSelect help={strings.help.forceResetOrganisation} required
              label={orgLabelCap}
              value={orgId}
              onChange={setOrgId}
              options={orgs.map((o) => ({ value: o.id, label: o.name }))}
            />
          )}
          <CheckboxField help={strings.help.forceResetTwoFactor}
            label={strings.passwordReset.forceTwoFactor} checked={reset2fa} onChange={setReset2fa}
          />
          <CheckboxField help={strings.help.forceResetSendLinks}
            label={strings.passwordReset.forceSendLinks} checked={sendLinks} onChange={setSendLinks}
          />
          <FormActions
            error={error}
            onCancel={onClose}
            onSave={() => setConfirming(true)}
            saveLabel={strings.passwordReset.forceSave}
            saveTone="danger"
            saveDisabled={!valid}
          />
        </div>
      </Modal>
      {confirming && (
        <ConfirmDialog
          title={strings.passwordReset.forceConfirmTitle}
          message={strings.passwordReset.forceConfirmMessage}
          confirmLabel={strings.passwordReset.forceConfirm}
          requireTypedText={strings.passwordReset.forceTypedText}
          onConfirm={apply}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  );
}
