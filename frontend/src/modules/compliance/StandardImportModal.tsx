/**
 * Module: modules/compliance/StandardImportModal
 *
 * The "Import standard" dialog (docs/compliance-module-plan.md Phase 21) —
 * uploads a single standard's export document (`GET .../standards/{id}/
 * export`, `StandardWorkspacePage.tsx`'s "Export" action) into an
 * organisation, always as a brand-new, `DRAFT`-only standard (§4/§31 — see
 * `app.modules.compliance.export.import_standard_data`'s own docstring for
 * why). Reached from `StandardListPage.tsx`'s "New standard"
 * `SplitButtonTrigger` alternative, mirroring `StandardFormModal.tsx`'s
 * "org picker as the dialog's first field, hidden entirely when there's
 * only one candidate" shape exactly.
 *
 * Reference-collision handling: the backend 409s (with a human-readable
 * message) when the uploaded document's `reference` already exists in the
 * chosen organisation, without writing anything — this dialog then offers
 * "Skip" or "Import as a copy" and retries with that `resolution`, rather
 * than a separate preview step (the whole-org bundle's own `import/preview`
 * + `import/merge` two-step is overkill here: a single standard has only
 * ever one possible collision to resolve, its own reference).
 */
import { useState } from "react";

import { ApiError } from "../../api/client";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { StandardImportResult } from "./types";

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
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Organisation</span>
            <select
              className="input"
              value={selectedOrgId}
              onChange={(e) => setSelectedOrgId(e.target.value)}
              aria-label="Organisation"
              autoFocus
            >
              <option value="" disabled>Select an organisation…</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Standard export file</span>
          <input
            className="input"
            type="file"
            accept=".json,application/json"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setConflictMessage(null);
              setError(null);
            }}
            aria-label="Standard export file"
          />
        </label>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          The imported standard is always created as a new, draft standard — nothing is published automatically.
        </p>

        {conflictMessage && (
          <div className="card stack" style={{ gap: "0.5rem" }}>
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
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          {!conflictMessage && (
            <button className="btn btn-primary" disabled={!canImport} onClick={() => doImport()}>
              {importing ? "Importing…" : "Import"}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
