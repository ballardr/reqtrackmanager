/**
 * Module: modules/compliance/OrganisationCell
 *
 * How a Compliance status row states its organisation when the tab reads more than one, shared by the By standard and
 * Outstanding tabs. `OrganisationHeader` / `OrganisationCell` are the left-aligned Organisation column of a table;
 * `OrganisationLabel` is the muted label leading an item of a list written as a sentence (Outstanding), so its position never
 * depends on the text after it. Each renders nothing for a single organisation, so callers place it unconditionally; the name is
 * a `CellText` (two lines and 14rem wide in a table, one line in a fixed 10rem as a label) so a long name never moves the
 * columns and the full name is in a tooltip.
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
