/**
 * Module: modules/compliance/StandardImportModal
 *
 * The "Import standard" dialog: uploads one standard's export document (`GET .../standards/{id}/export`, `StandardWorkspacePage.tsx`'s
 * "Export") into an organisation as a new `DRAFT`-only standard (§4/§31; see `app.modules.compliance.export.import_standard_data`).
 * It is an alternative of `StandardListPage.tsx`'s "New standard" `SplitButtonTrigger` and, like `StandardFormModal.tsx`, shows an
 * organisation picker first only with more than one candidate.
 * Reference collision: the backend returns 409 with a readable message, writing nothing, when the document's `reference` already
 * exists in the organisation; the dialog then offers "Skip" or "Import as a copy" and retries with that `resolution`. A single
 * standard has only one possible collision, so the whole-organisation bundle's two-step preview and merge is not used.
 */
import { useState } from "react";

import { ApiError } from "../../api/client";
import { FormActions } from "../../components/FormActions";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { StandardImportResult } from "./types";
import { LabeledSelect } from "../../components/LabeledSelect";
import { FileField } from "../../components/FormFields";
import { useOrgLabelCapitalized } from "../../context/BrandingContext";
import { useStrings } from "../../context/TerminologyContext";

interface StandardImportOrgOption {
  id: string;
  name: string;
}

export function StandardImportModal({
  orgId,
  orgs,
  onCancel,
  onImported,
}: {
  /** Fixed target organisation, when the caller already knows there's
   * exactly one candidate (no `orgs` picker is needed). */
  orgId?: string;
  /** Candidate organisations to import into, when the caller can manage
   * standards in more than one. The picker only renders when this has more
   * than one entry — mirrors `StandardFormModal.tsx`'s own org picker. */
  orgs?: StandardImportOrgOption[];
  onCancel: () => void;
  onImported: (result: StandardImportResult) => void;
}) {
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const [selectedOrgId, setSelectedOrgId] = useState(orgId ?? (orgs?.length === 1 ? orgs[0].id : ""));
  const [file, setFile] = useState<File | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolvedOrgId = orgId ?? selectedOrgId;
  const canImport = !!file && !!resolvedOrgId && !importing;

  async function doImport(resolution?: "skip" | "import_as_copy") {
    if (!file || !resolvedOrgId) return;
    setImporting(true);
    setError(null);
    try {
      const result = await complianceApi.importStandard(resolvedOrgId, file, resolution);
      onImported(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflictMessage(err.message);
      } else {
        setError(toErrorMessage(err, "Could not import standard."));
      }
    } finally {
      setImporting(false);
    }
  }

  return (
    <Modal title="Import standard" onClose={onCancel}>
      <div className="stack">
        {!orgId && orgs && orgs.length > 1 && (
          <LabeledSelect helpNotNeeded
            label={orgLabelCap}
            value={selectedOrgId}
            onChange={setSelectedOrgId}
            options={orgs.map((o) => ({ value: o.id, label: o.name }))}
            placeholder={strings.filters.select}
            inputProps={{ autoFocus: true }}
          />
        )}
        <FileField helpNotNeeded
          label="Standard export file"
          accept=".json,application/json"
          onChange={(next) => {
            setFile(next);
            setConflictMessage(null);
            setError(null);
          }}
        />
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          The imported standard is always created as a new, draft standard — nothing is published automatically.
        </p>

        {conflictMessage && (
          <div className="card stack" style={{ gap: "var(--space-3)" }}>
            <p style={{ margin: 0 }}>{conflictMessage}</p>
            <div className="row">
              <button className="btn" disabled={importing} onClick={() => doImport("skip")}>
                Skip import
              </button>
              <button className="btn btn-primary" disabled={importing} onClick={() => doImport("import_as_copy")}>
                Import as a copy
              </button>
            </div>
          </div>
        )}
        <FormActions
          error={error} onCancel={onCancel}
          onSave={conflictMessage ? undefined : () => doImport()} saveDisabled={!canImport}
          saveLabel={importing ? "Importing…" : "Import"}
        />
      </div>
    </Modal>
  );
}
