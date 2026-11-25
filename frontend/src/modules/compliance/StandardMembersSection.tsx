/**
 * Module: modules/compliance/StandardMembersSection
 *
 * The "Members" section of a standard's workspace: the standard's own working group, `standards_manager` and
 * `standards_contributor` role grants, direct and scoped to this one `ComplianceStandard`. It uses the `DirectoryTable` +
 * `MultiSelectDropdown` combination of the other role rosters (`OrgAdminPage.tsx`, `ProjectMembersTable.tsx`).
 * - The last `standards_manager` checkbox is disabled (with an explanatory `title`) when unchecking it would leave no manager and
 *   no fallback-group or other-group coverage. The backend enforces this independently (`revoke_standard_member_role` and
 *   `revoke_standard_group_role` return 400); this is a hint, not the authorization boundary.
 * - Add-member uses `UserAutocomplete`: debounced server-side search over the organisation's users (`organizationId` set) plus
 *   organisation-group matching (`groups`/`onSelectGroup`), as `OrgAdminPage.tsx`'s manage-users add flow (`addManageUsersGroupRole`
 *   -> `POST .../group-roles`). `onSelectExternal` is unwired: no external Standards-Contributor invite is supported.
 * - The roster has a second row kind for group grants (`ComplianceStandardGroupMember`), drawn with `PrincipalBadge` (the
 *   group icon, with the kind and member count in its tooltip). It lists the standard's direct grants (user or group), not every
 *   user a group reaches.
 */
import { UserPlus } from "lucide-react";
import { useRef, useState } from "react";

import type { OrgGroup, OrgUser } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { PrincipalBadge } from "../../components/PrincipalBadge";
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
import { LabeledSelect } from "../../components/LabeledSelect";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useSortState } from "../../hooks/useTableSort";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";

const STANDARD_ROLE_KEYS: ComplianceStandardRoleKey[] = ["standards_manager", "standards_contributor"];

const LAST_MANAGER_TITLE =
  "This standard must always have at least one Standards Manager. Assign another manager, or " +
  "configure a fallback compliance-managers group in this organisation's Compliance settings, " +
  "before removing the last one.";

type Row = { kind: "user"; member: ComplianceStandardMember } | { kind: "group"; group: ComplianceStandardGroupMember };

/** Sortable value of each column: a group has no email (its cell shows a dash, which sorts last) and the roles order by their joined labels. */
const MEMBER_SORT_VALUES: Record<string, (row: Row) => SortValue> = {
  name: (row) => (row.kind === "user" ? row.member.display_name : row.group.group_name),
  email: (row) => (row.kind === "user" ? row.member.email : null),
  roles: (row) =>
    STANDARD_ROLE_KEYS.filter((roleKey) => (row.kind === "user" ? row.member.role_keys : row.group.role_keys).includes(roleKey))
      .map((roleKey) => COMPLIANCE_STANDARD_ROLE_LABEL[roleKey])
      .join(", ") || null,
};

export function StandardMembersSection({
  orgId,
  standard,
  orgUsers,
  orgGroups,
}: {
  orgId: string;
  standard: ComplianceStandard;
  /** Already loaded by the caller (`StandardWorkspacePage.tsx`): every user in the standard's organisation. Passed to
   * `UserAutocomplete` only to satisfy its required prop; with `organizationId` set, matching runs server-side. */
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

  useResetOnChange([orgId, standard.id], () => {
    setData(null);
  });
  useLoadOnChange(reload, [orgId, standard.id]);

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

  const sorting = useSortState();
  if (!data) return <Spinner />;

  // Manager-floor hint: every explicit `standards_manager` source counts, a direct grant or a group grant whose group has at
  // least one effective member (an empty group is not coverage, as in the backend's floor logic). The revoke endpoints re-check
  // authoritatively.
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
      sortable: true,
      render: (row) =>
        row.kind === "user" ? (
          row.member.display_name
        ) : (
          <PrincipalBadge
            principal={{ type: "org_group", id: row.group.org_group_id, label: row.group.group_name, member_count: row.group.member_count, exists: true }}
          />
        ),
    },
    {
      key: "email",
      label: "Email",
      sortable: true,
      render: (row) =>
        row.kind === "user" ? row.member.email : "—",
    },
    {
      key: "roles",
      label: "Roles",
      sortable: true,
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
          <UserPlus /> Add member
        </button>
      </div>
      {addOpen && (
        <Popover anchorRef={addTriggerRef} title="Add a member" onClose={() => setAddOpen(false)}>
          <div className="stack">
            <LabeledSelect helpNotNeeded
              label="Role"
              value={addRoleKey}
              onChange={(next) => setAddRoleKey(next as ComplianceStandardRoleKey)}
              options={STANDARD_ROLE_KEYS.map((roleKey) => ({ value: roleKey, label: COMPLIANCE_STANDARD_ROLE_LABEL[roleKey] }))}
              placeholder={null}
            />
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
        rows={sortRows(rows, sorting.sort, MEMBER_SORT_VALUES)}
        sort={sorting.sort}
        onSort={sorting.onSort}
        rowKey={(row) => (row.kind === "user" ? `user:${row.member.user_id}` : `group:${row.group.org_group_id}`)}
        emptyState={<p className="text-muted">No direct members yet.</p>}
      />
    </div>
  );
}
