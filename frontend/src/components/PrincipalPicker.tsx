/**
 * Module: components/PrincipalPicker
 *
 * The one control for a field that names "who": a user, an organisation group or a project group
 * (users and groups on parity — docs/plans/users-and-groups-parity-plan.md). It shows the current
 * value (a `PrincipalBadge`, or "Unassigned"), an Unassign action while one is set, and a
 * `UserAutocomplete` search that also matches groups, each option tagged with its kind. It replaces
 * the user-only `AssigneePicker`; a field that cannot name a group yet passes `kinds={["user"]}`
 * and makes no group requests.
 *
 * Group lists come from `usePrincipalDirectory`; user search is `UserAutocomplete`'s (server-side
 * when `organizationId` is given). The current value's label is resolved from whatever is loaded,
 * or taken from `display` when the record already carries it (use that for a group the viewer
 * cannot list).
 *
 * `compact` collapses the always-open search box into a (+) button (a pencil once someone is
 * assigned) that opens it in a `Popover`, and turns "Unassign" into an "x": one short line per
 * field, for detail pages with several (docs/ux-style-guide.md, "Pattern: compact forms and
 * add-on-demand").
 */
import { Pencil, X } from "lucide-react";

import type { OrgGroup, OrgUser, Principal, PrincipalRef, PrincipalType, ProjectGroup } from "../api/types";
import { usePrincipalDirectory } from "../hooks/usePrincipalDirectory";
import { AddPopoverButton } from "./AddPopoverButton";
import { PrincipalBadge } from "./PrincipalBadge";
import { UserAutocomplete } from "./UserAutocomplete";

const ALL_KINDS: readonly PrincipalType[] = ["user", "org_group", "project_group"];

export function PrincipalPicker({
  orgUsers,
  organizationId,
  projectId,
  value,
  display,
  onChange,
  ariaLabel,
  placeholder = "Assign to…",
  kinds = ALL_KINDS,
  clearLabel = "Unassign",
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
  /** Called with the picked principal, or null when unassigned. */
  onChange: (principal: PrincipalRef | null) => void;
  /** Accessible name for the search input; distinct per instance (e.g. one per list row). */
  ariaLabel: string;
  placeholder?: string;
  /** The principal kinds this field may name. */
  kinds?: readonly PrincipalType[];
  /** Text of the action that empties the field (a replacement picker says "Clear"). */
  clearLabel?: string;
  /** Show the value with a (+)/pencil button instead of an always-open search box. */
  compact?: boolean;
}) {
  const { orgGroups, projectGroups } = usePrincipalDirectory(organizationId, projectId, kinds);
  const shown = value ? (display ?? resolve(value, orgUsers, orgGroups, projectGroups)) : null;
  const search = (afterSelect: () => void) => (
    <PrincipalSearch
      orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} kinds={kinds}
      orgGroups={orgGroups} projectGroups={projectGroups} placeholder={placeholder} ariaLabel={ariaLabel}
      onPick={(ref) => { onChange(ref); afterSelect(); }}
    />
  );
  if (compact) {
    return (
      <div className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
        <PrincipalBadge principal={shown} />
        <AddPopoverButton label={`${value ? "Change" : "Assign"}: ${ariaLabel}`} icon={value ? Pencil : undefined}>
          {(close) => search(close)}
        </AddPopoverButton>
        {value && (
          <button type="button" className="removable-item__remove" onClick={() => onChange(null)} aria-label={`${clearLabel}: ${ariaLabel}`} title={clearLabel}>
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
        <PrincipalBadge principal={shown} />
        {value && (
          <button type="button" className="btn" onClick={() => onChange(null)} aria-label={`${clearLabel}: ${ariaLabel}`}>
            {clearLabel}
          </button>
        )}
      </div>
      {search(() => {})}
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
  orgUsers, organizationId, projectId, kinds = ALL_KINDS, orgGroups, projectGroups, placeholder = "Assign to…", ariaLabel, onPick,
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
      placeholder={placeholder}
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
