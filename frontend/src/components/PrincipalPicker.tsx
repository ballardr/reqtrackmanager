/**
 * Module: components/PrincipalPicker
 *
 * The one control for a field that names "who": a user, an organisation group or a project group
 * (users and groups on parity). It shows the current value (a `PrincipalBadge`, or the empty text),
 * a compact `ClearButton` X straight after it while one is set, and a `UserAutocomplete` search that
 * also matches groups, each option tagged with its kind, all on one line: the badge and the X keep
 * their size and the search takes the remaining width, so the row is the same height whether or not
 * a value is set. The search box says what it does ("Search users and groups…", from the kinds the
 * field allows); `emptyLabel` is what an empty value is called ("Unassigned", or "Defaults to you").
 * It replaces the user-only `AssigneePicker`; a field that cannot name a group yet passes
 * `kinds={["user"]}` and makes no group requests.
 *
 * Group lists come from `usePrincipalDirectory`; user search is `UserAutocomplete`'s (server-side
 * when `organizationId` is given). The current value's label is resolved from whatever is loaded,
 * or taken from `display` when the record already carries it (use that for a group the viewer
 * cannot list).
 *
 * `compact` collapses the always-open search box into a (+) button (a pencil once someone is
 * assigned) that opens it in a `Popover`: one short line per field, for detail pages with several
 * (docs/ux-style-guide.md, "Pattern: compact forms and add-on-demand"). The clear control is the
 * same X in both forms ("Pattern: clear control").
 */
import { Pencil } from "lucide-react";

import type { OrgGroup, OrgUser, Principal, PrincipalRef, PrincipalType, ProjectGroup } from "../api/types";
import { usePrincipalDirectory } from "../hooks/usePrincipalDirectory";
import { t } from "../i18n/strings";
import { AddPopoverButton } from "./AddPopoverButton";
import { ClearButton } from "./ClearButton";
import { PrincipalBadge } from "./PrincipalBadge";
import { UserAutocomplete } from "./UserAutocomplete";

const strings = t();

const ALL_KINDS: readonly PrincipalType[] = ["user", "org_group", "project_group"];

/**
 * The search box's prompt for the kinds a field allows.
 *
 * @param kinds The principal kinds the field may name.
 * @returns "Search users…", "Search groups…" or "Search users and groups…".
 */
function principalSearchPrompt(kinds: readonly PrincipalType[]): string {
  const users = kinds.includes("user");
  const groups = kinds.includes("org_group") || kinds.includes("project_group");
  if (users && groups) return strings.common.searchUsersAndGroups;
  return groups ? strings.common.searchGroups : strings.common.searchUsers;
}

export function PrincipalPicker({
  orgUsers,
  organizationId,
  projectId,
  value,
  display,
  onChange,
  ariaLabel,
  emptyLabel = strings.common.unassigned,
  kinds = ALL_KINDS,
  clearLabel = strings.common.clear,
  compact = false,
}: {
  orgUsers: OrgUser[];
  /** Enables server-side user search and organisation-group listing. */
  organizationId?: string;
  /** Enables project-group listing (and scopes the user search to the project). */
  projectId?: string;
  value: PrincipalRef | null | undefined;
  /** The record's own resolved view of `value`; preferred over looking it up. */
  display?: Principal | null;
  /** Called with the picked principal, or null when cleared. */
  onChange: (principal: PrincipalRef | null) => void;
  /** Accessible name for the search input and the clear control; distinct per instance (e.g. one per list row). */
  ariaLabel: string;
  /** What an empty value is called (shown in place of the badge), e.g. "Defaults to you". */
  emptyLabel?: string;
  /** The principal kinds this field may name. */
  kinds?: readonly PrincipalType[];
  /** The clear control's accessible name and tooltip, followed by the field name ("Clear: Owner"). */
  clearLabel?: string;
  /** Show the value with a (+)/pencil button instead of an always-open search box. */
  compact?: boolean;
}) {
  const { orgGroups, projectGroups } = usePrincipalDirectory(organizationId, projectId, kinds);
  const shown = value ? (display ?? resolve(value, orgUsers, orgGroups, projectGroups)) : null;
  const search = (afterSelect: () => void) => (
    <PrincipalSearch
      orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} kinds={kinds}
      orgGroups={orgGroups} projectGroups={projectGroups} ariaLabel={ariaLabel}
      onPick={(ref) => { onChange(ref); afterSelect(); }}
    />
  );
  const clear = value && <ClearButton label={`${clearLabel}: ${ariaLabel}`} onClick={() => onChange(null)} />;
  if (compact) {
    return (
      <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        <PrincipalBadge principal={shown} placeholder={emptyLabel} />
        <AddPopoverButton label={`${value ? "Change" : "Assign"}: ${ariaLabel}`} icon={value ? Pencil : undefined}>
          {(close) => search(close)}
        </AddPopoverButton>
        {clear}
      </div>
    );
  }
  return (
    <div className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap" }}>
      <PrincipalBadge principal={shown} placeholder={emptyLabel} />
      {clear}
      <div style={{ flex: "1 1 8rem", minWidth: 0 }}>{search(() => {})}</div>
    </div>
  );
}

/**
 * The search box on its own: one input that finds a user, an organisation group or a project group
 * (whichever `kinds` allow) and reports the pick. `PrincipalPicker` wraps it with the current value;
 * `PrincipalListField` uses it to add to a list. The caller loads the group lists
 * (`usePrincipalDirectory`).
 *
 * @param orgGroups / projectGroups The groups to offer (empty for a kind the field does not allow).
 * @param onPick Called with the chosen principal.
 */
export function PrincipalSearch({
  orgUsers, organizationId, projectId, kinds = ALL_KINDS, orgGroups, projectGroups, placeholder, ariaLabel, onPick,
}: {
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  kinds?: readonly PrincipalType[];
  orgGroups: OrgGroup[];
  projectGroups: ProjectGroup[];
  placeholder?: string;
  ariaLabel: string;
  onPick: (principal: PrincipalRef) => void;
}) {
  return (
    <UserAutocomplete
      users={kinds.includes("user") ? orgUsers : []}
      organizationId={kinds.includes("user") ? organizationId : undefined}
      projectId={projectId}
      placeholder={placeholder ?? principalSearchPrompt(kinds)}
      ariaLabel={ariaLabel}
      onSelect={(id) => onPick({ type: "user", id })}
      groups={kinds.includes("org_group") ? orgGroups : undefined}
      onSelectGroup={(id) => onPick({ type: "org_group", id })}
      projectGroups={kinds.includes("project_group") ? projectGroups : undefined}
      onSelectProjectGroup={(id) => onPick({ type: "project_group", id })}
    />
  );
}

/** Best-effort display for a value when the record did not carry one. */
function resolve(
  value: PrincipalRef,
  users: OrgUser[],
  orgGroups: { id: string; name: string }[],
  projectGroups: { id: string; name: string }[],
): Principal {
  if (value.type === "user") {
    const user = users.find((u) => u.user_id === value.id);
    return { ...value, label: user ? `${user.display_name} (${user.email})` : "Unknown user", member_count: null, exists: !!user };
  }
  const group = (value.type === "org_group" ? orgGroups : projectGroups).find((g) => g.id === value.id);
  return { ...value, label: group?.name ?? "Group", member_count: null, exists: true };
}
