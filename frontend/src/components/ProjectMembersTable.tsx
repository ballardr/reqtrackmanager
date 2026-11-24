/**
 * Module: components/ProjectMembersTable
 *
 * The unified "who has access to this {project}, and why" table (docs/decisions.md), shared by
 * `ProjectAdminPage.tsx`'s Members section and `OrgAdminPage.tsx`'s "Manage users" modal over
 * `GET /{project_id}/effective-members` (with provenance). Search, the role filter and "Show invited" live inside
 * this component so both call sites behave identically.
 *
 * Rows (a `kind`-discriminated union), `members`/`invites` caller-supplied and fully loaded (the role filter and
 * the invite merge need the complete set, so they are not server-paginated):
 * - `member`: one row per effective member. The Role cell is a `MultiSelectDropdown` over the four `ProjectRole`
 *   values, checked from `EffectiveMember.sources`. An option is togglable (`onToggleRole`, `POST`/`DELETE
 *   /roles`) only when its sole source is `direct_role`, an individually revocable `UserProjectRole` row; the
 *   delete endpoint removes only those rows, so any other source (`direct_group`, `direct_org_group`,
 *   `direct_org_group_role`, `direct_project_ref`, `direct_org_wide`; see `MemberSourceProvenanceKind` in
 *   `api/types.ts`) shows checked but disabled, with a "(by group)" / "(only manager)" label suffix stating why.
 *   A client-side "last manager" hint covers a purely direct `project_manager` option; it is an approximation,
 *   and the backend guard on every mutating endpoint (`routers/projects.py::revoke_project_role`) is authoritative.
 *   Module-contributed roles (`availableModuleRoles`, already project-scoped) are extra options toggled through
 *   `onToggleModuleRole`; they are direct-grant-only, so never disabled, and labelled with the role's own `name`.
 *   The Source cell is one phrase ("Direct", "Group", "Direct and group") that opens a `Popover` with the
 *   per-source detail (`MemberSourceSummary`).
 * - `invited`: a pending invite from `GET /{project_id}/pending-invites`, with a status badge
 *   (`PENDING_INVITE_STATUS_LABEL`) and a Resend button (`onResendInvite`) in place of the dropdown.
 * - `group`: an organisation group with a direct `OrgGroupProjectRole` grant (`groupRoles`). Its Role cell is a
 *   `MultiSelectDropdown` over the core roles, always togglable (`onToggleGroupRole`) because the row is the
 *   grant; the Name cell carries a "Group" badge, the Source cell says "Direct" and Actions offers only "Remove
 *   group" (`onRemoveGroup`, behind a Tier 1 `ConfirmDialog`).
 *
 * Actions column, one `ActionMenu` per member row: "Remove all access" (`onRemoveAllAccess`, offered only when
 * every source is `direct_role`, behind a Tier 1 `ConfirmDialog`) and "Convert inherited access to direct roles"
 * (`onConvertToDirect`, additive so no confirm). Each callback is optional ("omit to hide"); the component fetches
 * and mutates nothing itself.
 */
