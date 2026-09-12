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
 * with no manager at all and no fallback-group/other-group coverage —
 * mirrors `OrgAdminPage.tsx`'s own "can't revoke your own org role"
 * disabled-with-title precedent. The backend re-enforces this
 * independently (`revoke_standard_member_role`/`revoke_standard_group_
 * role`'s own 400) regardless of what this component renders — this is a
 * UX hint, not the authorization boundary.
 *
 * Phase 30 (module system's generic group-based module-role grants,
 * `GroupModuleRole`) rebuilt this section's add-member flow onto
 * `UserAutocomplete` — search-as-you-type over this org's real user
 * directory (`organizationId` set, debounced server-side search) plus
 * org-group matching (`groups`/`onSelectGroup`), mirroring `OrgAdminPage.
 * tsx`'s own "manage users" add-flow wiring (`addManageUsersGroupRole` ->
 * `POST .../group-roles`) one level down — replacing the previous plain,
 * unfiltered `<select>` over `orgUsers` this human-review round flagged as
 * inconsistent with every other add-member control in the app.
 * `onSelectExternal` is deliberately left unwired — no concrete need for
 * external Standards-Contributor invites has come up yet.
 *
 * The roster itself gained a second row kind for group-based grants
 * (`ComplianceStandardGroupMember`), visually distinguished with the same
 * `Users` icon + "Org group" badge `UserAutocomplete` already uses for a
 * group match, rather than expanding a group to its individual members —
 * this remains a roster of this standard's own *direct* grants (user or
 * group), not every user a group happens to currently reach.
 */
import { UserPlus, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { OrgGroup, OrgUser } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { Popover } from "../../components/Popover";
import { Spinner } from "../../components/Spinner";
import { UserAutocomplete } from "../../components/UserAutocomplete";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_STANDARD_ROLE_LABEL,
  type ComplianceStandard,
  type ComplianceStandardGroupMember,
  type ComplianceStandardMember,
  type ComplianceStandardMembers,
  type ComplianceStandardRoleKey,
} from "./types";

const STANDARD_ROLE_KEYS: ComplianceStandardRoleKey[] = ["standards_manager", "standards_contributor"];

const LAST_MANAGER_TITLE =
  "This standard must always have at least one Standards Manager. Assign another manager, or " +
  "configure a fallback compliance-managers group in this organisation's Compliance settings, " +
  "before removing the last one.";

type Row = { kind: "user"; member: ComplianceStandardMember } | { kind: "group"; group: ComplianceStandardGroupMember };

