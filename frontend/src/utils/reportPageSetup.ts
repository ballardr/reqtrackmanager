/**
 * Module: utils/reportPageSetup
 *
 * The page setup of a document layout (paper, orientation, margins, mirrored margins and named page styles) as the
 * designer edits it, and the text view's lines that state it.
 *
 * Responsibilities:
 * - Name the vocabulary and limits the server accepts (`PAGE_SIZES`, `MARGIN_SIDES`, the margin range) so a form can
 *   offer them; the server stays the judge of what is valid.
 * - `readPageSetup` / `writePageSetup`: read the setup from a layout's text (its `@layout document …` line and its
 *   `@pagestyle` lines) and rewrite exactly those lines, leaving every block alone.
 * - `RunningBand`: a header or footer (left, centre and right text, a logo, whether the first page shows it) and the
 *   `@header` / `@footer` lines that state it under the layout or a `@pagestyle` line.
 * - `effectiveMargins`, `pageDimensionsCm`: the numbers a page sketch and a form's placeholders need, with the same
 *   defaults the server's renderers use.
 *
 * Design decisions: a heuristic reader of the lines it owns, not a parser (backend `services.report_layout_text` is
 * the parser). A line it cannot read leaves that part at its default, so the worst case is a form showing a default
 * for something the server then rejects with a positioned message.
 */
import type { LayoutFamily } from "../api/reportLayouts";
import { RUN_SCOPE_WORDS, runScopeOfWords, type RunScope } from "./runScope";

export const PAGE_ORIENTATIONS = ["portrait", "landscape"] as const;
export const PAGE_SIZES = ["A3", "A4", "A5", "Letter", "Legal"] as const;
/** The sides of a page, in the order the text view writes them; `gutter` is extra room on the binding edge. */
export const MARGIN_SIDES = ["top", "bottom", "left", "right", "gutter"] as const;

export type PageOrientation = (typeof PAGE_ORIENTATIONS)[number];
export type PageSize = (typeof PAGE_SIZES)[number];
export type MarginSide = (typeof MARGIN_SIDES)[number];
/** Margins in cm; a side that is left out is the layout's own (or the default). */
export type PageMargins = Partial<Record<MarginSide, number>>;

export const DEFAULT_MARGIN_CM = 1.5;
export const MIN_MARGIN_CM = 1;
export const MAX_MARGIN_CM = 10;
export const MAX_GUTTER_CM = 5;
export const MAX_PAGE_STYLES = 10;

export const BAND_SLOTS = ["left", "centre", "right"] as const;
export type BandSlot = (typeof BAND_SLOTS)[number];
export const BAND_VALIGN = ["top", "middle", "bottom"] as const;
export type BandValign = (typeof BAND_VALIGN)[number];
export const BAND_FIRST_PAGE = ["same", "none"] as const;
export type BandFirstPage = (typeof BAND_FIRST_PAGE)[number];
/** Space between the page edge and a header or footer, and the height of one line of its text, in cm (as the server checks). */
export const BAND_EDGE_CM = 0.5;
export const BAND_LINE_CM = 0.4;
/** A band's default text size in points, and the range the server accepts. */
export const BAND_SIZE_PT = 8;
export const MIN_BAND_SIZE_PT = 6;
export const MAX_BAND_SIZE_PT = 72;
export const MIN_LOGO_CM = 0.3;
export const MAX_LOGO_CM = 5;
export const DEFAULT_LOGO_CM = 0.9;

/** A header or footer; `{}` prints nothing, and no band at all means "use the one this inherits". */
export interface RunningBand {
  left?: string;
  centre?: string;
  right?: string;
  logo?: { file: string; height: number; slot?: BandSlot };
  first_page?: BandFirstPage;
  /** A cell's fixed width, `"25%"` of the band or a length like `"4 cm"`; absent, the cell fits its text. */
  left_width?: string;
  centre_width?: string;
  right_width?: string;
  /** Where the content sits in the row: the band's setting (top when absent) and a cell's own, which wins. */
  valign?: BandValign;
  left_valign?: BandValign;
  centre_valign?: BandValign;
  right_valign?: BandValign;
  /** The band's font key, size in points and colour word; absent follows the document's body font, 8 pt and black. */
  font?: string;
  size?: number;
  colour?: string;
}

