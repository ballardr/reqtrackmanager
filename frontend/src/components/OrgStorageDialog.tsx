/**
 * Module: components/OrgStorageDialog
 *
 * The dialog in which a server administrator or Platform subscription manager sets an organisation's file upload
 * switch and storage limit, and sees its usage.
 *
 * Responsibilities:
 * - Read `GET /orgs/{id}/storage` and show the switch, the limit, the usage meter and the number of files.
 * - Save through `PUT /orgs/{id}/storage` from the form header (Cancel and Save), and say so with a toast.
 * - Show the same figures read-only when the server says the caller cannot change them (`can_edit`).
 *
 * Design decisions: an empty limit means "follow the server default" and the placeholder says what that is; the limit
 * is entered in MB or GB and stored in bytes (`utils/storageLimit`); usage uses the shared `ProgressMeter`.
 * External dependencies: `api`, `Modal`, `FormActions`, `ToggleField`, `StorageLimitField`, `ProgressMeter`.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { OrgStorage } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { formatFileSize } from "../utils/formatFileSize";
import { joinStorageLimit, splitStorageLimit, type StorageUnit } from "../utils/storageLimit";

import { FormActions } from "./FormActions";
import { ToggleField } from "./FormFields";
import { Modal } from "./Modal";
import { ProgressMeter } from "./ProgressMeter";
import { Spinner } from "./Spinner";
import { StorageLimitField } from "./StorageLimitField";

/**
 * @param orgId The organisation.
 * @param orgName The organisation's name, for the title.
 * @param onClose Closes the dialog.
 * @param onSaved Called after a successful save, so the caller can refresh anything that shows the rules.
 */
export function OrgStorageDialog({
  orgId, orgName, onClose, onSaved,
}: { orgId: string; orgName: string; onClose: () => void; onSaved?: () => void }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [storage, setStorage] = useState<OrgStorage | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<StorageUnit>("GB");
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  useLoadOnChange(async () => {
    try {
      const loaded = await api.get<OrgStorage>(`/api/v1/orgs/${orgId}/storage`);
      const parts = splitStorageLimit(loaded.storage_quota_bytes);
      setStorage(loaded);
      setEnabled(loaded.file_uploads_enabled);
      setAmount(parts.amount);
      setUnit(parts.unit);
    } catch {
      setLoadFailed(true);
    }
  }, [orgId]);

  async function save() {
    const limit = joinStorageLimit(amount, unit);
    if (limit === undefined) {
      setError(strings.orgStorage.invalidLimit);
      return;
    }
    setError(null);
    try {
      await api.put<OrgStorage>(`/api/v1/orgs/${orgId}/storage`, { file_uploads_enabled: enabled, storage_quota_bytes: limit });
      showToast(strings.orgStorage.saved);
      onSaved?.();
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }

  const body = (() => {
    if (loadFailed) return <p role="alert">{strings.orgStorage.loadError}</p>;
    if (!storage) return <Spinner />;
    const canEdit = storage.can_edit;
    const placeholder = storage.default_storage_quota_bytes === null
      ? strings.orgStorage.placeholderNone
      : strings.orgStorage.placeholderDefault(formatFileSize(storage.default_storage_quota_bytes));
    const limit = storage.effective_quota_bytes;
    return (
      <div className="stack">
        {!storage.deployment_uploads_enabled && <p role="status">{strings.orgStorage.deploymentOff}</p>}
        <ToggleField
          label={strings.orgStorage.uploadsEnabled} checked={enabled} onChange={setEnabled} disabled={!canEdit}
          help={strings.help.orgUploadsEnabled}
        />
        <StorageLimitField
          label={strings.orgStorage.limit} amount={amount} unit={unit} onAmountChange={setAmount} onUnitChange={setUnit}
          placeholder={placeholder} disabled={!canEdit} help={strings.help.orgStorageLimit}
        />
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{strings.orgStorage.used}</span>
          {limit === null
            ? <span>{strings.orgStorage.usedNoLimit(formatFileSize(storage.used_bytes))}</span>
            : <ProgressMeter
                value={storage.used_bytes} max={limit}
                label={strings.orgStorage.usedOfLimit(formatFileSize(storage.used_bytes), formatFileSize(limit), limit > 0 ? Math.round((storage.used_bytes / limit) * 100) : 100)}
              />}
        </div>
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <span>{strings.orgStorage.files}</span>
          <span>{storage.file_count.toLocaleString()}</span>
        </div>
        {!canEdit && <p className="text-muted">{strings.orgStorage.readOnly}</p>}
      </div>
    );
  })();

  return (
    <Modal title={strings.orgStorage.title(orgName)} onClose={onClose}>
      <FormActions error={error} onCancel={onClose} onSave={storage?.can_edit ? save : undefined} />
      {body}
    </Modal>
  );
}
