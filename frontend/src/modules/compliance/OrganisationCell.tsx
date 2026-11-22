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
 * unconditionally; the name is a `CellText` (two lines at most and 14rem wide in a table, one line in a fixed 10rem as a
 * label), so a long name never moves the columns and the full name is in a tooltip.
 */
import { CellText } from "../../components/CellText";

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
      <CellText lines={2} maxWidth="14rem">{name}</CellText>
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
    <span className="org-cell--label text-muted">
      <CellText>{name}</CellText>
    </span>
  );
}