/** A named page style a section can use; what it leaves out is the layout's own. */
export interface PageStyleSetup {
  name: string;
  orientation?: PageOrientation;
  size?: PageSize;
  margins?: PageMargins;
  header?: RunningBand;
  footer?: RunningBand;
}

/** A layout's page setup; the layout's own pages first, then its named styles. */
export interface PageSetup {
  orientation: PageOrientation;
  size: PageSize;
  mirror: boolean;
  /** Whether a table's heading row is printed again on each page: `false` for `norepeatheader`, `true` for an explicit `repeatheader`, `undefined` when the line says neither (on). */
  repeatHeader?: boolean;
  /** Whether tables with the same headings share column widths: `false` for `noalign`, `true` for an explicit `align`, `undefined` when the line says neither (on). */
  alignTables?: boolean;
  /** Whether the extra fonts are embedded in Word and OpenDocument files: `true` for `embedfonts`, `false` for `noembedfonts`, `undefined` when the line says neither. Carried so the page setup dialog rewrites the line without losing it. */
  embedFonts?: boolean;
  /** Which projects the layout runs for, as the line states it (`undefined` when it states none, which means any). */
  runScope?: RunScope;
  margins: PageMargins;
  styles: PageStyleSetup[];
  header?: RunningBand;
  footer?: RunningBand;
}

/** The short sides then long sides of each page size in cm, as the server's renderers use them. */
const PAGE_SIZES_CM: Record<PageSize, [number, number]> = {
  A3: [29.7, 42], A4: [21, 29.7], A5: [14.8, 21], Letter: [21.59, 27.94], Legal: [21.59, 35.56],
};

/** The page's (width, height) in cm, turned on its side for landscape. */
export function pageDimensionsCm(size: PageSize, orientation: PageOrientation): [number, number] {
  const [short, long] = PAGE_SIZES_CM[size];
  return orientation === "landscape" ? [long, short] : [short, long];
}

/** Every side with the default filled in for one that is left out. */
export function effectiveMargins(margins: PageMargins | undefined, inherited: PageMargins = {}): Required<PageMargins> {
  const pick = (side: MarginSide) => margins?.[side] ?? inherited[side] ?? (side === "gutter" ? 0 : DEFAULT_MARGIN_CM);
  return { top: pick("top"), bottom: pick("bottom"), left: pick("left"), right: pick("right"), gutter: pick("gutter") };
}

const HEADER = /^@layout\s+document\b(.*)$/;
const STYLE_LINE = /^\s*@pagestyle\b(.*)$/;
const BAND_LINE = /^\s*@(header|footer)\b(.*)$/;
const TOKEN = /"(?:[^"\\]|\\.)*"|\S+/g;

/** The `side=cm` words after `margins`, as numbers; words it cannot read are skipped. */
function readMargins(words: string[]): PageMargins {
  const margins: PageMargins = {};
  for (const word of words) {
    const [key, value] = word.split("=");
    const number = Number(value);
    if ((MARGIN_SIDES as readonly string[]).includes(key) && value !== undefined && value !== "" && Number.isFinite(number)) {
      margins[key as MarginSide] = number;
    }
  }
  return margins;
}

/** ` margins top=2 …` for the sides that are set, or an empty string. */
function marginsText(margins: PageMargins | undefined): string {
  const set = MARGIN_SIDES.filter((side) => margins?.[side] !== undefined);
  return set.length === 0 ? "" : ` margins ${set.map((side) => `${side}=${margins?.[side]}`).join(" ")}`;
}

/** The orientation and size words of a header or style line. */
function readWords(words: string[]): { orientation?: PageOrientation; size?: PageSize } {
  return {
    orientation: PAGE_ORIENTATIONS.find((o) => words.includes(o)),
    size: PAGE_SIZES.find((s) => words.includes(s)),
  };
}

