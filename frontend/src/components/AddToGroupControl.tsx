/**
 * Module: components/AddToGroupControl
 *
 * Small anchored quick-pick — "add this org member to one of this
 * organisation's groups" — from the member's own row (PR6 of the
 * members/groups directory rework plan, docs/decisions.md): previously
 * reachable only from the *group's* own `SidePanel` (a member picker
 * scoped to that one group), never from the user's own row on
 * `OrgAdminPage.tsx`'s Users table. Pure UI reachability fix — no new
 * backend endpoint; `onAdd` is the caller's own existing `addGroupMember`
 * handler (`POST /orgs/{orgId}/groups/{groupId}/members`), unchanged.
 *
 * A one-field "pick an existing group" action fits `Popover` (style guide
 * "Pattern: create panels, popovers, and one door for bulk" — Popover
 * reserved for a quick action on something that already exists, not a
 * `Modal`, which this repo reserves for creating a new entity), so this
 * reuses `Popover` directly rather than a bespoke inline dropdown, the
 * same anchored-quick-pick shape `ProjectAdminPage.tsx`'s own group
 * `SidePanel` nesting controls already use.
 *
 * Renders nothing at all when the user is already a member of every group
 * in the organisation (nothing left to add them to) — same "hide rather
 * than show an empty/useless control" treatment `ProjectMembersTable`'s
 * own per-row Actions column gives a member with no eligible action.
 */
import { UserPlus } from "lucide-react";
import { useRef, useState } from "react";

import type { OrgGroup, OrgUser } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Popover } from "./Popover";

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
      <button
        ref={triggerRef}
        type="button"
        className="btn"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <UserPlus size={14} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={label} onClose={() => setOpen(false)}>
          <div className="stack">
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.orgAdmin.addToGroupSelectLabel}
              <select
                className="input"
                aria-label={strings.orgAdmin.addToGroupSelectLabel}
                value={groupId}
                onChange={(e) => setGroupId(e.target.value)}
                autoFocus
              >
                <option value="">{strings.orgAdmin.addToGroupSelectPlaceholder}</option>
                {availableGroups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setOpen(false)}>
                {strings.common.cancel}
              </button>
              <button
                className="btn btn-primary"
                disabled={!groupId}
                onClick={() => {
                  onAdd(groupId, user.user_id);
                  setGroupId("");
                  setOpen(false);
                }}
              >
                {strings.membersTable.add}
              </button>
            </div>
          </div>
        </Popover>
      )}
    </>
  );
}
