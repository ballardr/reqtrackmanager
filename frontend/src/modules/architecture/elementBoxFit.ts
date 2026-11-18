/**
 * Module: modules/architecture/elementBoxFit
 *
 * The least size an element box on a block diagram needs to show its symbol, its code line and its name whole. Pure functions,
 * no React.
 *
 * Responsibilities:
 * - Break a box's name into lines at the width the box is drawn at, between words only (`fitBox`), and total the height of the
 *   symbol, the name's lines and the caption line with the box's insets.
 * - Give the size a box is drawn at (`drawnBoxSize`): the larger of the stored size and that fit, in each direction.
 *
 * Design decisions:
 * - The stored size is never rewritten. A symbol is set on an element, on its type, or changed on the type later, which touches
 *   boxes on diagrams nobody has open, so the fit is computed wherever a box is read and the stored width and height stay what
 *   the person last drew.
 * - The server draws the same frame with a Python copy (`diagram_box_fit.py`); `elementBoxFitCases.json` holds the cases both
 *   are tested against, so a change is made in both. Widths come from the symbol label's width table (wider than the system
 *   fonts' glyphs), so a box may draw a little larger than its text needs and never smaller; the name is measured at the bold
 *   factor because the exports draw it bold.
 * - The symbol has a fixed height (`SYMBOL_HEIGHT`) rather than a share of the box, so the height is a plain sum and a taller
 *   box leaves room, never a larger symbol.
 */

import { textWidth, wrapLabel } from "./symbolLabelLayout";

/** The least a box is drawn: the resize handles' minimum (canvas units). */
export const BOX_MIN_WIDTH = 80;
export const BOX_MIN_HEIGHT = 40;

/** The distance from the frame's edge to the content: the left edge has a 4-unit accent border, the others a 1-unit border, each inside 6 units of padding. */
export const INSET_LEFT = 10;
export const INSET_RIGHT = 7;
export const INSET_Y = 7;

/** The height of the symbol and the gap under it. */
export const SYMBOL_HEIGHT = 40;
export const SYMBOL_GAP = 4;

/** The name's font size, its line height and the factor it is measured wider by (the exports draw it bold). */
export const NAME_FONT_SIZE = 13;
export const NAME_LINE_HEIGHT = 16;
export const NAME_PERCENT = 110;

/** The caption's (code and type) font size and line height. */
export const CAPTION_FONT_SIZE = 11;
export const CAPTION_LINE_HEIGHT = 17;

/** What a box needs. */
export interface BoxFit {
  /** The least width that shows every word and the caption whole. */
  minWidth: number;
  /** The least height at the width the box is drawn at (the larger of the stored width and `minWidth`). */
  minHeight: number;
  /** The name's lines at that width. */
  lines: string[];
}

/** @param thousandths A width in thousandths of a unit. @returns It in whole units, rounded up. */
function units(thousandths: number): number {
  return Math.floor((thousandths + 999) / 1000);
}

/**
 * The least size a box needs.
 *
 * @param hasSymbol Whether the box draws a symbol.
 * @param caption The small line under the name (the code and the type); empty for none.
 * @param name The element's name.
 * @param width The box's stored width, which the name's lines are broken for.
 * @returns The least width, the least height at the drawn width and the name's lines.
 */
export function fitBox(hasSymbol: boolean, caption: string, name: string, width: number): BoxFit {
  const longestWord = Math.max(0, ...wrapLabel(name, 1, NAME_FONT_SIZE, NAME_PERCENT).map((line) => textWidth(line, NAME_FONT_SIZE, NAME_PERCENT)));
  const captionWidth = caption ? textWidth(caption, CAPTION_FONT_SIZE) : 0;
  const content = Math.max(units(longestWord), units(captionWidth), hasSymbol ? SYMBOL_HEIGHT : 0);
  const minWidth = Math.max(BOX_MIN_WIDTH, content + INSET_LEFT + INSET_RIGHT);
  const drawnWidth = Math.max(width, minWidth);
  const lines = wrapLabel(name, Math.trunc((drawnWidth - INSET_LEFT - INSET_RIGHT) * 1000), NAME_FONT_SIZE, NAME_PERCENT);
  const height = 2 * INSET_Y + lines.length * NAME_LINE_HEIGHT + (hasSymbol ? SYMBOL_HEIGHT + SYMBOL_GAP : 0) + (caption ? CAPTION_LINE_HEIGHT : 0);
  return { minWidth, minHeight: Math.max(BOX_MIN_HEIGHT, height), lines };
}

/**
 * The size a box is drawn at.
 *
 * @param hasSymbol Whether the box draws a symbol.
 * @param caption The small line under the name.
 * @param name The element's name.
 * @param width The stored width.
 * @param height The stored height.
 * @returns The stored size, made larger in either direction where the content needs it.
 */
export function drawnBoxSize(hasSymbol: boolean, caption: string, name: string, width: number, height: number): { width: number; height: number } {
  const fit = fitBox(hasSymbol, caption, name, width);
  return { width: Math.max(width, fit.minWidth), height: Math.max(height, fit.minHeight) };
}
