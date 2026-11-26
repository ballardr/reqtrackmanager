/**
 * Module: modules/traceability/ProfileApprovalTab
 *
 * The Approval tab of a governance profile: for each record type with an approval gate, the roles the profile adds as
 * approvers, with a dialog to change them.
 *
 * Responsibilities: load the profile's approval policy, show it as a sortable table by record type, save one type's roles
 * (an empty set removes the profile's policy for it) and show the response as the new state.
 *
 * Design decisions: every part of the organisation router needs the organisation governance permission, so the table is
 * always editable. The roles are another way to be granted the approval right the type already requires; they never
 * replace it, which the field's help says.
 *
 * Dependencies: `profileApi` (`./api`), `PolicyTable`, `ApprovalRolesModal`.
 */
import { useCallback, useState } from "react";

import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { profileApi } from "./api";
import { ApprovalRolesModal } from "./ApprovalRolesModal";
import { ApproverRoleChips } from "./ApproverRolesField";
import { PolicyTable } from "./PolicyTable";
import type { ApproverRole, ProfileApproval, ProfileApprovalType } from "./types";

/**
 * @param orgId The organisation that owns the profile.
 * @param profileId The profile whose approval policy is shown.
 */
export function ProfileApprovalTab({ orgId, profileId }: { orgId: string; profileId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<ProfileApproval | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<ProfileApprovalType | null>(null);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await profileApi.approval(orgId, profileId));
    } catch {
      setFailed(true);
    }
  }, [orgId, profileId]);
  useLoadOnChange(load, [orgId, profileId]);

  async function save(type: ProfileApprovalType, roles: ApproverRole[] | null) {
    setData(await profileApi.setApprovalRoles(orgId, profileId, type.artefact_type, roles ?? []));
    showToast(`Approvers of ${type.label} saved.`);
    setEditing(null);
  }

  if (failed && !data) return <LoadFailed message="The approval policy could not be loaded." onRetry={() => void load()} />;
  if (!data) return <Spinner />;

  return (
    <div className="stack">
      <PolicyTable
        ariaLabel="Approval policy by record type"
        rows={data.types}
        emptyText="No record type of this organisation has an approval gate."
        columns={[{
          key: "roles", label: "Additional approvers", sortValue: (row) => row.roles.map((r) => r.label).join(", "),
          render: (row) => <ApproverRoleChips roles={row.roles} />,
        }]}
        rowMenu={(row) => [{ label: "Edit approvers", onSelect: () => setEditing(row) }]}
        rowMenuLabel={(row) => `Actions for ${row.label} approvers`}
      />
      {editing && (
        <ApprovalRolesModal
          typeLabel={editing.label} options={data.role_options} initial={editing.roles}
          onSave={(roles) => save(editing, roles)} onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