/** Everything after `margins` and the words before it. */
function split(tokens: string[]): { before: string[]; margins: string[] } {
  const at = tokens.indexOf("margins");
  return at === -1 ? { before: tokens, margins: [] } : { before: tokens.slice(0, at), margins: tokens.slice(at + 1) };
}

function readStyle(rest: string): PageStyleSetup {
  const tokens = rest.match(TOKEN) ?? [];
  const first = tokens[0] ?? '""';
  let name = first;
  if (first.startsWith('"')) {
    try {
      name = JSON.parse(first) as string;
    } catch {
      name = first.slice(1, -1);
    }
  }
  const { before, margins } = split(tokens.slice(1));
  const { orientation, size } = readWords(before);
  const style: PageStyleSetup = { name };
  if (orientation) style.orientation = orientation;
  if (size) style.size = size;
  const read = readMargins(margins);
  if (Object.keys(read).length > 0) style.margins = read;
  return style;
}

/** A quoted string token as text (the server writes JSON strings); a token that is not valid JSON is read without its quotes. */
function unquote(token: string | undefined): string {
  if (token === undefined) return "";
  if (!token.startsWith('"')) return token;
  try {
    return JSON.parse(token) as string;
  } catch {
    return token.slice(1, -1);
  }
}

/** The band an `@header` / `@footer` line states (`@header` alone is the empty band); words it cannot read are skipped. */
function readBand(rest: string): RunningBand {
  const tokens = rest.match(TOKEN) ?? [];
  const band: RunningBand = {};
  for (let i = 0; i < tokens.length; i += 1) {
    const word = tokens[i];
    const value = tokens[i + 1];
    if (word === "left" || word === "centre" || word === "right") band[word] = unquote(value);
    else if (word === "valign" || BAND_SLOTS.some((slot) => word === `${slot}valign`)) {
      if (!(BAND_VALIGN as readonly string[]).includes(value ?? "")) continue;
      band[(word === "valign" ? "valign" : `${word.slice(0, -6)}_valign`) as "valign"] = value as BandValign;
    } else if (BAND_SLOTS.some((slot) => word === `${slot}width`)) {
      if (!value || value === "auto") {
        i += value === "auto" ? 1 : 0;
        continue;
      }
      const unit = tokens[i + 2];
      const spec = !value.endsWith("%") && (unit === "cm" || unit === "mm") ? `${value} ${unit}` : value;
      band[`${word.slice(0, -5)}_width` as "left_width"] = spec;
      i += spec === value ? 1 : 2;
      continue;
    } else if (word === "first" && (BAND_FIRST_PAGE as readonly string[]).includes(value ?? "")) band.first_page = value as BandFirstPage;
    else if ((word === "font" || word === "colour") && value) band[word] = value;
    else if (word === "size" && Number.isFinite(Number(value))) band.size = Number(value);
    else if (word === "logo") band.logo = { file: unquote(value), height: DEFAULT_LOGO_CM };
    else if (word === "height" && band.logo && Number.isFinite(Number(value))) band.logo.height = Number(value);
    else if (word === "slot" && band.logo && (BAND_SLOTS as readonly string[]).includes(value ?? "")) band.logo.slot = value as BandSlot;
    else continue;
    i += 1;
  }
  return band;
}

/** A width as the server writes it: `20%`, or a number and unit apart (`4 cm`). */
function canonicalBandWidth(width: string): string {
  const match = /^\s*(\d+(?:\.\d+)?)\s*(%|cm|mm)\s*$/i.exec(width);
  if (!match) return width;
  const number = String(Number(match[1]));
  return match[2] === "%" ? `${number}%` : `${number} ${match[2].toLowerCase()}`;
}

