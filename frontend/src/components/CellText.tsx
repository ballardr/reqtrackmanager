/**
 * Module: components/CellText
 *
 * The one way a grid cell, table cell, list row or card shows text a person typed. A layout must never take its
 * shape from user text; `CellText` keeps the text inside its own cell: one line cut with an ellipsis (default) or
 * a clamp of `lines` lines, an unbroken word broken (`overflow-wrap: anywhere`), and the full text in a `Tooltip`
 * only while it is clipped (or always, when a `detail` line is given).
 *
 * The element is `min-width: 0` and flexes (`flex: 0 1 auto`), so beside a control it gives way and the control
 * keeps its size and line. It never holds controls. The text must be a string so the tooltip can carry it. A table
 * column sized from its content never narrows below a one-line text, so a table cell uses `lines` of two or more
 * and, for a narrow column, `maxWidth`.
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
 * @param detail A line the tooltip always shows beneath the text (what the text is, such as a group's kind and size).
 * @param className Extra class for the text element (a colour or size utility, for example `text-muted`).
 * @param style Extra style for the text element.
 */
export function CellText({
  children, lines = 1, maxWidth, detail, className, style,
}: {
  children: string; lines?: number; maxWidth?: string; detail?: string; className?: string; style?: CSSProperties;
}) {
  const [ref, clipped] = useIsClipped<HTMLSpanElement>();

  const clamp = lines > 1;
  const classes = ["cell-text", clamp ? "cell-text--clamp" : "", className ?? ""].filter(Boolean).join(" ");
  const tooltip = [clipped ? children : "", detail ?? ""].filter(Boolean).join("\n");
  return (
    <Tooltip label={tooltip} wrap disabled={tooltip === ""} className="cell-text-trigger" style={maxWidth ? { maxWidth } : undefined}>
      <span ref={ref} className={classes} style={clamp ? ({ ...style, "--cell-text-lines": lines } as CSSProperties) : style}>
        {children}
      </span>
    </Tooltip>
  );
}
