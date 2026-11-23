/**
 * Module: modules/compliance/VersionWorkspace
 *
 * The drill-down view for one `ComplianceStandardVersion`: status, publish and retire (§4's lifecycle), a "Compare versions"
 * entry into `VersionDiffModal` (§27) and the version's requirement tree (`RequirementTree.tsx`, §5/§6). It renders full width
 * in place of the Standards tab's list, not in a `SidePanel` (420px is too narrow for a tree editor), as `RequirementsPage`'s
 * detail view does for a content-heavy child.
 * - An always-editable "Version summary" field, distinct from `change_note` (what changed relative to the previous version),
 *   editable whatever the status, unlike the `isDraft`-gated rest. The backend enforces the stage-dependent roles
 *   (`standards_contributor` while `DRAFT`, `standards_manager` or override once published or retired); the component shows every
 *   action and surfaces a 403 as a toast.
 * - The `EntitySwitcher` chevron beside the version heading jumps to a sibling version; its list is the `versions` prop that
 *   `StandardNavSection` and `StandardVersionsSection` already load.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EntitySwitcher, type EntitySwitcherOption } from "../../components/EntitySwitcher";
import { ListActions } from "../../components/ListActions";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { RequirementTree } from "./RequirementTree";
import { VersionDiffModal } from "./VersionDiffModal";
import {
  COMPLIANCE_STANDARD_VERSION_STATUS_LABEL,
  type ComplianceActionType,
  type ComplianceStandard,
  type ComplianceStandardVersion,
} from "./types";
import { TextAreaField } from "../../components/FormFields";
import { useResetOnChange } from "../../hooks/useResetOnChange";

interface Props {
  orgId: string;
  standard: ComplianceStandard;
  version: ComplianceStandardVersion;
  versions: ComplianceStandardVersion[];
  actionTypes: ComplianceActionType[];
  onBack: () => void;
  onVersionChanged: (updated: ComplianceStandardVersion) => void;
}

export function VersionWorkspace({ orgId, standard, version, versions, actionTypes, onBack, onVersionChanged }: Props) {
  const { showToast } = useToast();
  const [confirming, setConfirming] = useState<"publish" | "retire" | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [summary, setSummary] = useState(version.summary);
  const [savingSummary, setSavingSummary] = useState(false);

  useResetOnChange([version.id, version.summary], () => setSummary(version.summary));

  async function handleSaveSummary() {
    setSavingSummary(true);
    try {
      const updated = await complianceApi.updateStandardVersion(orgId, standard.id, version.id, summary);
      showToast("Version summary updated.");
      onVersionChanged(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update version summary."), "error");
    } finally {
      setSavingSummary(false);
    }
  }

  async function handleConfirm() {
    if (!confirming) return;
    try {
      const updated =
        confirming === "publish"
          ? await complianceApi.publishStandardVersion(orgId, standard.id, version.id)
          : await complianceApi.retireStandardVersion(orgId, standard.id, version.id);
      showToast(confirming === "publish" ? "Version published." : "Version retired.");
      onVersionChanged(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update version status."), "error");
    } finally {
      setConfirming(null);
    }
  }

  const isDraft = version.status === "draft";

  async function loadVersionSwitcherOptions(): Promise<EntitySwitcherOption[]> {
    return versions.map((v) => ({
      id: v.id,
      label: v.version_label,
      href: `/standards/${standard.id}/versions/${v.id}`,
    }));
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: "0.1rem" }}>
          <button className="btn" onClick={onBack} style={{ alignSelf: "flex-start" }}>
            ← Back to {standard.name}
          </button>
          <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
            <h3 style={{ margin: 0 }}>
              {standard.reference} — {version.version_label}
            </h3>
            {/* `reloadKey`: `versions` can gain an entry after this mounts
                (e.g. one just created), which the switcher must pick up. */}
            <EntitySwitcher
              label="Switch version"
              currentId={version.id}
              loadOptions={loadVersionSwitcherOptions}
              reloadKey={versions.map((v) => v.id).join(",")}
            />
          </div>
          <span className="text-muted">{COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[version.status]}</span>
        </div>
        <div className="row">
          <ListActions
            organizationId={orgId} recordType="compliance_requirement" kindLabel="requirements"
            filters={new URLSearchParams({ standard: standard.id, version: version.id }).toString()}
          />
          <button className="btn" disabled={versions.length < 2} onClick={() => setShowDiff(true)}>
            Compare versions
          </button>
          {version.status === "draft" && (
            <button className="btn btn-primary" onClick={() => setConfirming("publish")}>
              Publish
            </button>
          )}
          {version.status !== "retired" && (
            <button className="btn btn-danger" onClick={() => setConfirming("retire")}>
              Retire
            </button>
          )}
        </div>
      </div>

      {!isDraft && (
        <p className="text-muted" style={{ margin: 0 }}>
          This version is {COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[version.status].toLowerCase()} — its requirements
          and required actions are immutable. Create a new version to make changes.
        </p>
      )}

      <div className="card stack" style={{ gap: "var(--space-2)" }}>
        <TextAreaField markdown helpNotNeeded
          label="Version summary"
          value={summary}
          onChange={setSummary}
          inputProps={{ placeholder: "This version's current standing — e.g. note that a retired version is deprecated." }}
        />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-primary" disabled={summary === version.summary || savingSummary} onClick={handleSaveSummary}>
            {savingSummary ? "Saving…" : "Save summary"}
          </button>
        </div>
      </div>

      <RequirementTree
        orgId={orgId}
        standardId={standard.id}
        versionId={version.id}
        isDraft={isDraft}
        isPublished={version.status === "published"}
        actionTypes={actionTypes}
      />

      {confirming && (
        <ConfirmDialog
          title={confirming === "publish" ? "Publish this version?" : "Retire this version?"}
          message={
            confirming === "publish"
              ? "Once published, this version's requirements become immutable — further changes require a new version."
              : "A retired version can no longer be assigned to new projects. Projects already assigned to it are unaffected."
          }
          confirmLabel={confirming === "publish" ? "Publish" : "Retire"}
          onConfirm={handleConfirm}
          onCancel={() => setConfirming(null)}
        />
      )}
      {showDiff && (
        <VersionDiffModal orgId={orgId} standardId={standard.id} fromVersionId={version.id} versions={versions} onClose={() => setShowDiff(false)} />
      )}
    </div>
  );
}
