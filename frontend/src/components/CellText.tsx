/**
 * Module: components/CellText
 *
 * The one way a grid cell, table cell, list row or card shows text a person typed (a name, a summary, a
 * description, a code). A layout must never take its shape from user text: a long name that widens its
 * column, or a long description that wraps and pushes the controls beside it onto a new line, is found by
 * whoever has the longest data. `CellText` keeps the text inside its own cell.
 *
 * Responsibilities:
 * - One line cut with an ellipsis (default), or a clamp of `lines` lines, never taller than that.
 * - Break an unbroken word (`overflow-wrap: anywhere`) so it cannot widen a column.
 * - Show the full text in a `Tooltip` only while the text is actually clipped.
 *
 * Design decisions: the element is `min-width: 0` and flexes (`flex: 0 1 auto`), so beside a control in a flex
 * row or a grid track it gives way and the control keeps its size and its line. It never holds controls: put a
 * button beside it, not inside it. The text must be a string so the tooltip can carry it. A table column sized
 * from its content never gets narrower than a one-line text, so in a table cell use `lines` of two or more
 * (the clamp may break anywhere, so the column can give way) and, for a column that should stay narrow,
 * `maxWidth`.
 *
 * Dependencies: `Tooltip`, `useIsClipped`; the `.cell-text*` rules in `styles/theme.css`.
 */
import type { CSSProperties } from "react";

import { useIsClipped } from "../hooks/useIsClipped";
import { Tooltip } from "./Tooltip";

/**
 * Text that stays inside its cell.
 *
 * @param children The text to show (a string, so the tooltip can repeat it in full).
 * @param lines How many lines to allow before clipping (default 1, a single line with an ellipsis).
 * @param maxWidth A cap on the text's width (a CSS length such as `14rem`); a short text keeps its own width.
 * @param className Extra class for the text element (a colour or size utility, for example `text-muted`).
 * @param style Extra style for the text element.
 */
export function CellText({
  children, lines = 1, maxWidth, className, style,
}: {
  children: string; lines?: number; maxWidth?: string; className?: string; style?: CSSProperties;
}) {
  const [ref, clipped] = useIsClipped<HTMLSpanElement>();

  const clamp = lines > 1;
  const classes = ["cell-text", clamp ? "cell-text--clamp" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <Tooltip
      label={children} wrap disabled={!clipped} className="cell-text-trigger" style={maxWidth ? { maxWidth } : undefined}
    >
      <span ref={ref} className={classes} style={clamp ? ({ ...style, "--cell-text-lines": lines } as CSSProperties) : style}>
        {children}
      </span>
    </Tooltip>
  );
}
