/**
 * Module: components/AddToGroupControl
 *
 * Anchored quick-pick on a member's own row (`OrgAdminPage.tsx` Users table): "add this org member to one of the
 * organisation's groups". `onAdd` is the caller's `addGroupMember` handler
 * (`POST /orgs/{orgId}/groups/{groupId}/members`).
 *
 * A one-field pick of an existing group fits `Popover` (style guide "Pattern: create panels, popovers, and one door
 * for bulk": a Popover is for a quick action on something that exists, a `Modal` for creating an entity).
 * Renders nothing when the user is already in every group of the organisation.
 */
import { UserPlus } from "lucide-react";
import { useRef, useState } from "react";

import type { OrgGroup, OrgUser } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Popover } from "./Popover";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Tooltip } from "./Tooltip";

export function AddToGroupControl({
  user,
  groups,
  onAdd,
}: {
  user: OrgUser;
  /** Every group in the organisation (unpaginated) — same `allGroups`
   * source `ProjectAdminPage.tsx`'s own nesting controls already reuse
   * rather than refetching. */
  groups: OrgGroup[];
  /** The existing `addGroupMember(groupId, userId)` handler — this
   * component only supplies the picker UI around it. */
  onAdd: (groupId: string, userId: string) => void;
}) {
  const strings = useStrings();
  const [open, setOpen] = useState(false);
  const [groupId, setGroupId] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);

  const availableGroups = groups.filter((g) => !g.member_user_ids.includes(user.user_id));
  if (availableGroups.length === 0) return null;

  const label = strings.orgAdmin.addToGroupFor(user.display_name);

  return (
    <>
      <Tooltip label={label} disabled={open}>
        <button
          ref={triggerRef}
          type="button"
          className="btn"
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <UserPlus />
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} title={label} onClose={() => setOpen(false)}>
          <div className="stack">
            <LabeledSelect helpNotNeeded
              label={strings.orgAdmin.addToGroupSelectLabel}
              value={groupId}
              onChange={setGroupId}
              options={availableGroups.map((g) => ({ value: g.id, label: g.name }))}
              placeholder={strings.orgAdmin.addToGroupSelectPlaceholder}
              inputProps={{ autoFocus: true }}
            />
            <FormActions
              onCancel={() => setOpen(false)}
              onSave={() => {
                onAdd(groupId, user.user_id);
                setGroupId("");
                setOpen(false);
              }}
              saveLabel={strings.membersTable.add}
              saveDisabled={!groupId}
            />
          </div>
        </Popover>
      )}
    </>
  );
}
