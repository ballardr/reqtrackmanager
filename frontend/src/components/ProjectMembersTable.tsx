/**
 * Module: components/ProjectMembersTable
 *
 * The unified "who has access to this {project}, and why" table (Phase D,
 * follow-up UX batch, 2026-08-31, docs/decisions.md) — replaces both
 * `MemberRoleTable.tsx` (the direct-users-and-groups editable table) and
 * `PendingInvitesSection.tsx` (a separate pending-invites list), now that
 * Phase C removed default project groups: groups are no longer the common
 * way to grant a role, so a group-and-user union row shape stopped making
 * sense, and pending invites are folded in as a per-row status rather than
 * kept as a second section. Two call sites share this exact component:
 * `ProjectAdminPage.tsx`'s own "Members" section, and `OrgAdminPage.tsx`'s
 * "Manage users" modal — the same sharing precedent `MemberRoleTable`
 * established, now over `GET /{project_id}/effective-members` (with
 * provenance) instead of the retired `GET /{project_id}/direct-members`.
 *
 * Responsibilities:
 * - Renders one `DirectoryTable` row per effective member (`kind:
 *   "member"`) merged with this project's outstanding pending invites
 *   (`kind: "invited"`, from `GET /{project_id}/pending-invites`) — the
 *   same `kind`-discriminated union pattern `MemberRoleTable`/Org Admin's
 *   own Users table already established. Search, the role filter, and
 *   "Show invited" are handled entirely inside this component (unlike bare
 *   `DirectoryTable` call sites elsewhere, which leave `FilterPanel`
 *   composition to the page) precisely so both call sites render and
 *   behave identically — a real single implementation, not two pages each
 *   re-composing their own `FilterPanel` around a shared shell.
 * - A member row's Role cell is a `MultiSelectDropdown` over the four
 *   `ProjectRole` values — checked options come from `EffectiveMember.
 *   sources`. An option is only freely togglable (via the caller's
 *   `onToggleRole`, which calls `POST`/`DELETE /roles`) when its *only*
 *   source is the `direct_role` provenance kind — a genuine, individually
 *   revocable `UserProjectRole` row. An option whose sources include any of
 *   the other five kinds (`direct_group`, `direct_org_group`,
 *   `direct_org_group_role`, `direct_project_ref`, `direct_org_wide`) is
 *   shown checked-but-disabled with a `title` explaining why: `DELETE
 *   /{project_id}/roles/{user_id}/{role}` only ever deletes `UserProjectRole`
 *   rows, so offering it as if it worked for any other source would
 *   silently no-op while this table
 *   showed the role as removed. See `MemberSourceProvenanceKind`'s own doc
 *   comment (`api/types.ts`) for the full rationale — this is the exact
 *   fix the Phase D `kind` split exists to make possible.
 * - An invited row's Role cell shows a status badge (Pending/Expired,
 *   through `PENDING_INVITE_STATUS_LABEL`) and a Resend button instead of a
 *   `MultiSelectDropdown` — folded in from the retired
 *   `PendingInvitesSection.tsx`, unchanged in behavior (`onResendInvite`
 *   calls the same `POST .../pending-invites/{id}/resend`).
 * - A fast, client-side "last manager" hint (disabled + `title`) on a
 *   purely-`direct_role` `project_manager` option, computed only from
 *   `direct_role`-kind entries (not the old collapsed `direct` bucket a
 *   manager whose role actually comes from a group or org-wide visibility
 *   would otherwise misreport through) — mirrors the same disabled+title
 *   treatment `MultiSelectDropdown` already gives self-role-revoke on
 *   `OrgAdminPage.tsx`'s own Users table. Approximation only: the backend's
 *   own C-U-08 guard on every mutating endpoint this table calls into is
 *   what's actually authoritative (e.g. it also accounts for forward
 *   inheritance, which this client-side hint can't see) — see that guard's
 *   own docstring (`routers/projects.py::revoke_project_role`).
 *
 * Does not fetch or mutate any data itself, matching `MemberRoleTable`'s
 * own contract: `members`/`invites` are caller-supplied, already loaded in
 * full (small enough to load whole and search/filter/paginate client-side
 * — the same precedent `MemberRoleTable`'s own two data sources already
 * set, and why `GET /{project_id}/effective-members`'s own new `search`/
 * `limit`/`offset` support — added in this same phase for completeness and
 * future consumers — isn't used by this component: role-filtering and the
 * pending-invite merge both need the *complete* set to stay correct, and a
 * `LoadMoreButton` backed by real server-side offset pagination would make
 * a role filter silently incomplete for any member not yet loaded).
 * `onToggleRole`/`onResendInvite`/`addControl` are the caller's own API
 * calls and composed control, same division of responsibility
 * `MemberRoleTable` already proved out.
 * - Per-row Actions column (PR6 of the members/groups directory rework
 *   plan, docs/decisions.md): "Remove all access" and "Convert inherited
 *   access to direct roles", behind one `ActionMenu` per member row —
 *   offered/hidden per-row per that PR's own eligibility rules (see
 *   `allDirectRoleSourced`/`hasInheritedSource` below). `onRemoveAllAccess`/
 *   `onConvertToDirect` are the caller's own API calls, same division of
 *   responsibility as `onToggleRole` — this component only owns the Tier-1
 *   `ConfirmDialog` in front of "Remove all access" (a real, destructive,
 *   full revocation, not a single toggle); "Convert inherited access to
 *   direct roles" is additive/non-destructive, so it calls straight
 *   through with no confirm step, matching the bulk "Convert all inherited
 *   access to direct roles" button's own (confirm-free) treatment on
 *   `ProjectAdminPage.tsx`.
 */
