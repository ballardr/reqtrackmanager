/**
 * Module: utils/reportLayoutText
 *
 * Pure helpers for the report layout designer's text editor; none of them knows the tree, only the text view's
 * line syntax (backend `services.report_layout_text`), so the server stays the one parser and these only help a
 * person write.
 *
 * Responsibilities:
 * - `aliasesInScope`: the `as` names a `{{alias.field}}` may use at a line (the enclosing `@each`/`@group`
 *   blocks), with the record type each one stands for so the field picker can offer that type's fields.
 * - `insertAt`: put a snippet at the caret or over the selection.
 * - `BLOCK_SNIPPETS`: starter text for each block type, per layout family.
 * - `widgetLine` and `placeholder`: the exact text a picker inserts.
 * - `diffLines`: a line diff of two text views, for comparing versions.
 *
 * Design decisions: a heuristic scan, not a parser. A line is judged by its first word only, so a half-typed
 * layout still resolves most aliases, and the worst case (an alias not found) leaves the author typing it by hand.
 */
import type { LayoutFamily, ReportWidget } from "../api/reportLayouts";

/** A name usable as `{{name.field}}` at some line. */
export interface AliasInScope {
  name: string;
  /** `record` stands for one record, `group` for a group of them (`value`, `count`). */
  kind: "record" | "group";
  /** The record type of the record, or of the group's members; `null` when it could not be told. */
  recordType: string | null;
}

interface Frame {
  alias: AliasInScope | null;
}

const BLOCK_OPENERS = new Set(["each", "group", "table", "sheet", "if"]);
const ALIAS_NAME = /(?:^|\s)as\s+([a-z][a-z0-9_]*)(?=\s|$)/;
const DEFAULT_RECORD_ALIAS = "record";
const DEFAULT_GROUP_ALIAS = "group";

/** The first word after `@name` on a directive line, i.e. the source's record type or `in`. */
function sourceOf(rest: string, visible: AliasInScope[]): string | null {
  const words = rest.trim().split(/\s+/);
  if (words[0] === "in") {
    const group = visible.find((a) => a.name === words[1]);
    return group?.recordType ?? null;
  }
  return words[0] && /^[a-z][a-z0-9_]*$/.test(words[0]) ? words[0] : null;
}

/**
 * The aliases visible at `lineIndex` (0-based), outermost first: every enclosing `@each` and `@group` that has
 * been opened and not yet closed by `@end` on the lines before it.
 *
 * @param text The whole text view.
 * @param lineIndex The line the caret is on; that line itself is not scanned.
 */
export function aliasesInScope(text: string, lineIndex: number): AliasInScope[] {
  const frames: Frame[] = [];
  let inTextBlock = false;
  const lines = text.split("\n");
  for (let i = 0; i < Math.min(lineIndex, lines.length); i += 1) {
    const line = lines[i].trim();
    if (inTextBlock) {
      if (line === "@end") inTextBlock = false;
      continue;
    }
    const match = /^@([a-z_]+)(.*)$/.exec(line);
    if (!match) continue;
    const [, name, rest] = match;
    if (name === "text" && rest.trim() === "") {
      inTextBlock = true;
    } else if (name === "end") {
      frames.pop();
    } else if (BLOCK_OPENERS.has(name)) {
      const visible = frames.flatMap((f) => (f.alias ? [f.alias] : []));
      let alias: AliasInScope | null = null;
      if (name === "each" || name === "group") {
        alias = {
          name: ALIAS_NAME.exec(rest)?.[1] ?? (name === "each" ? DEFAULT_RECORD_ALIAS : DEFAULT_GROUP_ALIAS),
          kind: name === "each" ? "record" : "group",
          recordType: sourceOf(rest, visible),
        };
      }
      frames.push({ alias });
    }
  }
  return frames.flatMap((f) => (f.alias ? [f.alias] : []));
}

/** The 0-based line the offset falls on. */
export function lineOfOffset(text: string, offset: number): number {
  let line = 0;
  for (let i = 0; i < Math.min(offset, text.length); i += 1) if (text[i] === "\n") line += 1;
  return line;
}

/** The offset of the start of a 1-based line (the end of the text when the line is past it). */
export function offsetOfLine(text: string, line: number): number {
  let offset = 0;
  for (let current = 1; current < line; current += 1) {
    const next = text.indexOf("\n", offset);
    if (next === -1) return text.length;
    offset = next + 1;
  }
  return offset;
}

/**
 * Replaces the selection (or inserts at the caret) with `snippet`.
 *
 * @returns The new text and where the caret goes (just after the snippet).
 */
export function insertAt(text: string, start: number, end: number, snippet: string): { text: string; caret: number } {
  return { text: text.slice(0, start) + snippet + text.slice(end), caret: start + snippet.length };
}

