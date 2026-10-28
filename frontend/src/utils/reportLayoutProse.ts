/**
 * Module: utils/reportLayoutProse
 *
 * The prose of a layout's text block as editor nodes and back: a small reader and writer of the canonical
 * Markdown spelling the report engine understands, with no editor dependency so it can be tested as plain
 * functions.
 *
 * Responsibilities:
 * - `parseMarkdown`: canonical Markdown to editor nodes (`# Heading`, paragraphs, `- ` and `1. ` lists, and bold,
 *   italic, code and link runs inside text), or `null` when the text is not in that spelling.
 * - `linkProblem` and `headingAnchor`: ports of the server's rules for what may be a link and what a heading's
 *   anchor is called (tested against the same vectors, `testing/linkVectors.json`).
 * - `serializeMarkdown`: editor nodes back to that spelling.
 * - Hold the editor node vocabulary (`DOC`, `DocNode`) the document converter and the editor share.
 *
 * Design decisions:
 * - **Lossless or not at all.** The reader returns nodes only when `serializeMarkdown(parse(text)) === text`, and is
 *   deliberately stricter than the server's Markdown reader: anything it is unsure of (a stray `*`, a backslash that
 *   is not an escape it writes itself, `_` emphasis, a line the server could take for a list, quote, fence or table)
 *   returns `null`, and the block stays a raw-Markdown source box. A text is therefore never rewritten, and the
 *   worst a mismatch can do is leave a block as source.
 * - **Spelling.** Bold is `**x**`, italic `*x*`, both `***x***`, code `` `x` ``, a link `[words](address)` (the words may
 *   be styled, a code span cannot be a link); a writer moves leading and trailing
 *   space outside the markers (the server only reads a run that starts and ends on a word), and escapes `*`, a
 *   backtick, a backslash and a `_` that is not inside a word. Equations (`\( \)`, `$$ $$`) and `{{placeholders}}`
 *   are copied through unread, as the server sets equations aside before it reads styles.
 */

/** A node of the editor's document as ProseMirror writes it. */
export interface DocNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: DocNode[];
  text?: string;
  marks?: { type: string; attrs?: Record<string, unknown> }[];
}

/** The names of the editor node types the converter produces. */
export const DOC = {
  heading: "layoutHeading",
  text: "layoutText",
  raw: "layoutRawText",
  leaf: "layoutLeaf",
  block: "layoutBlock",
  slot: "layoutSlot",
  mdHeading: "layoutMdHeading",
  paragraph: "paragraph",
  bulletList: "bulletList",
  orderedList: "orderedList",
  listItem: "listItem",
} as const;

/** The mark names, in the order a run's markers nest. */
export const MARKS = { bold: "bold", italic: "italic", code: "code", link: "link" } as const;

/** A run of text with its styles and, for a link, where it goes. */
interface Run {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
  href?: string;
}

/** Plain text as editor nodes (none for empty text). */
export const textNode = (text: string): DocNode[] => (text === "" ? [] : [{ type: "text", text }]);
/** The text of editor nodes, marks ignored. */
export const textOf = (nodes: DocNode[] | undefined): string => (nodes ?? []).map((n) => n.text ?? "").join("");

// ---- links and anchors: ports of the server's rules -----------------------------------------------------------------