import { Send, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { EffectiveMember, MemberSourceProvenance, PendingInvite, ProjectRole } from "../api/types";
import { PENDING_INVITE_STATUS_LABEL, PROJECT_ROLE_INHERITANCE_MODE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import type { Strings } from "../i18n/strings";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import type { DirectoryColumn } from "./DirectoryTable";
import { DirectoryTable } from "./DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "./FilterPanel";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { cycleSort, type SortState } from "./SortableHeader";

const PROJECT_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder", "member"];
const PAGE_SIZE = 20;

type Row = { kind: "member"; member: EffectiveMember } | { kind: "invited"; invite: PendingInvite };
type SortKey = "name" | "email";

/** Per-role provenance text for the Source column — one line per source a
 * user holds a given role through. See `MemberSourceProvenanceKind`'s own
 * doc comment (`api/types.ts`) for what each of the five direct kinds
 * means. */
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

export function ProjectMembersTable({
  members,
  invites,
  onToggleRole,
  onResendInvite,
  resendingInviteId,
  onRemoveAllAccess,
  onConvertToDirect,
  addControl,
  ariaLabel,
}: {
  members: EffectiveMember[];
  invites: PendingInvite[];
  /** Grants `role` to the user when `checked` is true, revokes it otherwise
   * — only ever called for an option whose sole source is `direct_role`
   * (see the module docstring); a non-`direct_role` option is rendered
   * disabled, so it can't reach this callback via the UI. */
  onToggleRole: (userId: string, role: ProjectRole, checked: boolean) => void;
  onResendInvite: (invite: PendingInvite) => void;
  /** The invite currently being resent, if any — disables that row's
   * Resend button while the request is in flight. */
  resendingInviteId?: string | null;
  /** Per-row "Remove all access" (Actions column, PR6) — called only after
   * the built-in `ConfirmDialog` is confirmed, and only ever offered for a
   * member whose sources are entirely `direct_role` (see
   * `allDirectRoleSourced` below). The caller loops the actual per-role
   * `DELETE /roles/{user_id}/{role}` calls itself, same division of
   * responsibility as `onToggleRole`. Omit to hide the Actions column
   * entirely (e.g. a future read-only rendering) — both current call sites
   * always supply it. */
  onRemoveAllAccess?: (userId: string) => void;
  /** Per-row "Convert inherited access to direct roles" (Actions column,
   * PR6) — called directly (no confirm step; additive, not destructive),
   * only ever offered for a member with at least one `forward_inherited`/
   * `member_source_inherited` source. The caller calls the new `POST
   * /{project_id}/materialize-inherited-access/{user_id}` endpoint and
   * refreshes `members` itself. Omit to hide the Actions column entirely. */
  onConvertToDirect?: (userId: string) => void;
  /** Caller-composed "add a member" control (`UserAutocomplete` + a role
   * `<select>`) — differs slightly per call site, so this table only
   * provides the slot. Omit for a read-only rendering. */
  addControl?: ReactNode;
  /** Accessible name for the table itself. */
  ariaLabel: string;
}) {
  const strings = useStrings();
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<ProjectRole | "">("");
  const [showInvited, setShowInvited] = useState(true);
  const [sort, setSort] = useState<SortState<SortKey> | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [confirmRemoveUserId, setConfirmRemoveUserId] = useState<string | null>(null);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search, roleFilter, showInvited]);

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
  const sortedMembers = sort
    ? [...filteredMembers].sort((a, b) => {
        const dir = sort.direction === "asc" ? 1 : -1;
        const av = sort.key === "name" ? a.display_name : a.email;
        const bv = sort.key === "name" ? b.display_name : b.email;
        return av.localeCompare(bv) * dir;
      })
    : filteredMembers;

  // Invited rows always render ahead of the sorted member rows rather than
  // interleaved into that sort order — same precedent Org Admin's own Users
  // table set for its "kind: user | invited" merge (there's no meaningful
  // name to sort an invited row by yet).
  const rows: Row[] = [
    ...filteredInvites.map((invite): Row => ({ kind: "invited", invite })),
    ...sortedMembers.map((member): Row => ({ kind: "member", member })),
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
      render: (row) => (row.kind === "member" ? row.member.display_name : <span className="text-muted">—</span>),
    },
    {
      key: "email",
      label: strings.membersTable.email,
      sortable: true,
      render: (row) => (row.kind === "member" ? row.member.email : row.invite.email),
    },
    {
      key: "role",
      label: strings.membersTable.role,
      render: (row) => {
        if (row.kind === "invited") {
          const invite = row.invite;
          return (
            <div className="row" style={{ gap: "0.4rem", alignItems: "center" }}>
              <span className="badge">{PENDING_INVITE_STATUS_LABEL[invite.status]}</span>
              <button
                className="btn"
                disabled={resendingInviteId === invite.id}
                onClick={() => onResendInvite(invite)}
                title={strings.admin.resendInviteAria(invite.email)}
                aria-label={strings.admin.resendInviteAria(invite.email)}
              >
                <Send size={14} /> {strings.admin.resendInvite}
              </button>
            </div>
          );
        }
        const member = row.member;
        return (
          <MultiSelectDropdown
            triggerLabel={strings.membersTable.rolesFor(member.display_name)}
            emptyLabel={strings.membersTable.noRoles}
            options={PROJECT_ROLES.map((role) => {
              const sourcesForRole = member.sources.filter((s) => s.role === role);
              const checked = sourcesForRole.length > 0;
              const kinds = new Set(sourcesForRole.map((s) => s.kind));
              const purelyDirect = checked && kinds.size === 1 && kinds.has("direct_role");
              const isLastManager = purelyDirect && role === "project_manager" && directRoleManagerCount <= 1;
              const disabled = checked && (!purelyDirect || isLastManager);
              const title = !disabled
                ? undefined
                : !purelyDirect
                  ? strings.membersTable.roleNotDirectlyRevocable
                  : strings.membersTable.cannotRemoveLastManager;
              return {
                value: role,
                label: PROJECT_ROLE_LABEL[role],
                checked,
                disabled,
                title,
                optionLabel: checked
                  ? strings.membersTable.revokeRole(PROJECT_ROLE_LABEL[role], member.display_name)
                  : strings.membersTable.grantRole(PROJECT_ROLE_LABEL[role], member.display_name),
                onToggle: () => onToggleRole(member.user_id, role, !checked),
              };
            })}
          />
        );
      },
    },
    {
      key: "source",
      label: strings.membersTable.source,
      render: (row) => {
        if (row.kind === "invited") {
          return (
            <span className="text-muted">
              {strings.membersTable.invitedSentOn(new Date(row.invite.created_at).toLocaleDateString())}
            </span>
          );
        }
        return (
          <div className="stack" style={{ gap: "0.15rem" }}>
            {row.member.sources.map((s, i) => (
              <span key={i} className="text-muted" style={{ fontSize: "0.85rem" }}>
                {sourceLine(strings, s)} ({PROJECT_ROLE_LABEL[s.role]})
              </span>
            ))}
          </div>
        );
      },
    },
  ];

  if (onRemoveAllAccess || onConvertToDirect) {
    columns.push({
      key: "actions",
      label: "",
      render: (row) => {
        if (row.kind === "invited") return null;
        const member = row.member;
        // "Remove all access" is only safe (and only offered) when every
        // source this member holds is a genuine, individually-revocable
        // `direct_role` row — the same "purely direct" test the Role
        // `MultiSelectDropdown` above already applies per-option, just
        // required across *all* of a member's held roles at once here:
        // if even one role were group-/inheritance-sourced, looping the
        // per-role DELETE over "currently-held direct roles" would leave
        // that other access silently in place while claiming to remove
        // "all" of it.
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
      {/* `FilterPanel` renders as a full-width bar ABOVE the table
          (`layout="top"`), not the standard `.side-grid` side layout —
          this table has 4 columns (Name, Email, Role, Source) with a
          multi-select role dropdown and per-source provenance text in the
          last column, wide enough that a 240px side sidebar visibly
          crowded it on both this component's call sites (follow-up UX
          fix; see docs/decisions.md and docs/ux-style-guide.md's "Pattern:
          filter panel placement — side vs. top"). */}
      <FilterPanel
        layout="top"
        sectionKey="projectMembersTableFilters"
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder={strings.membersTable.search}
      >
        <FilterField label={strings.membersTable.roleFilterLabel}>
          <select
            className="input"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value as ProjectRole | "")}
          >
            <option value="">{strings.membersTable.allRoles}</option>
            {PROJECT_ROLES.map((role) => (
              <option key={role} value={role}>
                {PROJECT_ROLE_LABEL[role]}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterCheckbox label={strings.membersTable.showInvited} checked={showInvited} onChange={setShowInvited} />
      </FilterPanel>
      <DirectoryTable
        ariaLabel={ariaLabel}
        columns={columns}
        rows={visible}
        rowKey={(row) => (row.kind === "member" ? `member-${row.member.user_id}` : `invited-${row.invite.id}`)}
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
