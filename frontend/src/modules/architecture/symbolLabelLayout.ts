/**
 * Module: modules/architecture/symbolLabelLayout
 *
 * The layout of the label drawn inside an initial, final or choice symbol of a state machine diagram: where its lines break and
 * how large the symbol must be to hold them. Pure functions, no React.
 * - `textWidth` measures with a fixed, font-independent table of average glyph widths in thousandths of the font size
 *   (integers only), set wider than the system fonts' glyphs so real text keeps its padding. Notes (`noteLayout`) use the
 *   same table, so every text on a diagram breaks at the same words on screen and in exports.
 * - `wrapLabel` breaks between words only (spaces, after a hyphen, between East Asian characters, typed line breaks).
 * - `fitLabel` grows the symbol in steps until the text block, centred on it, is at least `LABEL_PADDING` from the inner edge
 *   of the circle, disc or diamond (integers). `besideLabel` keeps the plain symbol and places the block against one side,
 *   `LABEL_PADDING` from the outer edge, wrapped to `BESIDE_MAX_WIDTH`; its offset may be negative.
 * - A word longer than the largest symbol's text area stays whole at the largest size and `fits` is false so the Selection card
 *   can warn; it is never broken or clipped.
 * The server draws the same lines with `diagram_symbol_label.py`; `symbolLabelCases.json` holds the cases both are tested
 * against, so a change is made in both.
 */

import type { StateMarkerKind } from "./stateShapes";
import type { LabelPosition } from "./types";

/** The label's font size and line height (canvas units). */
export const LABEL_FONT_SIZE = 10;
export const LABEL_LINE_HEIGHT = 12;

/** The smallest labelled symbol of each kind (its square frame). */
export const BASE_SIZE: Record<StateMarkerKind, number> = { initial: 52, final: 72, choice: 96 };

/** The share of a symbol's size a line is first wrapped to, in percent. */
export const TEXT_PERCENT: Record<StateMarkerKind, number> = { initial: 56, final: 42, choice: 40 };

/** The least distance (canvas units) between text and a symbol's edge: inside it from the inner edge, outside from the outer edge. */
export const LABEL_PADDING = 4;

/** The step a symbol grows by while its label does not fit, and the largest size. */
export const SIZE_STEP = 4;
export const MAX_SIZE = 320;

/** The widest a label placed outside its symbol is first wrapped to (canvas units); a single longer word is kept whole. */
export const BESIDE_MAX_WIDTH = 160;

/**
 * Glyph widths in thousandths of the font size, set above what the product's system font stack draws (measured with the browser's
 * canvas in the system UI font, Arial, Helvetica and Roboto; the widest rendered label was 7% under the table), so the real text
 * keeps its padding.
 */
const SPACE = 320;
const NARROW = 340;
const CAPITAL = 740;
const WIDE = 1000;
const FULL = 1000;
const OTHER = 620;
const NARROW_GLYPHS = new Set("iljtfI.,:;'|!()[]/\\");
const WIDE_GLYPHS = new Set("MWmw@%");
/** Code point ranges drawn full width, and so broken between any two characters. */
const FULL_WIDTH: ReadonlyArray<readonly [number, number]> = [
  [0x1100, 0x11ff], [0x2e80, 0xa4cf], [0xac00, 0xd7af], [0xf900, 0xfaff], [0xfe30, 0xfe6f], [0xff00, 0xff60], [0xffe0, 0xffe6],
];

/** The drawing of a label inside its symbol. */
export interface SymbolLabelLayout {
  /** The side of the square symbol that holds the label (a multiple of `SIZE_STEP`). */
  size: number;
  /** The label's lines, top to bottom. */
  lines: string[];
  /** False when the text does not fit the largest symbol with its padding (a word longer than its text area is drawn whole, wider than the symbol). */
  fits: boolean;
}

function isFullWidth(char: string): boolean {
  const code = char.codePointAt(0) ?? 0;
  return FULL_WIDTH.some(([low, high]) => code >= low && code <= high);
}

function glyph(char: string): number {
  if (char === " ") return SPACE;
  if (NARROW_GLYPHS.has(char)) return NARROW;
  if (WIDE_GLYPHS.has(char)) return WIDE;
  if (char >= "A" && char <= "Z") return CAPITAL;
  return isFullWidth(char) ? FULL : OTHER;
}

/**
 * The width a text takes at a font size (by default the label's).
 *
 * @param text Plain text.
 * @param fontSize The font size in canvas units (annotation notes measure at their own size, with this one table).
 * @param percent A width factor in percent (bold text is measured wider than regular text).
 * @returns The width in thousandths of a canvas unit (an integer).
 */
export function textWidth(text: string, fontSize = LABEL_FONT_SIZE, percent = 100): number {
  let total = 0;
  for (const char of text) total += glyph(char);
  return Math.floor((total * fontSize * percent) / 100);
}

/** The pieces a paragraph may be broken into, each with the separator that joins it to the one before. */
function pieces(paragraph: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const word of paragraph.split(/\s+/).filter(Boolean)) {
    const parts: string[] = [];
    let current = "";
    for (const char of word) {
      if (isFullWidth(char)) {
        if (current) parts.push(current);
        parts.push(char);
        current = "";
        continue;
      }
      current += char;
      if (char === "-") {
        parts.push(current);
        current = "";
      }
    }
    if (current) parts.push(current);
    parts.forEach((part, index) => out.push([index === 0 && out.length > 0 ? " " : "", part]));
  }
  return out;
}