const LINK_BAD = /[\s<>"\\]/;
/** Whether a character is a control character (which a link address may not hold). */
const isControl = (ch: string) => ch.charCodeAt(0) <= 0x1f || ch.charCodeAt(0) === 0x7f;
const MAILTO_ADDRESS = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/;
const WEB_ADDRESS = /^https?:\/\/(?:[^/?#@]*@)?(?:\[[^\]]+\]|[^/?#@:]+)(?::\d*)?(?:[/?#]|$)/i;

/**
 * Why `href` may not be a link, or `null` when it may (a port of `report_model.link_problem`): an absolute http or
 * https address with a host, a `mailto:` address, or `#heading` in the same document. The message never repeats the
 * address.
 */
export function linkProblem(href: string): string | null {
  if (href === "" || href.length > 2000) return "A link address must be between 1 and 2000 characters.";
  if (LINK_BAD.test(href) || [...href].some(isControl)) return "A link address cannot hold spaces, control characters, quotes, angle brackets or backslashes.";
  if (href.startsWith("#")) return /^[\p{L}\p{N}_-]+$/u.test(href.slice(1)) ? null : "A link to a section must name a heading.";
  const scheme = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(href)?.[1].toLowerCase();
  if (scheme === "http" || scheme === "https") return WEB_ADDRESS.test(href) ? null : "A web link needs a host name.";
  if (scheme === "mailto") return MAILTO_ADDRESS.test(href.slice(7).split("?")[0]) ? null : "An email link needs one email address.";
  return "Only web (http, https), email (mailto) and section (#) links are allowed.";
}

/** The anchor name of a heading's words (a port of `report_model.heading_anchor`): lower case, runs of other characters a hyphen. */
export function headingAnchor(text: string): string {
  const slug = text.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
  return slug === "" ? "section" : slug;
}

// ---- equations and placeholders, copied through unread --------------------------------------------------------------

/** Ranges `[start, end)` of `text` that are equations (as the server's `split_math` finds them) or `{{placeholders}}`. */
function opaqueRanges(text: string): [number, number][] {
  const ranges: [number, number][] = [];
  let cursor = 0;
  for (const opener of text.matchAll(/\\\(|\$\$/g)) {
    const start = opener.index ?? 0;
    if (start < cursor) continue;
    const closer = opener[0] === "$$" ? "$$" : "\\)";
    const end = text.indexOf(closer, start + opener[0].length);
    if (end < 0 || text.slice(start + opener[0].length, end).trim() === "") continue;
    ranges.push([start, end + closer.length]);
    cursor = end + closer.length;
  }
  for (const match of text.matchAll(/\{\{[^{}]*\}\}/g)) {
    const start = match.index ?? 0;
    if (!ranges.some(([from, to]) => start >= from && start < to)) ranges.push([start, start + match[0].length]);
  }
  return ranges.sort((a, b) => a[0] - b[0]);
}

const rangeAt = (ranges: [number, number][], i: number) => ranges.find(([from, to]) => i >= from && i < to);
const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch);
const isWord = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);
const isPunctuation = (ch: string | undefined) => ch !== undefined && /[\p{P}\p{S}]/u.test(ch);

// ---- inline: runs <-> text ------------------------------------------------------------------------------------------

/**
 * Reads a link that opens at `start` (`[words](address)`).
 *
 * @returns Its runs (each carrying the address) and where the text goes on; `undefined` when what follows is not a
 * link at all; `null` when it is a link this reader will not interpret (an address that is not allowed, a code span
 * inside, nested brackets), which leaves the block as source.
 */
function readLink(text: string, start: number, opaque: [number, number][]): { runs: Run[]; end: number } | undefined | null {
  let close = start + 1;
  while (close < text.length && (rangeAt(opaque, close) || (text[close] !== "]" && text[close] !== "["))) {
    close = rangeAt(opaque, close)?.[1] ?? close + 1;
  }
  if (text[close] !== "]" || text[close + 1] !== "(") return text[close] === "[" ? null : undefined;
  const end = text.indexOf(")", close + 2);
  const href = end < 0 ? "" : text.slice(close + 2, end);
  if (end < 0 || href === "" || /\s/.test(href) || (!href.includes("{{") && linkProblem(href) !== null)) return null;
  const inner = parseInline(text.slice(start + 1, close));
  if (inner === null || inner.length === 0 || inner.some((run) => run.code || run.href)) return null;
  return { runs: inner.map((run) => ({ ...run, href })), end: end + 1 };
}

/**
 * Reads the inline styles of one paragraph or list item.
 *
 * @returns Its runs, or `null` when it holds anything this reader will not interpret (see the module note).
 */
function parseInline(text: string): Run[] | null {
  const opaque = opaqueRanges(text);
  const runs: Run[] = [];
  let plain = "";
  const flush = () => {
    if (plain !== "") runs.push({ text: plain });
    plain = "";
  };
  let i = 0;
  while (i < text.length) {
    const hidden = rangeAt(opaque, i);
    if (hidden) {
      plain += text.slice(hidden[0], hidden[1]);
      i = hidden[1];
      continue;
    }
    const ch = text[i];
    if (ch === "\\") {
      if (!"*`\\_[]".includes(text[i + 1] ?? "")) return null;
      plain += text[i + 1];
      i += 2;
    } else if (ch === "[") {
      const link = readLink(text, i, opaque);
      if (link === undefined) {
        plain += ch; // a bracket that does not open a link is just a character
        i += 1;
        continue;
      }
      if (link === null) return null;
      flush();
      runs.push(...link.runs);
      i = link.end;
    } else if (ch === "`") {
      const end = text.indexOf("`", i + 1);
      const content = end < 0 ? "" : text.slice(i + 1, end);
      if (end < 0 || text[i + 1] === "`" || content === "" || content !== content.trim() || content.includes("\\") || text[end + 1] === "`") return null;
      flush();
      runs.push({ text: content, code: true });
      i = end + 1;
    } else if (ch === "*") {
      let count = 0;
      while (text[i + count] === "*") count += 1;
      if (count === 1 && isSpace(text[i - 1]) && isSpace(text[i + 1])) {
        plain += ch; // a lone asterisk between spaces is just a character
        i += 1;
        continue;
      }
      if (count > 3) return null;
      let close = i + count;
      while (close < text.length && (rangeAt(opaque, close) || text[close] !== "*")) {
        if (text[close] === "`" && !rangeAt(opaque, close)) return null;
        close = rangeAt(opaque, close)?.[1] ?? close + 1;
      }
      let after = 0;
      while (text[close + after] === "*") after += 1;
      const inner = text.slice(i + count, close);
      const before = text[i - 1];
      const next = text[close + after];
      if (close >= text.length || after !== count || inner === "" || isSpace(inner[0]) || isSpace(inner[inner.length - 1])) return null;
      if (inner.includes("](")) return null; // a link inside emphasis is not drawn as one here: leave it as source
      // A run next to punctuation inside and a letter outside is not emphasis to every reader: leave such text as source.
      if ((isPunctuation(inner[0]) && isWord(before)) || (isPunctuation(inner[inner.length - 1]) && isWord(next))) return null;
      flush();
      runs.push({ text: inner, bold: count >= 2, italic: count === 1 || count === 3 });
      i = close + after;
    } else if (ch === "_") {
      if (!(isWord(text[i - 1]) && isWord(text[i + 1]))) return null;
      plain += ch;
      i += 1;
    } else {
      plain += ch;
      i += 1;
    }
  }
  flush();
  return runs;
}

/** Editor text nodes for runs, each carrying its marks. */
function runNodes(runs: Run[]): DocNode[] {
  return runs.map((run) => {
    const marks = [
      run.bold && { type: MARKS.bold }, run.italic && { type: MARKS.italic }, run.code && { type: MARKS.code },
      run.href !== undefined && { type: MARKS.link, attrs: { href: run.href } },
    ].filter(Boolean) as { type: string; attrs?: Record<string, unknown> }[];
    return marks.length > 0 ? { type: "text", text: run.text, marks } : { type: "text", text: run.text };
  });
}

/** Escapes what would otherwise be read as a style in plain text; equations and placeholders are left alone. */
function escapePlain(text: string, inLink = false): string {
  const opaque = opaqueRanges(text);
  // A bracket is escaped only where it could open or sit inside a link, so ordinary "[1]" stays as typed.
  const bracket = inLink || text.includes("](");
  let out = "";
  for (let i = 0; i < text.length; i += 1) {
    const hidden = rangeAt(opaque, i);
    if (hidden) {
      out += text.slice(hidden[0], hidden[1]);
      i = hidden[1] - 1;
    } else if (text[i] === "*" && isSpace(text[i - 1]) && isSpace(text[i + 1]) && text[i - 1] !== undefined && text[i + 1] !== undefined) {
      out += text[i]; // a lone asterisk between spaces is read back as a character
    } else if ("*`\\".includes(text[i]) || (bracket && "[]".includes(text[i])) || (text[i] === "_" && !(isWord(text[i - 1]) && isWord(text[i + 1])))) {
      out += `\\${text[i]}`;
    } else {
      out += text[i];
    }
  }
  return out;
}

/** The marks of an editor text node. */
const marksOf = (node: DocNode): Run => ({
  text: node.text ?? "",
  bold: node.marks?.some((m) => m.type === MARKS.bold),
  italic: node.marks?.some((m) => m.type === MARKS.italic),
  code: node.marks?.some((m) => m.type === MARKS.code),
  href: node.marks?.find((m) => m.type === MARKS.link)?.attrs?.href as string | undefined,
});

/** Whether two runs carry the same marks (so their text can be written together). */
const sameMarks = (a: Run, b: Run) => !!a.bold === !!b.bold && !!a.italic === !!b.italic && !!a.code === !!b.code && a.href === b.href;

/** Writes runs that are not links: styled runs in their markers, plain text escaped. */
function writeRuns(runs: Run[], inLink: boolean): string {
  return runs.map((run) => {
    if (run.code) return run.text.includes("`") ? run.text : `\`${run.text}\``;
    if (!run.bold && !run.italic) return escapePlain(run.text, inLink);
    const core = run.text.trim();
    if (core === "") return run.text;
    const lead = run.text.slice(0, run.text.indexOf(core));
    const trail = run.text.slice(lead.length + core.length);
    const marker = run.bold && run.italic ? "***" : run.bold ? "**" : "*";
    return `${lead}${marker}${escapePlain(core, inLink)}${marker}${trail}`;
  }).join("");
}

/** Writes inline editor nodes as Markdown. */
function writeInline(nodes: DocNode[] | undefined): string {
  const runs: Run[] = [];
  for (const node of nodes ?? []) {
    const run = marksOf(node);
    const last = runs[runs.length - 1];
    if (last && sameMarks(last, run)) last.text += run.text;
    else runs.push(run);
  }
  let out = "";
  for (let i = 0; i < runs.length; i += 1) {
    const href = runs[i].href;
    if (href === undefined) {
      out += writeRuns([runs[i]], false);
      continue;
    }
    // Consecutive runs of one link are written as one link; its edge spaces go outside the brackets.
    const group: Run[] = [];
    while (i < runs.length && runs[i].href === href) group.push({ ...runs[i++], href: undefined });
    i -= 1;
    const words = group.map((run) => run.text).join("");
    const lead = words.slice(0, words.length - words.trimStart().length);
    const trail = words.slice(words.trimEnd().length);
    const inner = writeRuns(group, true).trim();
    out += inner === "" ? words : `${lead}[${inner}](${href})${trail}`;
  }
  return out;
}

// ---- blocks: Markdown <-> editor nodes ------------------------------------------------------------------------------

const MD_HEADING = /^(#{1,4}) (\S(?:.*\S)?)$/;
/** A heading ending in a closing `#` run, which the server's reader would drop from the heading's text. */
const MD_CLOSING_HASHES = /\s#+$/;
const MD_BULLET = /^- (\S(?:.*\S)?)$/;
const MD_NUMBER = /^(\d+)\. (\S(?:.*\S)?)$/;
/** A line that could start other Markdown syntax (list, quote, fence, table, HTML, setext rule, image). */
const MD_RISKY_START = /^([#>~|<!=+_-]|\d+[.)](\s|$)|`{3}|\*\s|\*+\s*$)/;

/** Whether a line may sit in a paragraph without the server's Markdown reader taking it for other syntax. */
function plainLine(line: string): boolean {
  return line !== "" && line === line.trim() && !MD_RISKY_START.test(line) && !line.endsWith("\\");
}

/** Inline editor nodes for text, or `null` when the text is not in the canonical spelling. */
function inlineNodes(text: string): DocNode[] | null {
  const runs = parseInline(text);
  return runs === null ? null : runNodes(runs);
}

const listItem = (nodes: DocNode[]): DocNode => ({ type: DOC.listItem, content: [{ type: DOC.paragraph, content: nodes }] });

/**
 * Reads canonical Markdown into editor nodes.
 *
 * @returns The nodes, or `null` when the text is not in the canonical spelling this reader understands (or would
 * not serialise back to exactly the same string).
 */
export function parseMarkdown(markdown: string): DocNode[] | null {
  if (markdown === "" || markdown !== markdown.trim()) return null;
  const nodes: DocNode[] = [];
  for (const block of markdown.split("\n\n")) {
    const lines = block.split("\n");
    const heading = lines.length === 1 ? MD_HEADING.exec(block) : null;
    if (heading) {
      // A heading is bold already and carries no styles: text with any is left as source.
      const runs = MD_CLOSING_HASHES.test(heading[2]) ? null : parseInline(heading[2]);
      if (!runs || runs.some((r) => r.bold || r.italic || r.code)) return null;
      nodes.push({ type: DOC.mdHeading, attrs: { level: heading[1].length }, content: textNode(runs.map((r) => r.text).join("")) });
    } else if (lines.every((l) => MD_BULLET.test(l))) {
      const items = lines.map((l) => inlineNodes(MD_BULLET.exec(l)?.[1] ?? ""));
      if (items.some((item) => item === null)) return null;
      nodes.push({ type: DOC.bulletList, content: items.map((item) => listItem(item ?? [])) });
    } else if (lines.every((l, n) => MD_NUMBER.exec(l)?.[1] === String(n + 1))) {
      const items = lines.map((l) => inlineNodes(MD_NUMBER.exec(l)?.[2] ?? ""));
      if (items.some((item) => item === null)) return null;
      nodes.push({ type: DOC.orderedList, content: items.map((item) => listItem(item ?? [])) });
    } else if (lines.every(plainLine)) {
      const inline = inlineNodes(block);
      if (inline === null) return null;
      nodes.push({ type: DOC.paragraph, content: inline });
    } else {
      return null;
    }
  }
  return serializeMarkdown(nodes) === markdown ? nodes : null;
}

/** Writes editor nodes of a text block as canonical Markdown; empty paragraphs and list items are dropped. */
export function serializeMarkdown(nodes: DocNode[]): string {
  const blocks: string[] = [];
  for (const node of nodes) {
    if (node.type === DOC.mdHeading) {
      const text = textOf(node.content).trim();
      if (text !== "") blocks.push(`${"#".repeat(Number(node.attrs?.level ?? 1))} ${escapePlain(text)}`);
    } else if (node.type === DOC.bulletList || node.type === DOC.orderedList) {
      const items = (node.content ?? []).map((item) => writeInline(item.content?.[0]?.content).trim()).filter((t) => t !== "");
      if (items.length === 0) continue;
      blocks.push(items.map((t, n) => (node.type === DOC.bulletList ? `- ${t}` : `${n + 1}. ${t}`)).join("\n"));
    } else {
      const text = writeInline(node.content).trim();
      if (text !== "") blocks.push(text);
    }
  }
  return blocks.join("\n\n");
}
