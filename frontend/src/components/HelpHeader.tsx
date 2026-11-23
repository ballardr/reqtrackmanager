/**
 * Module: components/HelpHeader
 *
 * A table column header that names a domain term and carries its help: the `<th>` with the column's text and a
 * `(?)` (`FieldHelp`), the one shape for "a column that needs explaining" (docs/ux-style-guide.md, "Pattern: field
 * help"). A self-explanatory column stays a plain `<th>`; a sortable one uses `SortableHeader`. The help is a
 * pinnable tooltip, so opening it never moves the columns, and its button is named "Help: {label}".
 */
import { FieldHelp } from "./FieldHelp";

/**
 * @param label The column's visible text; it also names the help button.
 * @param help One or two plain-language sentences saying what the column shows.
 */
export function HelpHeader({ label, help }: { label: string; help: string }) {
  return (
    <th scope="col">
      <span className="field-caption" style={{ flexWrap: "nowrap", whiteSpace: "nowrap" }}>
        <span>{label}</span>
        <FieldHelp label={label} help={help} />
      </span>
    </th>
  );
}
