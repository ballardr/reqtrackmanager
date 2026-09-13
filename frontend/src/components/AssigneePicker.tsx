/**
 * Module: components/AssigneePicker
 *
 * A single-user "who's assigned" field: the current assignee (or
 * "Unassigned"), an Unassign action shown only while someone is assigned,
 * and a `UserAutocomplete` search box to (re)assign — replacing a plain
 * unfiltered `<select>` mapping every org user to an `<option>` for this
 * exact shape (compliance-module-plan.md Phase 32: the report that such a
 * dropdown "won't scale past a handful of users" for
 * `RequirementAssessmentPanel.tsx`'s required-action assignee, and the same
 * defect independently present in `RequirementDetailPage.tsx`'s new-action
 * assignee).
 *
 * `UserAutocomplete` itself has no notion of a pre-filled current value —
 * it's a search-and-pick control that resets after each pick — so this
 * component is the pairing of that control with the current-value display
 * a single-assignee field still needs, kept as one shared component rather
 * than reimplementing the pairing at each call site (`docs/ux-style-guide.md`
 * "one component per pattern").
 */
import type { OrgUser } from "../api/types";
import { UserAutocomplete } from "./UserAutocomplete";

export function AssigneePicker({
  orgUsers,
  organizationId,
  assigneeId,
  onChange,
  ariaLabel,
  placeholder = "Assign to…",
}: {
  orgUsers: OrgUser[];
  /** Enables `UserAutocomplete`'s debounced server-side search — pass an
   * org's id when the caller already has one loaded (an org's user list
   * can be large); omit to filter `orgUsers` client-side instead. */
  organizationId?: string;
  assigneeId: string | null | undefined;
  onChange: (userId: string) => void;
  /** Accessible name for the search input — required, not optional, since
   * every current call site needs one distinct from any sibling instance
   * (e.g. one per row in a list). */
  ariaLabel: string;
  placeholder?: string;
}) {
  const assignee = orgUsers.find((u) => u.user_id === assigneeId);
  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
        <span>{assignee ? `${assignee.display_name} (${assignee.email})` : "Unassigned"}</span>
        {assignee && (
          <button type="button" className="btn" onClick={() => onChange("")} aria-label={`Unassign: ${ariaLabel}`}>
            Unassign
          </button>
        )}
      </div>
      <UserAutocomplete
        users={orgUsers}
        organizationId={organizationId}
        placeholder={placeholder}
        ariaLabel={ariaLabel}
        onSelect={onChange}
      />
    </div>
  );
}