export function StandardMembersSection({
  orgId,
  standard,
  orgUsers,
  orgGroups,
}: {
  orgId: string;
  standard: ComplianceStandard;
  /** Already loaded by the caller (`StandardWorkspacePage.tsx`) — every
   * user in this standard's own organisation. Passed to `UserAutocomplete`
   * only to satisfy its required prop; with `organizationId` set below,
   * matching itself runs server-side, not against this array. */
  orgUsers: OrgUser[];
  /** Already loaded by the caller — every org group in this standard's own
   * organisation, matched client-side by `UserAutocomplete` the same way
   * `OrgAdminPage.tsx`'s own "manage users" add-flow matches `allGroups`. */
  orgGroups: OrgGroup[];
}) {
  const { showToast } = useToast();
  const [data, setData] = useState<ComplianceStandardMembers | null>(null);
  const [addOpen, setAddOpen] = useState(false);
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

  async function handleToggleUserRole(member: ComplianceStandardMember, roleKey: ComplianceStandardRoleKey, checked: boolean) {
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

  async function handleToggleGroupRole(group: ComplianceStandardGroupMember, roleKey: ComplianceStandardRoleKey, checked: boolean) {
    try {
      if (checked) {
        await complianceApi.assignStandardGroupRole(orgId, standard.id, group.org_group_id, roleKey);
      } else {
        await complianceApi.revokeStandardGroupRole(orgId, standard.id, group.org_group_id, roleKey);
      }
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this group's role."), "error");
    }
  }

  async function handleAddUser(userId: string) {
    setAddOpen(false);
    try {
      await complianceApi.assignStandardMemberRole(orgId, standard.id, userId, addRoleKey);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not add this member."), "error");
    }
  }

  async function handleAddGroup(groupId: string) {
    setAddOpen(false);
    try {
      await complianceApi.assignStandardGroupRole(orgId, standard.id, groupId, addRoleKey);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not add this group."), "error");
    }
  }

  if (!data) return <Spinner />;

  // Manager-floor client-side hint: every explicit `standards_manager`
  // source counts — a direct grant, or a group grant whose group currently
  // has at least one effective member (a group with zero members isn't
  // real coverage, matching the backend's own floor logic). This is a UX
  // hint only; `revoke_standard_member_role`/`revoke_standard_group_role`
  // re-check independently and authoritatively.
  const managerCount =
    data.members.filter((m) => m.role_keys.includes("standards_manager")).length +
    data.group_members.filter((g) => g.role_keys.includes("standards_manager") && g.member_count > 0).length;

  const rows: Row[] = [
    ...data.members.map((member): Row => ({ kind: "user", member })),
    ...data.group_members.map((group): Row => ({ kind: "group", group })),
  ];

  const columns: DirectoryColumn<Row>[] = [
    {
      key: "name",
      label: "Name",
      render: (row) =>
        row.kind === "user" ? (
          row.member.display_name
        ) : (
          <span className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
            <Users size={14} aria-hidden="true" />
            {row.group.group_name} <span className="badge">Org group</span>
          </span>
        ),
    },
    {
      key: "email",
      label: "Email",
      render: (row) =>
        row.kind === "user"
          ? row.member.email
          : `${row.group.member_count} member${row.group.member_count === 1 ? "" : "s"}`,
    },
    {
      key: "roles",
      label: "Roles",
      render: (row) => {
        const name = row.kind === "user" ? row.member.display_name : row.group.group_name;
        const roleKeys = row.kind === "user" ? row.member.role_keys : row.group.role_keys;
        return (
          <MultiSelectDropdown
            triggerLabel={`Roles for ${name}`}
            emptyLabel="No roles"
            options={STANDARD_ROLE_KEYS.map((roleKey) => {
              const checked = roleKeys.includes(roleKey);
              const isLastManager = roleKey === "standards_manager" && checked && managerCount <= 1;
              const disabled = isLastManager && !data.manager_floor_covered_by_fallback;
              return {
                value: roleKey,
                label: COMPLIANCE_STANDARD_ROLE_LABEL[roleKey],
                checked,
                disabled,
                title: disabled ? LAST_MANAGER_TITLE : undefined,
                optionLabel: checked
                  ? `Revoke ${COMPLIANCE_STANDARD_ROLE_LABEL[roleKey]} from ${name}`
                  : `Grant ${COMPLIANCE_STANDARD_ROLE_LABEL[roleKey]} to ${name}`,
                onToggle: () =>
                  row.kind === "user"
                    ? handleToggleUserRole(row.member, roleKey, !checked)
                    : handleToggleGroupRole(row.group, roleKey, !checked),
              };
            })}
          />
        );
      },
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button ref={addTriggerRef} type="button" className="btn" onClick={() => setAddOpen((o) => !o)}>
          <UserPlus size={14} /> Add member
        </button>
      </div>
      {addOpen && (
        <Popover anchorRef={addTriggerRef} title="Add a member" onClose={() => setAddOpen(false)}>
          <div className="stack">
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
            <UserAutocomplete
              users={orgUsers}
              organizationId={orgId}
              placeholder="Search people or groups…"
              onSelect={handleAddUser}
              groups={orgGroups}
              onSelectGroup={handleAddGroup}
            />
          </div>
        </Popover>
      )}
      <DirectoryTable
        ariaLabel={`Members of ${standard.name}`}
        columns={columns}
        rows={rows}
        rowKey={(row) => (row.kind === "user" ? `user:${row.member.user_id}` : `group:${row.group.org_group_id}`)}
        emptyState={<p className="text-muted">No direct members yet.</p>}
      />
    </div>
  );
}
