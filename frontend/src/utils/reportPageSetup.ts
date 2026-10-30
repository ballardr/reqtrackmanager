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
 * - `effectiveMargins`, `pageDimensionsCm`: the numbers a page sketch and a form's placeholders need, with the same
 *   defaults the server's renderers use.
 *
 * Design decisions: a heuristic reader of the lines it owns, not a parser (backend `services.report_layout_text` is
 * the parser). A line it cannot read leaves that part at its default, so the worst case is a form showing a default
 * for something the server then rejects with a positioned message.
 */
import type { LayoutFamily } from "../api/reportLayouts";

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

/** A named page style a section can use; what it leaves out is the layout's own. */
export interface PageStyleSetup {
  name: string;
  orientation?: PageOrientation;
  size?: PageSize;
  margins?: PageMargins;
}

/** A layout's page setup; the layout's own pages first, then its named styles. */
export interface PageSetup {
  orientation: PageOrientation;
  size: PageSize;
  mirror: boolean;
  margins: PageMargins;
  styles: PageStyleSetup[];
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

/** The page setup a layout's text states, or `null` when the text is not a document layout's (a table has no pages). */
export function readPageSetup(text: string): PageSetup | null {
  const lines = text.split("\n");
  const match = HEADER.exec(lines[0].trimEnd());
  if (!match) return null;
  const { before, margins } = split(match[1].trim().split(/\s+/).filter(Boolean));
  const { orientation, size } = readWords(before);
  return {
    orientation: orientation ?? "portrait",
    size: size ?? "A4",
    mirror: before.includes("mirror"),
    margins: readMargins(margins),
    styles: lines.slice(1).map((line) => STYLE_LINE.exec(line)).filter((m) => m !== null).map((m) => readStyle(m[1])),
  };
}

/** `text` with its `@layout document` line and its `@pagestyle` lines rewritten to state `setup`; defaults are left unwritten. */
export function writePageSetup(text: string, setup: PageSetup): string {
  const lines = text.split("\n");
  if (!HEADER.test(lines[0].trimEnd())) return text;
  const header = [
    "@layout document",
    ...(setup.orientation === "landscape" ? ["landscape"] : []),
    ...(setup.size === "A4" ? [] : [setup.size]),
    ...(setup.mirror ? ["mirror"] : []),
  ].join(" ") + marginsText(setup.margins);
  const styles = setup.styles.map((style) => {
    const words = [style.orientation, style.size].filter((word) => word !== undefined).join(" ");
    return `@pagestyle ${JSON.stringify(style.name)}${words ? ` ${words}` : ""}${marginsText(style.margins)}`;
  });
  return [header, ...styles, ...lines.slice(1).filter((line) => !STYLE_LINE.test(line))].join("\n");
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
  return style;
}

/** The editor's style as a `page_styles` entry of the tree. */
export function styleToTree(style: PageStyleSetup): Record<string, unknown> {
  const entry: Record<string, unknown> = { name: style.name };
  if (style.orientation) entry.orientation = style.orientation;
  if (style.size) entry.page_size = style.size;
  if (style.margins) entry.margins = style.margins;
  return entry;
}
