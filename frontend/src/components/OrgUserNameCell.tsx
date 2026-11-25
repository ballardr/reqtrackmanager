/**
 * Module: components/OrgUserNameCell
 *
 * The Name cell of the organisation Users list: the display name, and for a service user the Service label and its
 * access-review flags. A service user's name is a button that opens its dialog (tokens, lifecycle); a person's name
 * is plain text.
 *
 * Design decisions:
 * - The name is `CellText`, so a long name gives way to the label and flags beside it instead of widening the column.
 * - The button uses the table's shared row-trigger style, so it reads like every other row that opens something.
 */
import type { OrgUser } from "../api/types";
import { CellText } from "./CellText";
import { ServiceBadge } from "./ServiceBadge";
import { ServiceUserFlags } from "./ServiceUserFlags";

/**
 * @param user The organisation user of the row.
 * @param onOpenServiceUser Called with the user's id when a service user's name is chosen.
 */
export function OrgUserNameCell({ user, onOpenServiceUser }: { user: OrgUser; onOpenServiceUser: (userId: string) => void }) {
  if (!user.is_service_account) return <CellText lines={2}>{user.display_name}</CellText>;
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap" }}>
      <button type="button" className="directory-table-row-trigger" style={{ minWidth: 0 }} onClick={() => onOpenServiceUser(user.user_id)}>
        <CellText lines={2}>{user.display_name}</CellText>
      </button>
      <span style={{ flex: "none" }}><ServiceBadge /></span>
      <ServiceUserFlags flags={user.service_flags ?? []} />
    </span>
  );
}
