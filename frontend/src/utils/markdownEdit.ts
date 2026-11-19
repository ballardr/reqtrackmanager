/**
 * Module: utils/markdownEdit
 *
 * Pure text edits behind the Markdown editor's toolbar: given the text and the selection, return the new text and
 * the selection to restore. No DOM access, so every edit is testable on its own.
 *
 * Design decisions:
 * - Line formats (heading, lists, quotation) apply to every selected line and toggle off when all of them already
 *   carry the format. Inline formats wrap the selection, or insert a placeholder that is left selected.
 * - A block (code, table, diagram) always starts on its own line, so it is valid wherever the cursor was.
 */

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
