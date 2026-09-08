/**
 * Module: modules/compliance/StandardVersionsSection
 *
 * The "Versions" section of a standard's workspace (docs/compliance-module-
 * plan.md Phase 18) — extracted out of `StandardsPanel.tsx`'s old
 * `SidePanel` content (the version list + "New version" dialog) plus its
 * full-width drill-in to `VersionWorkspace` when one is opened. Used as the
 * content of `StandardWorkspacePage.tsx`'s "Versions" nav-rail section.
 *
 * Owns its own `versions` state and reloads the version list after a
 * create/publish/retire, exactly as `StandardsPanel.tsx` did — this is a
 * pure extraction, not a behavioural change, so the version-management flow
 * (create, optionally cloned from an existing version; publish/retire) is
 * unchanged from Phase 12/4's original design.
 *
 * Phase 23 moves "which version is open" from local component state to the
 * URL (`/standards/:id/versions/:versionId`, `StandardWorkspacePage.tsx`'s
 * new trailing route param, passed down here as `initialVersionId`) — the
 * same "a real route, not client-only state" convention this module's own
 * section switching already established — so `StandardNavSection.tsx`'s
 * new expandable Versions group can deep-link straight to one version, and
 * opening/leaving a version here updates the address bar to match rather
 * than leaving it on the plain `/versions` URL the whole time.
 */
import { useEffect, useState } from "react";
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

  useEffect(() => {
    setVersions(null);
    void reloadVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, standard.id]);

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
    <Modal title="New version" onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Version label</span>
          <input className="input" value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="e.g. v2.0" aria-label="Version label" autoFocus />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Effective date</span>
          <input className="input" type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Change note</span>
          <textarea className="input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)} rows={2} />
        </label>
        {versions.length > 0 && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Clone requirements from</span>
            <select className="input" value={cloneFrom} onChange={(e) => setCloneFrom(e.target.value)} aria-label="Clone requirements from">
              <option value="">Start empty</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>{v.version_label}</option>
              ))}
            </select>
          </label>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!versionLabel.trim()}
            onClick={() =>
              onSave({
                version_label: versionLabel,
                effective_date: effectiveDate || null,
                change_note: changeNote,
                clone_from_version_id: cloneFrom || null,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