import { Info, Send, Trash2, Wand2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import type {
  EffectiveMember,
  MemberSourceProvenance,
  ModuleRoleDefinition,
  OrgGroupProjectRoleSummary,
  PendingInvite,
  ProjectRole,
} from "../api/types";
import { PENDING_INVITE_STATUS_LABEL, PROJECT_ROLE_INHERITANCE_MODE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import type { Strings } from "../i18n/strings";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import type { DirectoryColumn } from "./DirectoryTable";
import { DirectoryTable } from "./DirectoryTable";
import { FilterCheckbox, FilterPanel } from "./FilterPanel";
import { FilterSelect } from "./FilterSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { Popover } from "./Popover";
import { cycleSort, type SortState } from "./sortState";
import { Badge } from "./Badge";
import { ServiceBadge } from "./ServiceBadge";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { instantOf, sortRows, type SortValue } from "../utils/sortRows";

const PROJECT_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder", "member"];
const PAGE_SIZE = 20;
/** Longest joined role list the Role cell shows; beyond it the cell reads "N roles" so a row never widens the column. */
const ROLES_SUMMARY_MAX_LENGTH = 28;

type Row =
  | { kind: "member"; member: EffectiveMember }
  | { kind: "invited"; invite: PendingInvite }
  | { kind: "group"; group: OrgGroupProjectRoleSummary };
type SortKey = "name" | "email" | "role" | "source";

/** Per-role provenance text for the Source column: one line per source a user holds a given role through
 * (`MemberSourceProvenanceKind` in `api/types.ts` describes the five direct kinds). */
function sourceLine(strings: Strings, s: MemberSourceProvenance): string {
  switch (s.kind) {
    case "direct_role":
      return strings.membersTable.sourceDirectRole;
    case "direct_group":
      return s.via_group_name
        ? strings.membersTable.sourceDirectGroup(s.via_group_name)
        : strings.membersTable.sourceDirectRole;
    case "direct_org_group":
      return s.via_group_name
        ? strings.membersTable.sourceDirectOrgGroup(s.via_group_name)
        : strings.membersTable.sourceDirectRole;
    case "direct_org_group_role":
      return s.via_group_name
        ? strings.membersTable.sourceDirectOrgGroupRole(s.via_group_name)
        : strings.membersTable.sourceDirectRole;
    case "direct_project_ref":
      return strings.membersTable.sourceDirectProjectRef;
    case "direct_org_wide":
      return strings.membersTable.sourceDirectOrgWide;
    case "forward_inherited":
      return s.via_project_name && s.via_mode
        ? strings.membersTable.sourceForwardInherited(s.via_project_name, PROJECT_ROLE_INHERITANCE_MODE_LABEL[s.via_mode])
        : strings.membersTable.sourceDirectRole;
    case "member_source_inherited":
      return s.via_project_name && s.via_mode
        ? strings.membersTable.sourceMemberSourceInherited(s.via_project_name, PROJECT_ROLE_INHERITANCE_MODE_LABEL[s.via_mode])
        : strings.membersTable.sourceDirectRole;
    default:
      return "";
  }
}

/**
 * The Source column's one-phrase summary for a member, the text `MemberSourceSummary` shows and the Source sort value.
 *
 * @param strings The resolved UI strings.
 * @param member The effective member.
 * @returns "Direct", "Group" or "Direct and group", or `null` when the member has no source.
 */
function sourceSummaryLabel(strings: Strings, member: EffectiveMember): string | null {
  if (member.sources.length === 0) return null;
  const hasDirect = member.sources.some((s) => s.kind === "direct_role");
  const hasIndirect = member.sources.some((s) => s.kind !== "direct_role");
  if (!hasIndirect) return strings.membersTable.sourceDirectRole;
  return hasDirect ? strings.membersTable.sourceSummaryDirectAndGroup : strings.membersTable.sourceSummaryGroup;
}

/** The roles' displayed names joined in the order the Role dropdown lists them, for the Role sort value; `null` when none are held. */
function joinedRoleNames(roles: ProjectRole[], moduleNames: string[]): string | null {
  const names = [...PROJECT_ROLES.filter((role) => roles.includes(role)).map((role) => PROJECT_ROLE_LABEL[role]), ...moduleNames];
  return names.length > 0 ? names.join(", ") : null;
}

/** The Source column's cell for a `kind: "member"` row: one plain word or phrase ("Direct" / "Group" / "Direct and
 * group"), because the Role column already names the roles held. The per-source detail (`sourceLine`) is behind a
 * click-to-open `Popover`. */
function MemberSourceSummary({ strings, member }: { strings: Strings; member: EffectiveMember }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  if (member.sources.length === 0) return <span className="text-muted">—</span>;

  const label = sourceSummaryLabel(strings, member) ?? "";

  // Every source is `direct_role`, so a popover would only repeat "Direct" per role; the disclosure is skipped.
  if (member.sources.every((s) => s.kind === "direct_role")) return <span className="text-muted">{label}</span>;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="disclosure-toggle"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Info size={14} />
        {label}
      </button>
      {open && (
        <Popover
          anchorRef={triggerRef}
          title={strings.membersTable.sourceSummaryDetailTitle(member.display_name)}
          onClose={() => setOpen(false)}
        >
          <div className="stack" style={{ gap: "0.15rem" }}>
            {member.sources.map((s, i) => (
              <span key={i} className="text-muted" style={{ fontSize: "0.85rem" }}>
                {sourceLine(strings, s)} ({PROJECT_ROLE_LABEL[s.role]})
              </span>
            ))}
          </div>
        </Popover>
      )}
    </>
  );
}

/**
 * The sort value of each sortable column for every row kind, matching the text the cell shows.
 *
 * @param strings The resolved UI strings.
 * @param moduleRoles The module roles offered in the Role dropdown, whose names a member's checked module roles add to the Role value.
 * @returns Accessors keyed by column key: name and email (an invite has no name, a group no email), Role (the joined role
 *   names, or the invite's status label), Source (the summary phrase; an invite by its sent time).
 */
function rowSortValues(strings: Strings, moduleRoles: ModuleRoleDefinition[]): Record<SortKey, (row: Row) => SortValue> {
  return {
    name: (row) => (row.kind === "member" ? row.member.display_name : row.kind === "group" ? row.group.org_group_name : null),
    email: (row) => (row.kind === "member" ? row.member.email : row.kind === "invited" ? row.invite.email : null),
    role: (row) => {
      if (row.kind === "invited") return PENDING_INVITE_STATUS_LABEL[row.invite.status];
      if (row.kind === "group") return joinedRoleNames(row.group.roles, []);
      const { member } = row;
      const moduleNames = moduleRoles
        .filter((d) => member.module_roles.some((g) => g.module_key === d.module_key && g.role_key === d.role_key))
        .map((d) => d.name);
      return joinedRoleNames(member.sources.map((s) => s.role), moduleNames);
    },
    source: (row) =>
      row.kind === "invited"
        ? instantOf(row.invite.created_at)
        : row.kind === "group"
          ? strings.membersTable.sourceDirectRole
          : sourceSummaryLabel(strings, row.member),
  };
}

export function ProjectMembersTable({
  members,
  invites,
  groupRoles = [],
  onToggleRole,
  onToggleGroupRole,
  onResendInvite,
  resendingInviteId,
  onRemoveAllAccess,
  onConvertToDirect,
  onRemoveGroup,
  addControl,
  ariaLabel,
  availableModuleRoles = [],
  onToggleModuleRole,
}: {
  members: EffectiveMember[];
  invites: PendingInvite[];
  /** Organisation groups holding a direct `OrgGroupProjectRole` grant on this project, rendered as `kind: "group"`
   * rows beside the member and invited rows. Defaults to `[]`. */
  groupRoles?: OrgGroupProjectRoleSummary[];
  /** Grants `role` to the user when `checked` is true, revokes it otherwise. Only called for an option whose sole
   * source is `direct_role`; any other option is disabled. */
  onToggleRole: (userId: string, role: ProjectRole, checked: boolean) => void;
  /** Grants or revokes one role on a group's `kind: "group"` row. Always callable, because the row's existence
   * means every listed role is the group's own direct grant. Typed optional so a caller with nothing to pass needs
   * no stub. */
  onToggleGroupRole?: (orgGroupId: string, role: ProjectRole, checked: boolean) => void;
  onResendInvite: (invite: PendingInvite) => void;
  /** The invite currently being resent, if any — disables that row's
   * Resend button while the request is in flight. */
  resendingInviteId?: string | null;
  /** Per-row "Remove all access", called after the built-in `ConfirmDialog` is confirmed and only offered for a
   * member whose sources are all `direct_role` (`allDirectRoleSourced`). The caller loops the per-role
   * `DELETE /roles/{user_id}/{role}` calls. Omit to hide the Actions column. */
  onRemoveAllAccess?: (userId: string) => void;
  /** Per-row "Convert inherited access to direct roles", called directly (additive, so no confirm) and only
   * offered for a member with a `forward_inherited` or `member_source_inherited` source. The caller calls
   * `POST /{project_id}/materialize-inherited-access/{user_id}` and refreshes `members`. Omit to hide the Actions
   * column. */
  onConvertToDirect?: (userId: string) => void;
  /** A group row's "Remove group", called after the built-in `ConfirmDialog` is confirmed. The caller loops
   * `DELETE .../group-roles/{org_group_id}/{role}` over every role the group holds. Omit to hide "Remove group". */
  onRemoveGroup?: (orgGroupId: string) => void;
  /** Caller-composed "add a member" control (`UserAutocomplete` + a role
   * `<select>`) — differs slightly per call site, so this table only
   * provides the slot. Omit for a read-only rendering. */
  addControl?: ReactNode;
  /** Accessible name for the table itself. */
  ariaLabel: string;
  /** Project-scoped module-contributed role definitions available to grant, already filtered to enabled modules by
   * the caller (`GET /{project_id}/module-roles`). Defaults to `[]`, leaving the four core `ProjectRole` options. */
  availableModuleRoles?: ModuleRoleDefinition[];
  /** Grants or revokes one module-contributed role on a member. Always callable: module roles are direct-grant-only
   * with no inherited source to guard against. Typed optional so a caller with nothing to pass needs no stub. */
  onToggleModuleRole?: (userId: string, moduleKey: string, roleKey: string, grant: boolean) => void;
}) {
  const strings = useStrings();
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<ProjectRole | "">("");
  const [showInvited, setShowInvited] = useState(true);
  const [sort, setSort] = useState<SortState<SortKey> | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [confirmRemoveUserId, setConfirmRemoveUserId] = useState<string | null>(null);
  const [confirmRemoveGroupId, setConfirmRemoveGroupId] = useState<string | null>(null);

  useResetOnChange([search, roleFilter, showInvited], () => setVisibleCount(PAGE_SIZE));

  const needle = search.trim().toLowerCase();

  const filteredInvites = showInvited
    ? invites.filter(
        (inv) => (!needle || inv.email.toLowerCase().includes(needle)) && (!roleFilter || inv.role === roleFilter)
      )
    : [];

  const filteredMembers = members.filter((m) => {
    if (needle && !m.display_name.toLowerCase().includes(needle) && !m.email.toLowerCase().includes(needle)) return false;
    if (roleFilter && !m.sources.some((s) => s.role === roleFilter)) return false;
    return true;
  });
  // Same search/role-filter treatment as `filteredMembers` above, applied
  // to group rows — a group has no email, so search only matches
  // its name.
  const filteredGroupRoles = groupRoles.filter((g) => {
    if (needle && !g.org_group_name.toLowerCase().includes(needle)) return false;
    if (roleFilter && !g.roles.includes(roleFilter)) return false;
    return true;
  });

  // Invited and group rows render ahead of the member rows ("fixed kind first" in the style guide's type-badged mixed
  // rows pattern); each kind is ordered within itself by the sort, since the kinds hold different values.
  const sortValues = rowSortValues(strings, availableModuleRoles);
  const rows: Row[] = [
    ...sortRows(filteredInvites.map((invite): Row => ({ kind: "invited", invite })), sort, sortValues),
    ...sortRows(filteredGroupRoles.map((group): Row => ({ kind: "group", group })), sort, sortValues),
    ...sortRows(filteredMembers.map((member): Row => ({ kind: "member", member })), sort, sortValues),
  ];
  const visible = rows.slice(0, visibleCount);

  // Client-side "last manager" hint (see module docstring) — counts only
  // members whose project_manager role has a direct_role-kind source, not
  // any other kind.
  const directRoleManagerCount = members.filter((m) =>
    m.sources.some((s) => s.role === "project_manager" && s.kind === "direct_role")
  ).length;

  function applySort(key: SortKey) {
    setSort((current) => cycleSort(current, key));
  }

  const columns: DirectoryColumn<Row>[] = [
    {
      key: "name",
      label: strings.membersTable.name,
      sortable: true,
      render: (row) => {
        if (row.kind === "member") {
          return row.member.is_service_account ? (
            <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
              {row.member.display_name}
              <ServiceBadge />
            </span>
          ) : (
            row.member.display_name
          );
        }
        if (row.kind === "invited") return <span className="text-muted">—</span>;
        // A "Group" badge ahead of the name so the row does not read as a person with a blank email; no separate
        // Type column.
        return (
          <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
            <Badge>{strings.membersTable.groupRowBadge}</Badge>
            {row.group.org_group_name}
          </span>
        );
      },
    },
    {
      key: "email",
      label: strings.membersTable.email,
      sortable: true,
      render: (row) => {
        if (row.kind === "member") return row.member.email;
        if (row.kind === "invited") return row.invite.email;
        return <span className="text-muted">—</span>;
      },
    },
    {
      key: "role",
      label: strings.membersTable.role,
      sortable: true,
      render: (row) => {
        if (row.kind === "invited") {
          const invite = row.invite;
          return (
            <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
              <Badge>{PENDING_INVITE_STATUS_LABEL[invite.status]}</Badge>
              <button
                className="btn"
                disabled={resendingInviteId === invite.id}
                onClick={() => onResendInvite(invite)}
                title={strings.admin.resendInviteAria(invite.email)}
                aria-label={strings.admin.resendInviteAria(invite.email)}
              >
                <Send /> {strings.admin.resendInvite}
              </button>
            </div>
          );
        }
        if (row.kind === "group") {
          const group = row.group;
          // No `purelyDirect`/`isLastManager` treatment: the row's existence means every listed role is the group's
          // direct grant, and `get_effective_project_managers` never counts a group-derived manager towards the
          // last-manager floor, so a client-side hint would rarely predict a real block. The backend guard is
          // authoritative; a rejected revoke surfaces through the caller's error toast.
          return (
            <MultiSelectDropdown
              triggerLabel={strings.membersTable.rolesFor(group.org_group_name)}
              emptyLabel={strings.membersTable.noRoles}
              summaryMaxLength={ROLES_SUMMARY_MAX_LENGTH}
              summaryCount={strings.membersTable.nRoles}
              options={PROJECT_ROLES.map((role) => {
                const checked = group.roles.includes(role);
                // Same rule as a member row: the last role cannot be cleared, since the row would vanish.
                const isOnlyRole = checked && group.roles.length === 1;
                return {
                  value: role,
                  label: PROJECT_ROLE_LABEL[role] + (isOnlyRole ? ` ${strings.membersTable.roleOnlyRoleSuffix}` : ""),
                  checked,
                  disabled: isOnlyRole,
                  title: isOnlyRole ? strings.membersTable.cannotRemoveOnlyRole : undefined,
                  optionLabel: checked
                    ? strings.membersTable.revokeRole(PROJECT_ROLE_LABEL[role], group.org_group_name)
                    : strings.membersTable.grantRole(PROJECT_ROLE_LABEL[role], group.org_group_name),
                  onToggle: () => onToggleGroupRole?.(group.org_group_id, role, !checked),
                };
              })}
            />
          );
        }
        const member = row.member;
        return (
          <MultiSelectDropdown
            triggerLabel={strings.membersTable.rolesFor(member.display_name)}
            emptyLabel={strings.membersTable.noRoles}
            summaryMaxLength={ROLES_SUMMARY_MAX_LENGTH}
            summaryCount={strings.membersTable.nRoles}
            options={[
              ...PROJECT_ROLES.map((role) => {
                const sourcesForRole = member.sources.filter((s) => s.role === role);
                const checked = sourcesForRole.length > 0;
                const kinds = new Set(sourcesForRole.map((s) => s.kind));
                const purelyDirect = checked && kinds.size === 1 && kinds.has("direct_role");
                const isLastManager = purelyDirect && role === "project_manager" && directRoleManagerCount <= 1;
                // A member exists only through its role grants, so revoking the last one removes the row at once
                // (and its subscriptions). Removal is the confirmed "Remove all access" action, never a side effect
                // of clearing a role, so a person changing roles can clear roles first without losing the member.
                const isOnlyAccess =
                  purelyDirect && !member.sources.some((s) => !(s.role === role && s.kind === "direct_role"));
                const disabled = checked && (!purelyDirect || isLastManager || isOnlyAccess);
                const title = !disabled
                  ? undefined
                  : !purelyDirect
                    ? strings.membersTable.roleNotDirectlyRevocable
                    : isLastManager
                      ? strings.membersTable.cannotRemoveLastManager
                      : strings.membersTable.cannotRemoveOnlyRole;
                // Inline suffix on the option's label (not only its hover `title`) so a disabled option states why
                // at a glance; `roleByGroupSuffix` explains the one generic "(by group)" wording.
                const disabledSuffix = !disabled
                  ? ""
                  : !purelyDirect
                    ? ` ${strings.membersTable.roleByGroupSuffix}`
                    : isLastManager
                      ? ` ${strings.membersTable.roleOnlyManagerSuffix}`
                      : ` ${strings.membersTable.roleOnlyRoleSuffix}`;
                return {
                  value: role,
                  label: PROJECT_ROLE_LABEL[role] + disabledSuffix,
                  checked,
                  disabled,
                  title,
                  optionLabel: checked
                    ? strings.membersTable.revokeRole(PROJECT_ROLE_LABEL[role], member.display_name)
                    : strings.membersTable.grantRole(PROJECT_ROLE_LABEL[role], member.display_name),
                  onToggle: () => onToggleRole(member.user_id, role, !checked),
                };
              }),
              // Merged in beside the core roles with the same styling; never disabled (module roles skip the
              // `purelyDirect` check).
              ...availableModuleRoles.map((d) => {
                const checked = member.module_roles.some(
                  (g) => g.module_key === d.module_key && g.role_key === d.role_key
                );
                return {
                  value: `${d.module_key}:${d.role_key}`,
                  label: d.name,
                  checked,
                  optionLabel: checked
                    ? strings.membersTable.revokeRole(d.name, member.display_name)
                    : strings.membersTable.grantRole(d.name, member.display_name),
                  onToggle: () => onToggleModuleRole?.(member.user_id, d.module_key, d.role_key, !checked),
                };
              }),
            ]}
          />
        );
      },
    },
    {
      key: "source",
      label: strings.membersTable.source,
      sortable: true,
      render: (row) => {
        if (row.kind === "invited") {
          return (
            <span className="text-muted">
              {strings.membersTable.invitedSentOn(new Date(row.invite.created_at).toLocaleDateString())}
            </span>
          );
        }
        if (row.kind === "group") {
          // A group's direct grant has no upstream provenance, so the cell states "Direct" once rather than per role.
          return <span className="text-muted">{strings.membersTable.sourceDirectRole}</span>;
        }
        return <MemberSourceSummary strings={strings} member={row.member} />;
      },
    },
  ];

  if (onRemoveAllAccess || onConvertToDirect || onRemoveGroup) {
    columns.push({
      key: "actions",
      label: "",
      render: (row) => {
        if (row.kind === "invited") return null;
        if (row.kind === "group") {
          if (!onRemoveGroup) return null;
          const group = row.group;
          const items: ActionMenuItem[] = [
            {
              label: strings.membersTable.removeGroup,
              icon: <Trash2 size={14} />,
              onSelect: () => setConfirmRemoveGroupId(group.org_group_id),
            },
          ];
          return <ActionMenu triggerLabel={strings.membersTable.actionsFor(group.org_group_name)} items={items} />;
        }
        const member = row.member;
        // "Remove all access" is offered only when every source is an individually revocable `direct_role` row,
        // the same "purely direct" test the Role dropdown applies per option, across all held roles: looping the
        // per-role DELETE would otherwise leave group- or inheritance-sourced access in place while claiming to
        // remove all of it.
        const allDirectRoleSourced = member.sources.length > 0 && member.sources.every((s) => s.kind === "direct_role");
        const hasInheritedSource = member.sources.some(
          (s) => s.kind === "forward_inherited" || s.kind === "member_source_inherited"
        );
        const items: ActionMenuItem[] = [];
        if (onRemoveAllAccess && allDirectRoleSourced) {
          items.push({
            label: strings.membersTable.removeAllAccess,
            icon: <Trash2 size={14} />,
            onSelect: () => setConfirmRemoveUserId(member.user_id),
          });
        }
        if (onConvertToDirect && hasInheritedSource) {
          items.push({
            label: strings.membersTable.convertToDirect,
            icon: <Wand2 size={14} />,
            onSelect: () => onConvertToDirect(member.user_id),
          });
        }
        if (items.length === 0) return null;
        return <ActionMenu triggerLabel={strings.membersTable.actionsFor(member.display_name)} items={items} />;
      },
    });
  }

  const filtersActive = Boolean(needle) || Boolean(roleFilter) || !showInvited;
  const confirmRemoveMember = confirmRemoveUserId ? members.find((m) => m.user_id === confirmRemoveUserId) : undefined;
  const confirmRemoveGroup = confirmRemoveGroupId
    ? groupRoles.find((g) => g.org_group_id === confirmRemoveGroupId)
    : undefined;

  return (
    <div className="stack">
      {addControl}
      {confirmRemoveMember && onRemoveAllAccess && (
        <ConfirmDialog
          title={strings.membersTable.removeAllAccessConfirmTitle(confirmRemoveMember.display_name)}
          message={strings.membersTable.removeAllAccessConfirmMessage(confirmRemoveMember.display_name)}
          confirmLabel={strings.membersTable.removeAllAccessConfirmButton}
          onConfirm={() => {
            onRemoveAllAccess(confirmRemoveMember.user_id);
            setConfirmRemoveUserId(null);
          }}
          onCancel={() => setConfirmRemoveUserId(null)}
        />
      )}
      {confirmRemoveGroup && onRemoveGroup && (
        <ConfirmDialog
          title={strings.membersTable.removeGroupConfirmTitle(confirmRemoveGroup.org_group_name)}
          message={strings.membersTable.removeGroupConfirmMessage(confirmRemoveGroup.org_group_name)}
          confirmLabel={strings.membersTable.removeGroupConfirmButton}
          onConfirm={() => {
            onRemoveGroup(confirmRemoveGroup.org_group_id);
            setConfirmRemoveGroupId(null);
          }}
          onCancel={() => setConfirmRemoveGroupId(null)}
        />
      )}
      {/* `FilterPanel` renders as a full-width bar above the table (`layout="top"`), not the side layout: the
          four columns (Name, Email, Role, Source), a multi-select role dropdown and per-source text are too wide
          for a 240px side panel (docs/ux-style-guide.md, "Pattern: filter panel placement — side vs. top"). */}
      <FilterPanel
        layout="top"
        sectionKey="projectMembersTableFilters"
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder={strings.membersTable.search}
      >
        <FilterSelect
          label={strings.membersTable.roleFilterLabel}
          value={roleFilter}
          onChange={setRoleFilter}
          allLabel={strings.membersTable.allRoles}
          options={PROJECT_ROLES.map((role) => ({ value: role, label: PROJECT_ROLE_LABEL[role] }))}
        />
        <FilterCheckbox label={strings.membersTable.showInvited} checked={showInvited} onChange={setShowInvited} />
      </FilterPanel>
      <DirectoryTable
        ariaLabel={ariaLabel}
        columns={columns}
        rows={visible}
        rowKey={(row) =>
          row.kind === "member"
            ? `member-${row.member.user_id}`
            : row.kind === "invited"
              ? `invited-${row.invite.id}`
              : `group-${row.group.org_group_id}`
        }
        sort={sort}
        onSort={(key) => applySort(key as SortKey)}
        total={rows.length}
        onLoadMore={() => setVisibleCount((n) => n + PAGE_SIZE)}
        emptyState={
          <p className="text-muted">{filtersActive ? strings.membersTable.noResults : strings.membersTable.empty}</p>
        }
      />
    </div>
  );
}
