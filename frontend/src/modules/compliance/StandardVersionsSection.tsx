/**
 * Module: modules/compliance/StandardVersionsSection
 *
 * The "Versions" section of a standard's workspace — extracted out of `StandardsPanel.tsx`'s old
 * `SidePanel` content (the version list + "New version" dialog) plus its
 * full-width drill-in to `VersionWorkspace` when one is opened. Used as the
 * content of `StandardWorkspacePage.tsx`'s "Versions" nav-rail section.
 *
 * Owns its own `versions` state and reloads the version list after a
 * create/publish/retire, exactly as `StandardsPanel.tsx` did — this is a
 * pure extraction, not a behavioural change, so the version-management flow
 * (create, optionally cloned from an existing version; publish/retire) is
 * unchanged.
 *
 * "Which version is open" lives in the
 * URL (`/standards/:id/versions/:versionId`, `StandardWorkspacePage.tsx`'s
 * trailing route param, passed down here as `initialVersionId`) — the
 * same "a real route, not client-only state" convention this module's own
 * section switching already established — so `StandardNavSection.tsx`'s
 * expandable Versions group can deep-link straight to one version, and
 * opening/leaving a version here updates the address bar to match rather
 * than leaving it on the plain `/versions` URL the whole time.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { VersionWorkspace } from "./VersionWorkspace";
import {
  COMPLIANCE_STANDARD_VERSION_STATUS_LABEL,
  type ComplianceActionType,
  type ComplianceStandard,
  type ComplianceStandardVersion,
} from "./types";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { LabeledSelect } from "../../components/LabeledSelect";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { COMPLIANCE_HELP } from "./help";

export function StandardVersionsSection({
  orgId,
  standard,
  actionTypes,
  initialVersionId,
}: {
  orgId: string;
  standard: ComplianceStandard;
  actionTypes: ComplianceActionType[];
  /** The `:versionId` route param, if the URL names one directly (e.g. a
   * `StandardNavSection.tsx` expandable-versions link, or the Overview's
   * "Requirements" tile) — `null` for the plain `/versions` list URL. */
  initialVersionId: string | null;
}) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [creatingVersion, setCreatingVersion] = useState(false);

  async function reloadVersions() {
    try {
      setVersions(await complianceApi.listStandardVersions(orgId, standard.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load versions."), "error");
    }
  }

  useResetOnChange([orgId, standard.id], () => {
    setVersions(null);
  });
  useLoadOnChange(reloadVersions, [orgId, standard.id]);

  const activeVersion = initialVersionId ? versions?.find((v) => v.id === initialVersionId) ?? null : null;

  function openVersion(versionId: string) {
    navigate(`/standards/${standard.id}/versions/${versionId}`);
  }

  if (initialVersionId && activeVersion) {
    return (
      <VersionWorkspace
        orgId={orgId}
        standard={standard}
        version={activeVersion}
        versions={versions ?? []}
        actionTypes={actionTypes}
        onBack={() => navigate(`/standards/${standard.id}/versions`)}
        onVersionChanged={(updated) => {
          setVersions((prev) => (prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev));
        }}
      />
    );
  }

  return (
    <div className="stack">
      {versions === null ? (
        <p>Loading…</p>
      ) : versions.length === 0 ? (
        <p className="text-muted">No versions yet.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {versions.map((v) => (
            <li
              key={v.id}
              className="row"
              style={{ justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--color-border)" }}
            >
              <button className="btn" onClick={() => openVersion(v.id)}>
                {v.version_label}
              </button>
              <span className="text-muted">{COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[v.status]}</span>
            </li>
          ))}
        </ul>
      )}
      <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setCreatingVersion(true)}>
        New version
      </button>

      {creatingVersion && (
        <VersionFormModal
          versions={versions ?? []}
          onCancel={() => setCreatingVersion(false)}
          onSave={async (values) => {
            try {
              await complianceApi.createStandardVersion(orgId, standard.id, values);
              showToast("Version created.");
              setCreatingVersion(false);
              await reloadVersions();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not create version."), "error");
            }
          }}
        />
      )}
    </div>
  );
}

function VersionFormModal({
  versions,
  onCancel,
  onSave,
}: {
  versions: ComplianceStandardVersion[];
  onCancel: () => void;
  onSave: (values: { version_label: string; effective_date: string | null; change_note: string; clone_from_version_id: string | null }) => void;
}) {
  const [versionLabel, setVersionLabel] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [cloneFrom, setCloneFrom] = useState("");

  return (
    <Modal title="New version" onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField helpNotNeeded required
            label="Version label"
            value={versionLabel}
            onChange={setVersionLabel}
            placeholder="e.g. v2.0"
            inputProps={{ autoFocus: true }}
          />
          <DateField help={COMPLIANCE_HELP.complianceEffectiveDate} label="Effective date" value={effectiveDate} onChange={setEffectiveDate} />
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Change note" value={changeNote} onChange={setChangeNote} rows={2} />
          </FormGridFull>
          {versions.length > 0 && (
            <LabeledSelect help={COMPLIANCE_HELP.complianceCloneFrom}
              label="Clone requirements from"
              value={cloneFrom}
              onChange={setCloneFrom}
              options={versions.map((v) => ({ value: v.id, label: v.version_label }))}
              placeholder="Start empty"
            />
          )}
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() =>
            onSave({
              version_label: versionLabel,
              effective_date: effectiveDate || null,
              change_note: changeNote,
              clone_from_version_id: cloneFrom || null,
            })}
        saveDisabled={!versionLabel.trim()}
        />
      </div>
    </Modal>
  );
}
