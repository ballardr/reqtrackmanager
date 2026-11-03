/**
 * Module: components/LayoutDiff
 *
 * A line-by-line comparison of two layout texts, as `diffLines` computes it: added and removed lines carry a
 * sign and a screen-reader word as well as a colour. Shared by the version history and the draft comparison.
 */
import { useStrings } from "../context/TerminologyContext";
import type { DiffLine } from "../utils/reportLayoutText";

/**
 * @param diff The lines to draw.
 * @param label The accessible name of the comparison.
 */
export function LayoutDiff({ diff, label }: { diff: DiffLine[]; label: string }) {
  const text = useStrings().reportLayouts;
  return (
    <pre className="layout-diff" aria-label={label}>
      {diff.map((line, index) => (
        <span key={index} className={`layout-diff-line${line.kind === "same" ? "" : ` layout-diff-line--${line.kind}`}`}>
          <span className="sr-only">{line.kind === "add" ? text.compareAdded : line.kind === "remove" ? text.compareRemoved : ""}</span>
          {line.kind === "add" ? "+ " : line.kind === "remove" ? "- " : "  "}
          {line.text}
        </span>
      ))}
    </pre>
  );
}
