/**
 * Module: components/MemberRoleTable
 *
 * The "add a user or group, then assign a role" shared table (Phase 5,
 * docs/decisions.md — project membership/groups redesign) — built entirely
 * from existing primitives (`SortableHeader`, `MultiSelectDropdown`,
 * `LoadMoreButton`), no new low-level machinery. Two call sites share this
 * exact component rather than each growing its own bespoke version:
 * `ProjectAdminPage.tsx`'s new "Members" section, and `OrgAdminPage.tsx`'s
 * "Manage users" modal (replacing that page's old inline expand-in-place
 * — see its own comment for what this removed).
 *
 * Responsibilities:
 * - Renders a searchable, `SortableHeader`-sortable table over a caller-
 *   supplied, already-merged `rows` array — a `kind: "user" | "group"`
 *   discriminated union (`MemberRoleRow`), matching the existing
 *   "Effective members" table shape and Org Admin's own Users table (style
 *   guide "Pattern: project-scoped member lists match Org Admin's Users
 *   table").
 * - The Role cell differs by row kind, deliberately (not an inconsistency
 *   to unify): a user row gets `MultiSelectDropdown` (`UserProjectRole` is
 *   genuinely multi-valued — a user can hold more than one direct role at
 *   once, unique on `(user_id, project_id, role)`, the same treatment
 *   `OrgRole` already gets on `OrgAdminPage.tsx`'s Users table); a group
 *   row gets a plain `<select className="input">` (`ProjectGroup.role` is
 *   one column, genuinely single-valued).
 * - `search` + a client-side "load more" window, per style guide "Pattern:
 *   directories at scale" — `rows` itself is expected to already be fully
 *   loaded (both call sites merge an unpaginated `GET .../groups` with an
 *   unpaginated `GET .../direct-members`, the same "small enough to load
 *   whole, search/paginate client-side" precedent `GET .../effective-
 *   members` already established), so this component's own pagination is a
 *   progressively-revealed window over an already-in-memory array, not a
 *   fresh network request per page.
 * - A fast, client-side "last manager" hint (disabled + `title`) on the
 *   role control for whichever row is this table's *only* row currently
 *   granting `project_manager` — mirrors `MultiSelectDropdown`'s existing
 *   self-role-revoke treatment on `OrgAdminPage.tsx`. This is an
 *   approximation only (it can't see forward-inherited managers from a
 *   parent {project}, for instance) — the backend's own C-U-08 guard on
 *   every mutating endpoint this table calls into is what's actually
 *   authoritative; this hint just avoids a round-trip for the common case.
 *
 * Does not fetch, mutate, or own any data itself: every callback
 * (`onToggleUserRole`, `onChangeGroupRole`) is the caller's own API call,
 * and `addControl` is a caller-supplied slot (composing `UserAutocomplete`
 * + a role `<select>`) since what can be added differs slightly per call
 * site (a project's own Members page can add any org member directly; the
 * Org Admin modal's add flow is identical but scoped to one project chosen
 * from Org Admin's own project list).
 */
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import type { ProjectRole } from "../api/types";
import { PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { LoadMoreButton } from "./LoadMoreButton";
import { MultiSelectDropdown } from "./MultiSelectDropdown";
import { cycleSort, SortableHeader, type SortState } from "./SortableHeader";

const PROJECT_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder", "member"];
const PAGE_SIZE = 20;

export interface MemberRoleUserRow {
  kind: "user";
  id: string;
  name: string;
  email: string;
  /** Genuinely multi-valued — see this module's own docstring. */
  roles: ProjectRole[];
}

export interface MemberRoleGroupRow {
  kind: "group";
  id: string;
  name: string;
  email: null;
  role: ProjectRole;
  memberCount: number;
  isDefault: boolean;
}

export type MemberRoleRow = MemberRoleUserRow | MemberRoleGroupRow;

type SortKey = "name" | "email";

export function MemberRoleTable({
  rows,
  onToggleUserRole,
  onChangeGroupRole,
  groupHref,
  addControl,
  ariaLabel,
}: {
  rows: MemberRoleRow[];
  /** Grants `role` to the user when `checked` is true, revokes it otherwise. */
  onToggleUserRole: (userId: string, role: ProjectRole, checked: boolean) => void;
  onChangeGroupRole: (groupId: string, role: ProjectRole) => void;
  /** Builds the URL a group row's name links to (its own Groups-page detail
   * panel) — omit to render group names as plain, non-clickable text (no
   * equivalent destination exists, e.g. from a context with no Groups page
   * of its own). */
  groupHref?: (groupId: string) => string;
  /** Caller-composed "add a member" control (`UserAutocomplete` + a role
   * `<select>`) — differs slightly per call site, so this table only
   * provides the slot. Omit for a read-only rendering. */
  addControl?: ReactNode;
  /** Accessible name for the search input and the table itself. */
  ariaLabel: string;
}) {
  const strings = useStrings();
  const [search, setSearch] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [sort, setSort] = useState<SortState<SortKey> | null>(null);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search]);

  const needle = search.trim().toLowerCase();
  const filtered = needle
    ? rows.filter((r) => r.name.toLowerCase().includes(needle) || (r.email ?? "").toLowerCase().includes(needle))
    : rows;
  const sorted = sort
    ? [...filtered].sort((a, b) => {
        const dir = sort.direction === "asc" ? 1 : -1;
        const av = sort.key === "name" ? a.name : (a.email ?? "");
        const bv = sort.key === "name" ? b.name : (b.email ?? "");
        return av.localeCompare(bv) * dir;
      })
    : filtered;
  const visible = sorted.slice(0, visibleCount);

  // Client-side "last manager" hint (see module docstring) — the number of
  // rows currently granting project_manager at all. A row is this table's
  // sole manager source only if it grants the role and this count is 1.
  const managerSourceCount = rows.filter((r) =>
    r.kind === "user" ? r.roles.includes("project_manager") : r.role === "project_manager"
  ).length;

  function applySort(key: SortKey) {
    setSort((current) => cycleSort(current, key));
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
        <input
          className="input"
          style={{ maxWidth: 320 }}
          placeholder={strings.memberRoleTable.search}
          aria-label={ariaLabel}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {addControl}
      </div>
      {sorted.length === 0 ? (
        <p className="text-muted">{needle ? strings.memberRoleTable.noResults : strings.memberRoleTable.empty}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table aria-label={ariaLabel}>
            <thead>
              <tr>
                {/* No natural order (two unordered categories) — plain
                    `<th>`, not `SortableHeader`, per style guide "Pattern:
                    sortable column header"'s own "sortable columns are the
                    obvious ones only" rule. */}
                <th>{strings.memberRoleTable.type}</th>
                <SortableHeader label={strings.memberRoleTable.name} sortKey="name" sort={sort} onSort={applySort} />
                <SortableHeader label={strings.memberRoleTable.email} sortKey="email" sort={sort} onSort={applySort} />
                <th>{strings.memberRoleTable.role}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={`${row.kind}-${row.id}`}>
                  <td>
                    <span className="badge">{row.kind === "user" ? strings.memberRoleTable.typeUser : strings.memberRoleTable.typeGroup}</span>
                  </td>
                  <td>
                    {row.kind === "group" && groupHref ? (
                      // No `aria-label` here deliberately (same reasoning as
                      // `SortableHeader`'s own comment): the link's visible
                      // text already is the group's name, so an aria-label
                      // would silently replace it as the accessible name for
                      // assistive tech and any `getByRole("cell"|"link",
                      // { name })` query alike.
                      <Link to={groupHref(row.id)} title={strings.memberRoleTable.viewGroupMembers(row.name)}>
                        {row.name}
                      </Link>
                    ) : (
                      row.name
                    )}
                  </td>
                  <td>
                    {row.kind === "user" ? row.email : strings.memberRoleTable.groupMemberCount(row.memberCount)}
                  </td>
                  <td>
                    {row.kind === "user" ? (
                      <MultiSelectDropdown
                        triggerLabel={strings.memberRoleTable.rolesFor(row.name)}
                        emptyLabel={strings.memberRoleTable.noRoles}
                        options={PROJECT_ROLES.map((role) => {
                          const checked = row.roles.includes(role);
                          const disabled = checked && role === "project_manager" && managerSourceCount <= 1;
                          return {
                            value: role,
                            label: PROJECT_ROLE_LABEL[role],
                            checked,
                            disabled,
                            title: disabled ? strings.memberRoleTable.cannotRemoveLastManager : undefined,
                            optionLabel: checked
                              ? strings.memberRoleTable.revokeRole(PROJECT_ROLE_LABEL[role], row.name)
                              : strings.memberRoleTable.grantRole(PROJECT_ROLE_LABEL[role], row.name),
                            onToggle: () => onToggleUserRole(row.id, role, !checked),
                          };
                        })}
                      />
                    ) : (
                      (() => {
                        const disabled = row.role === "project_manager" && managerSourceCount <= 1;
                        return (
                          <select
                            className="input"
                            aria-label={strings.memberRoleTable.groupRoleSelectLabel(row.name)}
                            value={row.role}
                            disabled={disabled}
                            title={disabled ? strings.memberRoleTable.cannotRemoveLastManager : undefined}
                            onChange={(e) => onChangeGroupRole(row.id, e.target.value as ProjectRole)}
                          >
                            {PROJECT_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {PROJECT_ROLE_LABEL[role]}
                              </option>
                            ))}
                          </select>
                        );
                      })()
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMoreButton loaded={visible.length} total={sorted.length} onClick={() => setVisibleCount((n) => n + PAGE_SIZE)} />
    </div>
  );
}
