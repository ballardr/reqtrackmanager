/**
 * Module: components/MarkdownSummary
 *
 * The summary of a Markdown text in a card, tile or list cell: its words without marks and its equations drawn.
 * Headings, lists, links, pictures and tables lose their marks (a diagram is `[Diagram]`), so a clamped card keeps
 * its shape; an equation, which cannot be read from its words, is drawn with `MathEquation` inline in the flow, a
 * display equation (`$$ x $$`) at inline size.
 *
 * Reads the same tokens as `markdownPlainText` (`utils/markdownPlain.markdownSummaryParts`), so the two cannot
 * disagree about what is text. The text is clamped by `CellText` (`lines`, default 3), whose tooltip holds the plain
 * words, never markup. A text longer than `SUMMARY_LIMIT` characters is cut before it is drawn, so a very long
 * description does not build a long element list that the clamp then hides.
 *
 * Use it only on screen; a native tooltip, toast, notification, search snippet or export stays a plain string from
 * `markdownPlainText`.
 *
 * Dependencies: `CellText`, `MathEquation`, `utils/markdownPlain`.
 */
import { useMemo, type CSSProperties } from "react";

import { markdownPlainText, markdownSummaryParts } from "../utils/markdownPlain";
import { CellText } from "./CellText";
import { MathEquation } from "./MathEquation";

/** The most characters of a text that are read and drawn. */
export const SUMMARY_LIMIT = 600;

/**
 * @param text The Markdown text, as stored.
 * @param math Read `\( x \)` and `$$ x $$` as equations (the fields people write mathematics in).
 * @param lines How many lines to allow before the text is clipped (default 3).
 * @param className Extra class for the text element (a colour utility such as `text-muted`).
 * @param style Extra style for the text element (a font size).
 */
export function MarkdownSummary({
  text, math = false, lines = 3, className, style,
}: {
  text: string; math?: boolean; lines?: number; className?: string; style?: CSSProperties;
}) {
  const parts = useMemo(() => markdownSummaryParts(text, { math, limit: SUMMARY_LIMIT }), [text, math]);
  const plain = useMemo(() => markdownPlainText(text, { math, limit: SUMMARY_LIMIT }), [text, math]);
  if (parts.length === 0) return null;
  return (
    <CellText lines={lines} plain={plain} className={["markdown-summary", className ?? ""].filter(Boolean).join(" ")} style={style}>
      {parts.map((part, index) =>
        part.kind === "text" ? <span key={index}>{part.value}</span> : <MathEquation key={index} tex={part.tex} display={false} />)}
    </CellText>
  );
}