/** The `@header` / `@footer` lines that state `band`, in the order the server reads them. */
function bandLine(kind: "header" | "footer", band: RunningBand): string {
  const parts = [`@${kind}`];
  for (const slot of BAND_SLOTS) if (band[slot] !== undefined) parts.push(`${slot} ${JSON.stringify(band[slot])}`);
  if (band.logo) {
    parts.push(`logo ${JSON.stringify(band.logo.file)}`, `height ${band.logo.height}`);
    if (band.logo.slot) parts.push(`slot ${band.logo.slot}`);
  }
  if (band.first_page) parts.push(`first ${band.first_page}`);
  if (band.font) parts.push(`font ${band.font}`);
  if (band.size !== undefined) parts.push(`size ${band.size}`);
  if (band.colour) parts.push(`colour ${band.colour}`);
  if (band.valign) parts.push(`valign ${band.valign}`);
  for (const slot of BAND_SLOTS) {
    const width = band[`${slot}_width`];
    if (width) parts.push(`${slot}width ${canonicalBandWidth(width)}`);
    const valign = band[`${slot}_valign`];
    if (valign) parts.push(`${slot}valign ${valign}`);
  }
  return parts.join(" ");
}

function bandLines(holder: { header?: RunningBand; footer?: RunningBand }): string[] {
  return (["header", "footer"] as const).flatMap((kind) => (holder[kind] ? [bandLine(kind, holder[kind])] : []));
}

/** The page setup a layout's text states, or `null` when the text is not a document layout's (a table has no pages). */
export function readPageSetup(text: string): PageSetup | null {
  const lines = text.split("\n");
  const match = HEADER.exec(lines[0].trimEnd());
  if (!match) return null;
  const { before, margins } = split(match[1].trim().split(/\s+/).filter(Boolean));
  const { orientation, size } = readWords(before);
  const setup: PageSetup = {
    orientation: orientation ?? "portrait",
    size: size ?? "A4",
    mirror: before.includes("mirror"),
    repeatHeader: before.includes("norepeatheader") ? false : before.includes("repeatheader") ? true : undefined,
    alignTables: before.includes("noalign") ? false : before.includes("align") ? true : undefined,
    embedFonts: before.includes("noembedfonts") ? false : before.includes("embedfonts") ? true : undefined,
    runScope: runScopeOfWords(before),
    margins: readMargins(margins),
    styles: [],
  };
  // A band line belongs to the page style written just above it, or to the layout before any.
  let holder: { header?: RunningBand; footer?: RunningBand } = setup;
  for (const line of lines.slice(1)) {
    const style = STYLE_LINE.exec(line);
    const band = BAND_LINE.exec(line);
    if (style) {
      const read = readStyle(style[1]);
      setup.styles.push(read);
      holder = read;
    } else if (band) {
      holder[band[1] as "header" | "footer"] = readBand(band[2]);
    }
  }
  return setup;
}

/** `text` with its `@layout document` line, its `@header` and `@footer` lines and its `@pagestyle` lines rewritten to state `setup`; defaults are left unwritten. */
export function writePageSetup(text: string, setup: PageSetup): string {
  const lines = text.split("\n");
  if (!HEADER.test(lines[0].trimEnd())) return text;
  const header = [
    "@layout document",
    ...(setup.orientation === "landscape" ? ["landscape"] : []),
    ...(setup.size === "A4" ? [] : [setup.size]),
    ...(setup.mirror ? ["mirror"] : []),
    ...(setup.repeatHeader === undefined ? [] : [setup.repeatHeader ? "repeatheader" : "norepeatheader"]),
    ...(setup.alignTables === undefined ? [] : [setup.alignTables ? "align" : "noalign"]),
    ...(setup.embedFonts === undefined ? [] : [setup.embedFonts ? "embedfonts" : "noembedfonts"]),
    ...(setup.runScope === undefined ? [] : [RUN_SCOPE_WORDS[setup.runScope]]),
  ].join(" ") + marginsText(setup.margins);
  const styles = setup.styles.map((style) => {
    const words = [style.orientation, style.size].filter((word) => word !== undefined).join(" ");
    return [`@pagestyle ${JSON.stringify(style.name)}${words ? ` ${words}` : ""}${marginsText(style.margins)}`, ...bandLines(style)];
  });
  const rest = lines.slice(1).filter((line) => !STYLE_LINE.test(line) && !BAND_LINE.test(line));
  return [header, ...bandLines(setup), ...styles.flat(), ...rest].join("\n");
}