/**
 * Break a label into lines, between words only.
 *
 * @param label The label text; a line break the person typed starts a new line.
 * @param limit The widest a line may be, in thousandths of a canvas unit.
 * @param fontSize The font size the text is measured at (see `textWidth`).
 * @param percent The width factor the text is measured with (see `textWidth`).
 * @returns The lines, none empty. A word wider than `limit` is kept whole on a line of its own.
 */
export function wrapLabel(label: string, limit: number, fontSize = LABEL_FONT_SIZE, percent = 100): string[] {
  const lines: string[] = [];
  for (const paragraph of label.replace(/\r\n?/g, "\n").split("\n")) {
    let current = "";
    let currentWidth = 0;
    for (const [separator, part] of pieces(paragraph)) {
      const partWidth = textWidth(part, fontSize, percent);
      const separatorWidth = textWidth(separator, fontSize, percent);
      if (current && currentWidth + separatorWidth + partWidth > limit) {
        lines.push(current);
        current = part;
        currentWidth = partWidth;
      } else if (current) {
        current += separator + part;
        currentWidth += separatorWidth + partWidth;
      } else {
        current = part;
        currentWidth = partWidth;
      }
    }
    if (current) lines.push(current);
  }
  return lines;
}

/**
 * Whether a symbol of `size` holds the lines with `LABEL_PADDING` clear of its inner edge.
 *
 * @param kind The marker kind.
 * @param size The side of the square frame.
 * @param lines The label's lines.
 * @returns True when the corner of the text block nearest the edge is at least `LABEL_PADDING` inside it.
 */
export function holds(kind: StateMarkerKind, size: number, lines: string[]): boolean {
  const width = Math.max(...lines.map((line) => textWidth(line))); // thousandths of a unit
  const height = lines.length * LABEL_LINE_HEIGHT * 1000;
  const half = Math.floor(size / 2);
  if (kind === "choice") {
    // The diamond's inner edge is |x| + |y| = half - 2 (inside the 2-unit stroke); the corner must be LABEL_PADDING from it at
    // right angles, i.e. slack >= padding * sqrt(2) (compared squared).
    const slack2 = (half - 2) * 2000 - (width + height);
    return slack2 >= 0 && slack2 * slack2 >= 8_000_000 * LABEL_PADDING * LABEL_PADDING;
  }
  // A circle: the dot's radius, or the final state's inner disc (the text sits on the disc).
  const radius = kind === "initial" ? half - 1 : Math.floor((26 * size + 36) / 72);
  const room = radius - LABEL_PADDING;
  return room > 0 && width * width + height * height <= 4 * room * room * 1_000_000;
}

/** The width a line is first tried at in a symbol of `size`: the side of the square that fits it (canvas units, whole). */
export function textSide(kind: StateMarkerKind, size: number): number {
  return Math.floor((size * TEXT_PERCENT[kind]) / 100);
}

/**
 * The smallest symbol that holds a label, and the lines drawn in it.
 *
 * @param kind The marker kind.
 * @param label The symbol's label.
 * @returns The size and lines, or null when the label is blank (no label, so the symbol keeps its plain size).
 */
export function fitLabel(kind: StateMarkerKind, label: string): SymbolLabelLayout | null {
  const text = label.trim();
  if (!text) return null;
  for (let size = BASE_SIZE[kind]; size <= MAX_SIZE; size += SIZE_STEP) {
    const lines = wrapLabel(text, textSide(kind, size) * 1000);
    if (holds(kind, size, lines)) return { size, lines, fits: true };
  }
  return { size: MAX_SIZE, lines: wrapLabel(text, textSide(kind, MAX_SIZE) * 1000), fits: false };
}

/** The drawing of a label placed outside its symbol. */
export interface BesideLayout {
  /** The label's lines, top to bottom. */
  lines: string[];
  /** The text block's left edge, relative to the symbol's top left corner (negative to its left). */
  x: number;
  /** The text block's top edge, relative to the symbol's top left corner (negative above it). */
  y: number;
  /** The widest line (a whole number of units, from the width table). */
  width: number;
  /** The block's height (lines times the line height). */
  height: number;
  /** How the lines are aligned within the block, toward the symbol. */
  align: "left" | "center" | "right";
}

/**
 * Where a label sits when it is outside its symbol.
 *
 * @param label The symbol's label.
 * @param position `left`, `right`, `above` or `below` (`inside` is not a place outside, see `fitLabel`).
 * @param symbolWidth The width of the symbol's own box.
 * @param symbolHeight The height of the symbol's own box.
 * @returns The lines and the text block's place relative to the symbol's top left corner, or null when the label is blank or the
 *   position is `inside`. The block is `LABEL_PADDING` from the symbol's edge on its side and centred along it.
 */
export function besideLabel(label: string, position: LabelPosition, symbolWidth: number, symbolHeight: number): BesideLayout | null {
  const text = label.trim();
  if (!text || position === "inside") return null;
  const lines = wrapLabel(text, BESIDE_MAX_WIDTH * 1000);
  const width = Math.floor((Math.max(...lines.map((line) => textWidth(line))) + 999) / 1000);
  const height = lines.length * LABEL_LINE_HEIGHT;
  if (position === "right") return { lines, x: symbolWidth + LABEL_PADDING, y: (symbolHeight - height) / 2, width, height, align: "left" };
  if (position === "left") return { lines, x: -(LABEL_PADDING + width), y: (symbolHeight - height) / 2, width, height, align: "right" };
  if (position === "above") return { lines, x: (symbolWidth - width) / 2, y: -(LABEL_PADDING + height), width, height, align: "center" };
  return { lines, x: (symbolWidth - width) / 2, y: symbolHeight + LABEL_PADDING, width, height, align: "center" };
}
