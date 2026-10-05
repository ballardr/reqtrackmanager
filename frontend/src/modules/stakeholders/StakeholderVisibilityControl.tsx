/**
 * Module: modules/stakeholders/StakeholderVisibilityControl
 *
 * The "Visibility in this project" field on an organisation Stakeholder's
 * detail page when it is opened from a project: states whether this project
 * has an override of its own (`OverridePill`, style guide "Pattern: platform
 * default vs. override") and offers "Hide from this project". Hiding is
 * reversible and non-destructive, so it is a tier-1 `ConfirmDialog` that says
 * what stays recorded. A hidden stakeholder never reaches this page (the
 * project API treats it as absent); it is shown again from the list's "Show
 * hidden" filter, so the only override seen here is an explicit "shown" that
 * beats a parent project's hide.
 *
 * Purely presentational: the parent owns the API calls and navigation.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { OverridePill } from "../../components/OverridePill";
import { RecordFieldGroup } from "./RecordDetailParts";
import type { Stakeholder } from "./types";

export function StakeholderVisibilityControl({
  stakeholder,
  onHide,
  onReset,
}: {
  stakeholder: Stakeholder;
  /** Hides the stakeholder from the project; called once the dialog is confirmed. */
  onHide: () => void;
  /** Removes the project's own "shown" override, reverting to what a parent project decides. */
  onReset: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const shownDespiteParent = stakeholder.hidden_override === false;

  return (
    <RecordFieldGroup label="Visibility in this project" gap="0.35rem">
      <div className="row" style={{ gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
        <span data-testid="project-visibility">
          {shownDespiteParent ? "Shown, although a parent project hides it" : "Visible"}
        </span>
        <OverridePill
          custom={shownDespiteParent}
          defaultLabel="Shared by the organisation"
          resetLabel="Use inherited value"
          onReset={onReset}
        />
        <button className="btn" onClick={() => setConfirming(true)}>
          Hide from this project
        </button>
      </div>
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>
        Hiding applies to this project and any child project without its own setting. Other projects are unaffected.
      </span>

      {confirming && (
        <ConfirmDialog
          title={`Hide ${stakeholder.name} from this project?`}
          message={
            "They will no longer appear in this project's Stakeholders or be offered when linking needs or " +
            "relationships. Nothing is deleted: existing links stay recorded and reappear if you show them " +
            "again from the list's \"Show hidden\" filter."
          }
          confirmLabel="Hide"
          onConfirm={() => { setConfirming(false); onHide(); }}
          onCancel={() => setConfirming(false)}
        />
      )}
    </RecordFieldGroup>
  );
}
