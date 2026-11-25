/**
 * Module: utils/markdownEdit
 *
 * Pure text edits behind the Markdown editor's toolbar: given the text and the
 * selection, return the new text and the selection to restore (no DOM access).
 * Design: line formats (heading, lists, quotation) apply to every selected line
 * and toggle off when all already carry the format; inline formats wrap the
 * selection or insert a selected placeholder; a block (code, table, diagram,
 * display equation) always starts on its own line.
 */

import { pictureMarkdown } from "./markdownPicture";
import { equationMarkdown } from "./visualMathNode";

export type MarkdownFormat =
  | "bold" | "italic" | "heading" | "bulleted" | "numbered" | "quote" | "code" | "link" | "table" | "diagram";

export interface EditResult {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

export const DIAGRAM_TEMPLATE = "flowchart LR\n  A[Start] --> B[End]";
const TABLE_TEMPLATE = "| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |";

function wrap(value: string, start: number, end: number, mark: string, placeholder: string): EditResult {
  const selected = value.slice(start, end);
  if (selected.startsWith(mark) && selected.endsWith(mark) && selected.length >= mark.length * 2) {
    const inner = selected.slice(mark.length, selected.length - mark.length);
    return { value: value.slice(0, start) + inner + value.slice(end), selectionStart: start, selectionEnd: start + inner.length };
  }
  const text = selected || placeholder;
  return {
    value: `${value.slice(0, start)}${mark}${text}${mark}${value.slice(end)}`,
    selectionStart: start + mark.length,
    selectionEnd: start + mark.length + text.length,
  };
}

function prefixLines(value: string, start: number, end: number, prefix: (index: number) => string, pattern: RegExp): EditResult {
  const from = value.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = value.indexOf("\n", end);
  const to = lineEnd === -1 ? value.length : lineEnd;
  const lines = value.slice(from, to).split("\n");
  const allHave = lines.every((line) => pattern.test(line));
  const next = lines.map((line, i) => (allHave ? line.replace(pattern, "") : `${prefix(i)}${line.replace(pattern, "")}`));
  const block = next.join("\n");
  return { value: value.slice(0, from) + block + value.slice(to), selectionStart: from, selectionEnd: from + block.length };
}

function insertBlock(value: string, start: number, end: number, body: string, select: [number, number]): EditResult {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const lead = before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const trail = after === "" || after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
  const head = before + lead;
  return { value: head + body + trail + after, selectionStart: head.length + select[0], selectionEnd: head.length + select[1] };
}

/**
 * @param value The current text.
 * @param start Selection start (a character offset).
 * @param end Selection end.
 * @param format The format to apply.
 * @returns The new text and selection.
 */
export function applyMarkdownFormat(value: string, start: number, end: number, format: MarkdownFormat): EditResult {
  switch (format) {
    case "bold": return wrap(value, start, end, "**", "bold text");
    case "italic": return wrap(value, start, end, "_", "italic text");
    case "heading": return prefixLines(value, start, end, () => "## ", /^#{1,6}\s+/);
    case "bulleted": return prefixLines(value, start, end, () => "- ", /^[-*]\s+/);
    case "numbered": return prefixLines(value, start, end, (i) => `${i + 1}. `, /^\d+[.)]\s+/);
    case "quote": return prefixLines(value, start, end, () => "> ", /^>\s?/);
    case "link": {
      const label = value.slice(start, end) || "link text";
      const text = `[${label}](https://)`;
      const urlStart = start + label.length + 3;
      return { value: value.slice(0, start) + text + value.slice(end), selectionStart: urlStart, selectionEnd: urlStart + "https://".length };
    }
    case "code": {
      const body = value.slice(start, end) || "code";
      const text = `\`\`\`\n${body}\n\`\`\``;
      return insertBlock(value, start, end, text, [4, 4 + body.length]);
    }
    case "table": return insertBlock(value, start, end, TABLE_TEMPLATE, [2, 10]);
    case "diagram": {
      const body = value.slice(start, end) || DIAGRAM_TEMPLATE;
      return insertBlock(value, start, end, `\`\`\`mermaid\n${body}\n\`\`\``, [11, 11 + body.length]);
    }
  }
}

/**
 * Replaces the selection with an equation: an inline equation in place, a display equation as its own paragraph.
 *
 * @param value The current text.
 * @param start Selection start (a character offset).
 * @param end Selection end.
 * @param tex The equation's TeX (a line break in it is a space, so no line of the text starts with TeX).
 * @param display Whether it is a display equation.
 * @returns The new text, with the cursor after the equation.
 */
export function insertMarkdownMath(value: string, start: number, end: number, tex: string, display: boolean): EditResult {
  const source = equationMarkdown(tex.trim().replace(/\s*\n\s*/g, " "), display);
  if (display) return insertBlock(value, start, end, source, [source.length, source.length]);
  const next = value.slice(0, start) + source + value.slice(end);
  return { value: next, selectionStart: start + source.length, selectionEnd: start + source.length };
}

/**
 * Replaces the selection with a picture of the record's own attachment, as a paragraph of its own.
 *
 * @param value The current text.
 * @param start Selection start (a character offset).
 * @param end Selection end.
 * @param picture The attachment's file id and the picture's alternative text and caption.
 * @returns The new text, with the cursor after the picture.
 */
export function insertMarkdownPicture(
  value: string, start: number, end: number, picture: { fileId: string; alt: string; caption: string },
): EditResult {
  const source = pictureMarkdown(picture.fileId, picture.alt, picture.caption);
  return insertBlock(value, start, end, source, [source.length, source.length]);
}
