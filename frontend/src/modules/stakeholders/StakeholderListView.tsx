/**
 * Module: modules/stakeholders/StakeholderListView
 *
 * The Stakeholder list shared by the project page (`ProjectStakeholdersPage`)
 * and the organisation panel (`OrgStakeholdersPanel`): `RecordListView`
 * configured with Stakeholder's own columns (Role, Cadence, Influence,
 * Interest), its create form and the "Add from org user" action. Influence and
 * Interest show the org's level *names* (`scheme`); they are plain labels, the
 * grid position itself is only computed server-side.
 *
 * The project page's "Show hidden" filter and Visibility column are
 * `RecordListView`'s; the `includeHidden`/`onIncludeHiddenChange`/`onShowHidden`
 * props pass straight through.
 */
import { useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { toErrorMessage } from "../../context/ToastContext";
import { RecordListView } from "./RecordListView";
import { StakeholderFormModal } from "./StakeholderFormModal";
import { StakeholderFromUserModal } from "./StakeholderFromUserModal";
import type { CadenceHint, Stakeholder, StakeholderFieldValues } from "./types";
import { STAKEHOLDER_SCOPE_LABEL, STAKEHOLDER_STATUS_LABEL, STAKEHOLDER_STATUS_TONE, TARGET_CADENCE_LABEL } from "./types";
import { levelName } from "./useStakeholderScheme";

export function StakeholderListView({
  stakeholders,
  ariaLabel,
  sectionKey,
  scopeLabel,
  emptyText,
  showScope,
  typeOptions,
  scheme,
  orgUsers,
  loadHint,
  includeArchived,
  onIncludeArchivedChange,
  includeHidden = false,
  onIncludeHiddenChange,
  onShowHidden,
  onOpen,
  onCreate,
  onCreateFromUser,
}: {
  stakeholders: Stakeholder[];
  ariaLabel: string;
  sectionKey: string;
  /** "project" / "organisation", for the create modals' titles. */
  scopeLabel: string;
  emptyText: string;
  showScope: boolean;
  typeOptions: { value: string; label: string }[];
  scheme: ScoringScheme | null;
  orgUsers: OrgUser[];
  loadHint: (influenceLevelId: string, interestLevelId: string) => Promise<CadenceHint>;
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  includeHidden?: boolean;
  /** Offered on the project page only; omit where there is nothing to hide. */
  onIncludeHiddenChange?: (next: boolean) => void;
  /** Re-shows a hidden stakeholder in this project (the Visibility cell's "Show" action). */
  onShowHidden?: (stakeholder: Stakeholder) => void;
  onOpen: (stakeholder: Stakeholder) => void;
  /** Resolves on success; a rejection keeps the modal open and shows its message. */
  onCreate: (values: StakeholderFieldValues) => Promise<void>;
  /** Same contract, for the "Add from org user" modal. */
  onCreateFromUser: (values: { user_id: string; stakeholder_type_id: string | null; role: string }) => Promise<void>;
}) {
  const [fromUserOpen, setFromUserOpen] = useState(false);
  const [fromUserError, setFromUserError] = useState<string | null>(null);

  return (
    <>
      <RecordListView<Stakeholder, StakeholderFieldValues>
        records={stakeholders}
        ariaLabel={ariaLabel}
        sectionKey={sectionKey}
        noun="Stakeholder"
        scopeLabel={scopeLabel}
        emptyText={emptyText}
        showScope={showScope}
        statusLabel={STAKEHOLDER_STATUS_LABEL}
        statusTone={STAKEHOLDER_STATUS_TONE}
        scopeLabels={STAKEHOLDER_SCOPE_LABEL}
        typeName={(s) => s.stakeholder_type_name}
        searchText={(s) => `${s.name} ${s.role} ${s.organisation_group}`}
        columnsBeforeType={[{ key: "role", label: "Role", render: (s) => s.role || "—" }]}
        columnsAfterScope={[
          { key: "cadence", label: "Cadence", render: (s) => (s.target_cadence ? TARGET_CADENCE_LABEL[s.target_cadence] : "—") },
          { key: "influence", label: "Influence", render: (s) => levelName(scheme, "influence", s.influence_level_id) },
          { key: "interest", label: "Interest", render: (s) => levelName(scheme, "interest", s.interest_level_id) },
        ]}
        toolbar={
          <button className="btn" onClick={() => setFromUserOpen(true)}>
            Add from org user
          </button>
        }
        includeArchived={includeArchived}
        onIncludeArchivedChange={onIncludeArchivedChange}
        includeHidden={includeHidden}
        onIncludeHiddenChange={onIncludeHiddenChange}
        onShowHidden={onShowHidden}
        onOpen={onOpen}
        onCreate={onCreate}
        renderCreateModal={(props) => (
          <StakeholderFormModal {...props} typeOptions={typeOptions} scheme={scheme} loadHint={loadHint} />
        )}
      />
      {fromUserOpen && (
        <StakeholderFromUserModal
          scopeLabel={scopeLabel}
          orgUsers={orgUsers}
          typeOptions={typeOptions}
          error={fromUserError}
          onCancel={() => { setFromUserOpen(false); setFromUserError(null); }}
          onSave={async (values) => {
            setFromUserError(null);
            try {
              await onCreateFromUser(values);
              setFromUserOpen(false);
            } catch (err) {
              setFromUserError(toErrorMessage(err, "Could not create the Stakeholder."));
            }
          }}
        />
      )}
    </>
  );
}
