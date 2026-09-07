/**
 * Module: modules/compliance/VersionWorkspace
 *
 * The drill-down view for one `ComplianceStandardVersion` — status,
 * publish/retire actions (§4's lifecycle), a "Compare versions" entry point
 * into `VersionDiffModal` (§27), and the version's own requirement tree
 * (`RequirementTree.tsx`, §5/§6). Rendered full-width in place of the
 * Standards tab's list (not a `SidePanel`, whose 420px max-width is too
 * narrow for a usable tree editor — see this component's own "why not a
 * SidePanel" note in docs/compliance-module-plan.md's Phase 12 notes) —
 * a "drill into the content column, keep a Back control" shape, the same
 * one `RequirementsPage`'s own detail view already uses elsewhere in this
 * app for a similarly content-heavy child view.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
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

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: "0.1rem" }}>
          <button className="btn" onClick={onBack} style={{ alignSelf: "flex-start" }}>
            ← Back to {standard.name}
          </button>
          <h3 style={{ margin: 0 }}>
            {standard.reference} — {version.version_label}
          </h3>
          <span className="text-muted">{COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[version.status]}</span>
        </div>
        <div className="row">
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

      <RequirementTree orgId={orgId} standardId={standard.id} versionId={version.id} isDraft={isDraft} actionTypes={actionTypes} />

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
