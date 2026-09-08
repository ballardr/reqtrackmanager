/**
 * Module: modules/compliance/StandardMembersSection
 *
 * The "Members" section of a standard's workspace (docs/compliance-module-
 * plan.md Phase 22) — this standard's own dedicated working group:
 * `standards_manager`/`standards_contributor` role grants, direct and
 * scoped to just this one `ComplianceStandard` row (module system Phase 2's
 * new generalised entity-scope mechanism). Renders through the same
 * `DirectoryTable` + `MultiSelectDropdown` combination every other role
 * roster in this app already uses (`OrgAdminPage.tsx`'s Users table,
 * `ProjectMembersTable.tsx`) — per docs/compliance-module-plan.md's own
 * "Reused Existing Patterns" section, the single most-corrected point in
 * this plan's whole design history, this is not a bespoke roster table.
 *
 * The last remaining `standards_manager` row's checkbox is disabled (with
 * an explanatory `title`) whenever unchecking it would leave the standard
 * with no manager at all and no fallback group coverage — mirrors
 * `OrgAdminPage.tsx`'s own "can't revoke your own org role" disabled-with-
 * title precedent. The backend re-enforces this independently
 * (`revoke_standard_member_role`'s own 400) regardless of what this
 * component renders — this is a UX hint, not the authorization boundary.
 *
 * Adding a member reuses `orgUsers` already loaded by the caller
 * (`StandardWorkspacePage.tsx`) rather than a second fetch — a small
 * `Popover` picker (user + initial role), mirroring `AddToGroupControl.tsx`'s
 * exact anchored-quick-pick shape one level down (a single-field pick
 * fits `Popover`, per the style guide's "one door" pattern — not a
 * `Modal`, reserved for creating a new entity, and this only links an
 * existing user to an existing standard).
 */
import { UserPlus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { OrgUser } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { Popover } from "../../components/Popover";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_STANDARD_ROLE_LABEL,
  type ComplianceStandard,
  type ComplianceStandardMember,
  type ComplianceStandardMembers,
  type ComplianceStandardRoleKey,
} from "./types";

const STANDARD_ROLE_KEYS: ComplianceStandardRoleKey[] = ["standards_manager", "standards_contributor"];

export function StandardMembersSection({
  orgId,
  standard,
  orgUsers,
}: {
  orgId: string;
  standard: ComplianceStandard;
  /** Already loaded by the caller (`StandardWorkspacePage.tsx`) — every
   * user in this standard's own organisation, the pool a new member is
   * picked from. */
  orgUsers: OrgUser[];
}) {
  const { showToast } = useToast();
  const [data, setData] = useState<ComplianceStandardMembers | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [addUserId, setAddUserId] = useState("");
  const [addRoleKey, setAddRoleKey] = useState<ComplianceStandardRoleKey>("standards_contributor");
  const addTriggerRef = useRef<HTMLButtonElement>(null);

  async function reload() {
    try {
      setData(await complianceApi.listStandardMembers(orgId, standard.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load this standard's members."), "error");
    }
  }

  useEffect(() => {
    setData(null);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, standard.id]);

  async function handleToggleRole(member: ComplianceStandardMember, roleKey: ComplianceStandardRoleKey, checked: boolean) {
    try {
      if (checked) {
        await complianceApi.assignStandardMemberRole(orgId, standard.id, member.user_id, roleKey);
      } else {
        await complianceApi.revokeStandardMemberRole(orgId, standard.id, member.user_id, roleKey);
      }
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this member's role."), "error");
    }
  }

  async function handleAdd() {
    if (!addUserId) return;
    try {
      await complianceApi.assignStandardMemberRole(orgId, standard.id, addUserId, addRoleKey);
      setAddUserId("");
      setAddRoleKey("standards_contributor");
      setAddOpen(false);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not add this member."), "error");
    }
  }

  if (!data) return <Spinner />;

  const managerCount = data.members.filter((m) => m.role_keys.includes("standards_manager")).length;
  const availableUsers = orgUsers.filter((u) => !data.members.some((m) => m.user_id === u.user_id));

  const columns: DirectoryColumn<ComplianceStandardMember>[] = [
    { key: "name", label: "Name", render: (m) => m.display_name },
    { key: "email", label: "Email", render: (m) => m.email },
    {
      key: "roles",
      label: "Roles",
      render: (member) => (
        <MultiSelectDropdown
          triggerLabel={`Roles for ${member.display_name}`}
          emptyLabel="No roles"
          options={STANDARD_ROLE_KEYS.map((roleKey) => {
            const checked = member.role_keys.includes(roleKey);
            const isLastManager = roleKey === "standards_manager" && checked && managerCount <= 1;
            const disabled = isLastManager && !data.manager_floor_covered_by_fallback;
            return {
              value: roleKey,
              label: COMPLIANCE_STANDARD_ROLE_LABEL[roleKey],
              checked,
              disabled,
              title: disabled
                ? "This standard must always have at least one Standards Manager. Assign another manager, or " +
                  "configure a fallback compliance-managers group in this organisation's Compliance settings, " +
                  "before removing the last one."
                : undefined,
              optionLabel: checked
                ? `Revoke ${COMPLIANCE_STANDARD_ROLE_LABEL[roleKey]} from ${member.display_name}`
                : `Grant ${COMPLIANCE_STANDARD_ROLE_LABEL[roleKey]} to ${member.display_name}`,
              onToggle: () => handleToggleRole(member, roleKey, !checked),
            };
          })}
        />
      ),
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button
          ref={addTriggerRef}
          type="button"
          className="btn"
          disabled={availableUsers.length === 0}
          onClick={() => setAddOpen((o) => !o)}
        >
          <UserPlus size={14} /> Add member
        </button>
      </div>
      {addOpen && (
        <Popover anchorRef={addTriggerRef} title="Add a member" onClose={() => setAddOpen(false)}>
          <div className="stack">
            <label className="stack" style={{ gap: "0.25rem" }}>
              User
              <select
                className="input"
                value={addUserId}
                onChange={(e) => setAddUserId(e.target.value)}
                autoFocus
              >
                <option value="">Select a user…</option>
                {availableUsers.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.display_name} ({u.email})
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              Role
              <select
                className="input"
                value={addRoleKey}
                onChange={(e) => setAddRoleKey(e.target.value as ComplianceStandardRoleKey)}
              >
                {STANDARD_ROLE_KEYS.map((roleKey) => (
                  <option key={roleKey} value={roleKey}>
                    {COMPLIANCE_STANDARD_ROLE_LABEL[roleKey]}
                  </option>
                ))}
              </select>
            </label>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setAddOpen(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!addUserId} onClick={handleAdd}>Add</button>
            </div>
          </div>
        </Popover>
      )}
      <DirectoryTable
        ariaLabel={`Members of ${standard.name}`}
        columns={columns}
        rows={data.members}
        rowKey={(m) => m.user_id}
        emptyState={<p className="text-muted">No direct members yet.</p>}
      />
    </div>
  );
}
