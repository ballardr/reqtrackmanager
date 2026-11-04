/**
 * Module: components/TableHeadingColours
 *
 * The control for a document layout's default table heading colours: the heading row's fill, its text colour and a small
 * sample heading row showing the result.
 *
 * Responsibilities:
 * - Draw the two shared colour fields (`ColourChoiceField`, so the layout's scheme names are offered) and report both words
 *   together; an empty word is "default" (the fill the organisation's accent, the text automatic).
 * - Draw the sample the way the renderers colour a heading row (`utils/tableHeadingColours`): the fill, else the accent;
 *   the text colour, else black or white by contrast with the fill.
 * - One component for the Blocks view's layout panel and the text view's page setup dialog, so both places agree.
 *
 * Design decisions: "No colour" is not offered; a heading row always has a fill, and a table that wants none says so in its
 * own cells. Changes apply as they are made.
 */
import { useStrings } from "../context/TerminologyContext";
import { tableHeadingColours } from "../utils/tableHeadingColours";
import { DEFAULT_COLOUR_CONTEXT, type ColourContext, type ColourEntry } from "../utils/reportColours";
import type { TableHeadings } from "../utils/reportPageSetup";
import { ColourChoiceField } from "./ColourChoiceField";

/**
 * @param value The layout's two colour words (a word left out is the default).
 * @param onChange Called with both words after a change; a cleared word is omitted.
 * @param colours The branding colour and the organisation's colour scheme.
 * @param palette The layout's own colour scheme.
 * @param disabled Read-only.
 * @param problems The server's messages about either colour, shown under the control.
 */
export function TableHeadingColours({
  value, onChange, colours = DEFAULT_COLOUR_CONTEXT, palette = [], disabled = false, problems = [],
}: {
  value: TableHeadings;
  onChange: (next: TableHeadings) => void;
  colours?: ColourContext;
  palette?: ColourEntry[];
  disabled?: boolean;
  problems?: string[];
}) {
  const strings = useStrings();
  const text = strings.tableHeadings;
  const shown = tableHeadingColours(value, colours, palette);
  const set = (key: keyof TableHeadings) => (word: string) => onChange({ ...value, [key]: word === "" ? undefined : word });
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div className="row" style={{ alignItems: "flex-start", gap: "var(--space-3)" }}>
        <ColourChoiceField
          label={text.fillLabel} help={strings.help.layoutTableHeadingFill} value={value.fill ?? ""} disabled={disabled}
          context={colours} layoutPalette={palette} allowNone={false} emptyLabel={text.fillDefault} onChange={set("fill")}
        />
        <ColourChoiceField
          label={text.textLabel} help={strings.help.layoutTableHeadingText} value={value.text ?? ""} disabled={disabled}
          context={colours} layoutPalette={palette} allowNone={false} emptyLabel={text.textDefault} onChange={set("text")}
        />
      </div>
      <table className="table-heading-sample" aria-label={text.sampleLabel}>
        <thead>
          <tr>{Object.values(text.sampleCells).map((cell) => <th key={cell} style={{ background: shown.fill, color: shown.text }}>{cell}</th>)}</tr>
        </thead>
        <tbody>
          <tr>{Object.values(text.sampleCells).map((cell) => <td key={cell}>{text.sampleBody}</td>)}</tr>
        </tbody>
      </table>
      {problems.length > 0 && (
        <ul className="outline-field-problems" role="alert">{problems.map((message) => <li key={message}>{message}</li>)}</ul>
      )}
    </div>
  );
}
