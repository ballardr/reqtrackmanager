/**
 * Module: components/GroupInUseDialog
 *
 * The delete dialog for an organisation or project group that still owns records (an owner, assignee
 * or reviewer field names it). It is `DeleteInUseDialog` configured for groups: it lists what names
 * the group, then lets the admin hand everything to a user or another group (a searchable
 * `PrincipalPicker`, since a replacement can be any person) or, when no required field names the
 * group, clear the optional fields. The server enforces the same rules (`DELETE .../groups/{id}`).
 */
import type { OrgUser, PrincipalRef, PrincipalType, PrincipalUsage } from "../api/types";
import { t } from "../i18n/strings";
import { DeleteInUseDialog } from "./DeleteInUseDialog";
import { PrincipalPicker } from "./PrincipalPicker";

const strings = t();

/**
 * @param groupName The group being deleted (shown, and typed to confirm clearing).
 * @param usage What names it (`GET .../groups/{id}/usage`).
 * @param organizationId The group's organisation (user search and group listing).
 * @param projectId Set for a project group, so replacements can be that project's groups.
 * @param orgUsers Users to offer as replacements without a search round trip.
 * @param kinds The principal kinds a replacement may be (an org group's cannot be a project group).
 * @param onReplace Delete, moving everything to this principal.
 * @param onClear Delete, emptying the optional fields.
 */
export function GroupInUseDialog({
  groupName,
  groupId,
  usage,
  organizationId,
  projectId,
  orgUsers,
  kinds,
  onReplace,
  onClear,
  onClose,
}: {
  groupName: string;
  /** Excluded from the replacements. */
  groupId: string;
  usage: PrincipalUsage;
  organizationId: string;
  projectId?: string;
  orgUsers: OrgUser[];
  kinds: readonly PrincipalType[];
  onReplace: (replacement: PrincipalRef) => Promise<void>;
  onClear: () => Promise<void>;
  onClose: () => void;
}) {
  const listing = usage.items.map((i) => `${i.count} ${i.label}`).join(", ");
  return (
    <DeleteInUseDialog
      title={strings.admin.deleteInUseTitle(groupName)}
      summary={strings.admin.groupInUseSummary(groupName, listing)}
      candidates={[]}
      moveHeading={strings.admin.groupInUseMoveHeading}
      moveHint={strings.admin.groupInUseMoveHint}
      onMove={(replacement) => {
        const [type, id] = replacement.split(":");
        return onReplace({ type: type as PrincipalType, id });
      }}
      renderMovePicker={({ value, onChange, disabled }) => {
        const [type, id] = value.split(":");
        return (
          <fieldset disabled={disabled} style={{ border: 0, padding: 0, margin: 0 }}>
            <PrincipalPicker
              orgUsers={orgUsers}
              organizationId={organizationId}
              projectId={projectId}
              kinds={kinds}
              value={value ? { type: type as PrincipalType, id } : null}
              onChange={(principal) => {
                // The group being deleted is not a valid replacement; ignore picking it.
                if (principal && principal.id === groupId) return;
                onChange(principal ? `${principal.type}:${principal.id}` : "");
              }}
              ariaLabel={strings.admin.groupInUseReplacement}
              clearLabel={strings.admin.groupInUseClear}
            />
          </fieldset>
        );
      }}
      remove={{
        heading: strings.admin.groupInUseClearHeading,
        buttonLabel: strings.admin.groupInUseClearButton,
        description: strings.admin.groupInUseClearDescription,
        blockedReason: usage.mandatory_total > 0 ? strings.admin.groupInUseClearBlocked : undefined,
        confirmText: groupName,
        confirmMessage: strings.admin.groupInUseClearConfirm(groupName),
        confirmLabel: strings.admin.deleteGroup,
        onRemove: onClear,
      }}
      onClose={onClose}
    />
  );
}
