/**
 * Module: modules/compliance/OrganisationCell
 *
 * How a Compliance status row states its organisation when the tab reads more than one organisation, so a row
 * never leaves its organisation unstated. Shared by the By standard and Outstanding tabs.
 *
 * Responsibilities:
 * - `OrganisationHeader` / `OrganisationCell`: the Organisation column of a table, left-aligned at the same place
 *   in every row.
 * - `OrganisationLabel`: the muted label that leads an item of a list written as a sentence (Outstanding), so its
 *   position never depends on the length or wrapping of the text after it.
 *
 * Design decisions: each renders nothing when the tab reads a single organisation, so callers place it
 * unconditionally; the name never wraps and is cut with an ellipsis past `.org-cell`'s width, with the full name
 * in a tooltip.
 */
import { Tooltip } from "../../components/Tooltip";

/**
 * @param show Whether the tab reads more than one organisation (`ComplianceStatusFrame.showOrg`).
 */
export function OrganisationHeader({ show }: { show: boolean }) {
  if (!show) return null;
  return <th>Organisation</th>;
}

/**
 * @param name The organisation's name.
 * @param show Whether the tab reads more than one organisation (`ComplianceStatusFrame.showOrg`).
 */
export function OrganisationCell({ name, show }: { name: string; show: boolean }) {
  if (!show) return null;
  return (
    <td>
      <Tooltip label={name}>
        <span className="org-cell">{name}</span>
      </Tooltip>
    </td>
  );
}

/**
 * @param name The organisation's name.
 * @param show Whether the tab reads more than one organisation (`ComplianceStatusFrame.showOrg`).
 */
export function OrganisationLabel({ name, show }: { name: string; show: boolean }) {
  if (!show) return null;
  return (
    <Tooltip label={name}>
      <span className="org-cell org-cell--label text-muted">{name}</span>
    </Tooltip>
  );
}
