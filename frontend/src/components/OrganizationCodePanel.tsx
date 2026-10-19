/**
 * Module: components/OrganizationCodePanel
 *
 * Org Admin form for the organisation's own code, which goes in front of the codes of records the
 * organisation owns (`ACME-PER-001`). Changing it asks for confirmation first: a qualified code
 * already pasted into a document or ticket stops finding its record.
 *
 * Dependencies: `PUT /api/v1/orgs/{id}/code`.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { rememberOrganizationCode } from "../hooks/useOrganizationCode";
import { normaliseProjectCode } from "../utils/codePolicy";
import { ConfirmDialog } from "./ConfirmDialog";
import { TextField } from "./FormFields";

/** The most characters an organisation code may have (matches the server's `ABSOLUTE_MAX_CODE_LENGTH`). */
const MAX_LENGTH = 10;

/**
 * @param org The organisation whose code is edited.
 * @param onSaved Called with the saved organisation so the page can refresh its copy.
 */
export function OrganizationCodePanel({ org, onSaved }: { org: Organization; onSaved: (org: Organization) => void }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [code, setCode] = useState(org.code);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);

  const next = normaliseProjectCode(code);
  const valid = /^[A-Z0-9]+$/.test(next) && next.length <= MAX_LENGTH;
  const changed = next !== org.code;

  async function save() {
    setConfirming(false);
    setSaving(true);
    try {
      const saved = await api.put<Organization>(`/api/v1/orgs/${org.id}/code`, { code: next });
      rememberOrganizationCode(saved.id, saved.code);
      showToast(strings.orgAdmin.organizationCodeSaved);
      setCode(saved.code);
      onSaved(saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.organizationCodeHint}</p>
      <div className="row" style={{ gap: "1rem", alignItems: "flex-end" }}>
        <TextField
          label={strings.orgAdmin.organizationCodeLabel}
          value={code}
          onChange={setCode}
          inputProps={{ style: { width: "8rem" }, maxLength: MAX_LENGTH }}
        />
        <button type="button" className="btn btn-primary" onClick={() => setConfirming(true)} disabled={!valid || !changed || saving}>
          {strings.common.save}
        </button>
      </div>
      {confirming && (
        <ConfirmDialog
          title={strings.orgAdmin.organizationCodeConfirmTitle}
          message={strings.orgAdmin.organizationCodeConfirmBody(org.code, next)}
          confirmLabel={strings.orgAdmin.organizationCodeConfirm}
          onConfirm={save}
          onCancel={() => setConfirming(false)}
        />
      )}
    </div>
  );
}
