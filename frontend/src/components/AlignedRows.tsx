/**
 * Module: components/AlignedRows
 *
 * A list of rows that each have a leading marker, a main text and trailing actions (move up, move
 * down, edit, delete), laid out in ONE grid so the action column lines up across every row however
 * long the text is (docs/ux-style-guide.md, "Pattern: compact forms and add-on-demand": controls that
 * repeat align). A row may also carry a detail line under its text. Rows are list items, so the list
 * keeps its semantics (use `ordered` for a numbered list).
 */
import type { ReactNode } from "react";

export interface AlignedRow {
  id: string;
  /** The leading marker, e.g. the row number. */
  lead?: ReactNode;
  /** The row's main text. */
  main: ReactNode;
  /** The trailing buttons; give every row the same set so the columns match. */
  actions?: ReactNode;
  /** A secondary line under the text (notes). */
  detail?: ReactNode;
}

/**
 * @param rows The rows.
 * @param ordered Render an `<ol>` rather than a `<ul>`.
 * @param ariaLabel Accessible name of the list.
 */
export function AlignedRows({ rows, ordered = false, ariaLabel }: { rows: AlignedRow[]; ordered?: boolean; ariaLabel?: string }) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag className="aligned-rows" aria-label={ariaLabel}>
      {rows.map((row) => (
        <li key={row.id}>
          <span>{row.lead}</span>
          <span>{row.main}</span>
          <span className="aligned-rows__actions">{row.actions}</span>
          {row.detail && <div className="aligned-rows__detail text-muted">{row.detail}</div>}
        </li>
      ))}
    </Tag>
  );
}
