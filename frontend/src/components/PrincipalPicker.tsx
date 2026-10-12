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
 */
import type { OrgUser, Principal, PrincipalRef, PrincipalType } from "../api/types";
import { usePrincipalDirectory } from "../hooks/usePrincipalDirectory";
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
}) {
  const { orgGroups, projectGroups } = usePrincipalDirectory(organizationId, projectId, kinds);
  const shown = value ? (display ?? resolve(value, orgUsers, orgGroups, projectGroups)) : null;
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
      <UserAutocomplete
        users={kinds.includes("user") ? orgUsers : []}
        organizationId={kinds.includes("user") ? organizationId : undefined}
        projectId={projectId}
        placeholder={placeholder}
        ariaLabel={ariaLabel}
        onSelect={(id) => onChange({ type: "user", id })}
        groups={kinds.includes("org_group") ? orgGroups : undefined}
        onSelectGroup={(id) => onChange({ type: "org_group", id })}
        projectGroups={kinds.includes("project_group") ? projectGroups : undefined}
        onSelectProjectGroup={(id) => onChange({ type: "project_group", id })}
      />
    </div>
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
