/**
 * Module: components/HelpHeader
 *
 * A table column header that names a domain term and carries its plain-language help: the `<th>` with the
 * column's text and a `(?)` (`FieldHelp`) after it. Table headers are not form fields, so this is the one
 * shape for "a column that needs explaining" (docs/ux-style-guide.md, "Pattern: field help"); a column
 * whose text is self-explanatory stays a plain `<th>`, and a sortable column uses `SortableHeader`.
 *
 * Design decisions: the help is a pinnable tooltip (`FieldHelp`), so opening it never moves the table's
 * columns, and its button is named "Help: {label}" like every other `(?)`.
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