/**
 * Keeps an insertion off the `@layout` line: the first line declares the layout's kind and nothing may be put
 * before or on it, so a caret at the very start (an editor nobody has clicked in yet) lands after it.
 *
 * @param text The whole text view.
 * @param start Selection start.
 * @param end Selection end.
 * @returns The range to replace.
 */
export function insertionRange(text: string, start: number, end: number): { start: number; end: number } {
  if (!text.startsWith("@layout")) return { start, end };
  const newline = text.indexOf("\n");
  const firstLineEnd = newline === -1 ? text.length : newline + 1;
  return start < firstLineEnd ? { start: firstLineEnd, end: firstLineEnd } : { start, end };
}

/**
 * Snippet for a block that starts on its own line: adds a leading line break when the caret is not at the start
 * of a line, and a trailing one, so the block never glues onto the text beside it.
 */
export function asBlock(text: string, start: number, snippet: string): string {
  const atLineStart = start === 0 || text[start - 1] === "\n";
  return `${atLineStart ? "" : "\n"}${snippet}\n`;
}

/** `{{alias.field}}` or `{{name}}`. */
export function placeholder(alias: string | null, field: string): string {
  return alias ? `{{${alias}.${field}}}` : `{{${field}}}`;
}

/** One starter block the designer can insert. */
export interface BlockSnippet {
  /** The block's name; its label is `strings.reportLayouts.blockLabels[key]`. */
  key: string;
  families: LayoutFamily[];
  text: string;
}

/** Starter text per block type; `requirement` is a type every deployment has. */
export const BLOCK_SNIPPETS: BlockSnippet[] = [
  { key: "heading", families: ["document"], text: "@heading level=2 Heading" },
  { key: "text", families: ["document"], text: "Some text. Use {{project_name}} for the project's name." },
  { key: "each", families: ["document"], text: "@each requirement sort title as req\n  @heading level=3 {{req.code}} {{req.title}}\n@end" },
  { key: "group", families: ["document"], text: "@group requirement by status as grp\n  @heading level=2 {{grp.value}} ({{grp.count}})\n@end" },
  { key: "table", families: ["document"], text: "@table requirement sort title\n  @column code\n  @column title \"Requirement\"\n@end" },
  { key: "if", families: ["document"], text: "@if req.status eq Approved\n  Approved.\n@else\n  Not approved yet.\n@end" },
  { key: "page_break", families: ["document"], text: "@page_break" },
  { key: "sheet", families: ["table"], text: "@sheet \"Requirements\" requirement sort title\n  @column code\n  @column title\n@end" },
];

/**
 * The line a widget picker inserts: `[[widget.<key> name=value ...]]`. A boolean or whole number is written bare,
 * every other value quoted, and an unset value is left out so the report's default applies.
 *
 * @param widget The chosen component.
 * @param values Parameter values by name (`undefined`, `null` and `""` are skipped).
 */
export function widgetLine(widget: ReportWidget, values: Record<string, string | number | boolean | null | undefined>): string {
  const settings = widget.params.flatMap((param) => {
    const value = values[param.name];
    if (value === undefined || value === null || value === "") return [];
    const written = param.type === "boolean" || param.type === "integer" ? String(value) : JSON.stringify(String(value));
    return [` ${param.name}=${written}`];
  });
  return `[[widget.${widget.key}${settings.join("")}]]`;
}

/** One line of a diff. */
export interface DiffLine {
  kind: "same" | "add" | "remove";
  text: string;
}

/** Most cells of the comparison table; beyond it the two texts are shown as wholly replaced rather than stall the page. */
const MAX_DIFF_CELLS = 4_000_000;

/**
 * A line diff (longest common subsequence) of two texts.
 *
 * @param before The older text.
 * @param after The newer text.
 * @returns Every line of both, in order, marked kept, added or removed.
 */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before === "" ? [] : before.split("\n");
  const b = after === "" ? [] : after.split("\n");
  if ((a.length + 1) * (b.length + 1) > MAX_DIFF_CELLS) {
    return [...a.map((text): DiffLine => ({ kind: "remove", text })), ...b.map((text): DiffLine => ({ kind: "add", text }))];
  }
  const width = b.length + 1;
  const table = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * width + j] = a[i] === b[j] ? table[(i + 1) * width + j + 1] + 1 : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) {
      out.push({ kind: "remove", text: a[i] });
      i += 1;
    } else {
      out.push({ kind: "add", text: b[j] });
      j += 1;
    }
  }
  for (; i < a.length; i += 1) out.push({ kind: "remove", text: a[i] });
  for (; j < b.length; j += 1) out.push({ kind: "add", text: b[j] });
  return out;
}