/** The layout family's pages exist only for a document layout. */
export function hasPages(family: LayoutFamily): boolean {
  return family === "document";
}

/** A layout tree's `page_styles` entry as the editor holds it (`page_size` is `size`). */
export function styleFromTree(entry: Record<string, unknown>): PageStyleSetup {
  const style: PageStyleSetup = { name: typeof entry.name === "string" ? entry.name : "" };
  if (PAGE_ORIENTATIONS.includes(entry.orientation as PageOrientation)) style.orientation = entry.orientation as PageOrientation;
  if (PAGE_SIZES.includes(entry.page_size as PageSize)) style.size = entry.page_size as PageSize;
  if (entry.margins !== null && typeof entry.margins === "object") style.margins = entry.margins as PageMargins;
  for (const kind of ["header", "footer"] as const) if (entry[kind] !== null && typeof entry[kind] === "object") style[kind] = entry[kind] as RunningBand;
  return style;
}

/** The editor's style as a `page_styles` entry of the tree. */
export function styleToTree(style: PageStyleSetup): Record<string, unknown> {
  const entry: Record<string, unknown> = { name: style.name };
  if (style.orientation) entry.orientation = style.orientation;
  if (style.size) entry.page_size = style.size;
  if (style.margins) entry.margins = style.margins;
  if (style.header) entry.header = style.header;
  if (style.footer) entry.footer = style.footer;
  return entry;
}

/** The height in cm of one line of a band's text at `size` points: the default line, or taller for a larger size (as the server). */
export function bandLineCm(size: number | undefined): number {
  return Math.max(BAND_LINE_CM, (size ?? BAND_SIZE_PT) * 1.25 * (2.54 / 72));
}

/** The lines a band's text takes (a cell may hold up to three). */
function lineCount(text: string | undefined): number {
  return text ? text.split("\n").length : 0;
}

/**
 * The margin in cm a band needs (the gap to the page edge and its tallest cell), or 0 for a band that prints nothing; the
 * same arithmetic the server checks at save, so the editor can say what to raise before the save is refused.
 */
export function bandNeedsCm(band: RunningBand | undefined): number {
  if (!band) return 0;
  const lines = Math.max(...BAND_SLOTS.map((slot) => lineCount(band[slot])));
  const logo = band.logo?.height ?? 0;
  return lines > 0 || logo > 0 ? BAND_EDGE_CM + Math.max(lines * bandLineCm(band.size), logo) : 0;
}

const SAMPLE_PAGE = "3";
const SAMPLE_PAGES = "12";

/**
 * `text` with `snippet` written over the selection `start`..`end` (at `start` when they are equal).
 *
 * @param text The cell's text.
 * @param snippet What to write.
 * @param start Selection start; clamped to the text.
 * @param end Selection end; clamped to the text.
 * @returns The new text and the caret position after the snippet.
 */
export function insertAtCaret(text: string, snippet: string, start: number, end: number): { text: string; caret: number } {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  return { text: `${text.slice(0, from)}${snippet}${text.slice(to)}`, caret: from + snippet.length };
}

/** One stretch of a cell's text with its marks. */
export interface MarkedRun {
  text: string;
  bold: boolean;
  italic: boolean;
}

/**
 * A cell's text as stretches reading `**bold**`, `*italic*` and `***both***`, the way the server reads it: a mark opens before
 * a word and closes after one, a lone `*`, `2 * 3` or an unclosed mark stays as written, and `\*` is a literal asterisk.
 *
 * @param text One cell's text.
 * @returns The stretches in order, without empty ones.
 */
export function readMarks(text: string): MarkedRun[] {
  type Item = { text: string } | { stars: number; canOpen: boolean; canClose: boolean; applied: boolean };
  const items: Item[] = [];
  let last = 0;
  for (const match of text.matchAll(/\\\*|\*+/g)) {
    const at = match.index ?? 0;
    if (at > last) items.push({ text: text.slice(last, at) });
    last = at + match[0].length;
    if (match[0] === "\\*") {
      items.push({ text: "*" });
      continue;
    }
    const before = at > 0 ? text[at - 1] : "";
    const after = last < text.length ? text[last] : "";
    items.push({ stars: match[0].length, canOpen: after !== "" && !/\s/.test(after), canClose: before !== "" && !/\s/.test(before), applied: false });
  }
  if (last < text.length) items.push({ text: text.slice(last) });
  const kinds: Record<number, ("bold" | "italic")[]> = { 1: ["italic"], 2: ["bold"], 3: ["bold", "italic"] };
  const opened: Record<"bold" | "italic", number | null> = { bold: null, italic: null };
  items.forEach((item, index) => {
    if (!("stars" in item) || !kinds[item.stars]) return;
    const wanted = kinds[item.stars];
    if (wanted.every((k) => opened[k] !== null) && item.canClose) {
      for (const k of wanted) {
        (items[opened[k] as number] as { applied: boolean }).applied = true;
        item.applied = true;
        opened[k] = null;
      }
    } else if (wanted.every((k) => opened[k] === null) && item.canOpen) {
      for (const k of wanted) opened[k] = index;
    }
  });
  const runs: MarkedRun[] = [];
  let bold = false;
  let italic = false;
  const push = (words: string) => {
    const tail = runs[runs.length - 1];
    if (tail && tail.bold === bold && tail.italic === italic) tail.text += words;
    else if (words) runs.push({ text: words, bold, italic });
  };
  for (const item of items) {
    if ("text" in item) push(item.text);
    else if (item.applied && kinds[item.stars]) {
      for (const k of kinds[item.stars]) {
        if (k === "bold") bold = !bold;
        else italic = !italic;
      }
    } else push("*".repeat(item.stars));
  }
  return runs;
}

/**
 * `text` with the selection `start`..`end` wrapped in `marker` (`**` or `*`); with nothing selected the marker pair is written
 * and the caret left between them, so typing continues inside the mark.
 *
 * @param text The cell's text.
 * @param marker The mark to wrap in.
 * @param start Selection start; clamped to the text.
 * @param end Selection end; clamped to the text.
 * @returns The new text and the selection after it (the wrapped words, or the caret between the markers).
 */
export function wrapMark(text: string, marker: string, start: number, end: number): { text: string; start: number; end: number } {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  return {
    text: `${text.slice(0, from)}${marker}${text.slice(from, to)}${marker}${text.slice(to)}`,
    start: from + marker.length, end: to + marker.length,
  };
}

/**
 * What a cell prints for page 3 of 12 as marked stretches, or `null` when the cell holds neither a page field nor a mark
 * (nothing to show).
 *
 * @param text The cell's text.
 */
export function pageSample(text: string): MarkedRun[] | null {
  const marked = readMarks(text);
  const hasField = /\{\{\s*pages?\s*\}\}/.test(text);
  if (!hasField && !marked.some((run) => run.bold || run.italic)) return null;
  return marked.map((run) => ({
    ...run, text: run.text.replace(/\{\{\s*page\s*\}\}/g, SAMPLE_PAGE).replace(/\{\{\s*pages\s*\}\}/g, SAMPLE_PAGES),
  }));
}

/** The stretches of a sample as plain text. */
export function sampleText(runs: MarkedRun[]): string {
  return runs.map((run) => run.text).join("");
}

/**
 * The readable palette of a layout's text: the `name=colour` pairs of its `@palette` line (empty when it has none).
 *
 * @param text The layout text.
 */
export function readPalette(text: string): { name: string; colour: string }[] {
  const line = /^@palette\s+(.+)$/m.exec(text);
  if (!line || line[1].trim() === "follow") return [];
  return [...line[1].matchAll(/([a-z0-9_]+)=(\S+)/g)].map((m) => ({ name: m[1], colour: m[2] }));
}
