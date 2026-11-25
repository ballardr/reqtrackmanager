/**
 * Module: utils/tableHeadingColours
 *
 * How a table heading row is coloured, for the places that draw a sample of it.
 *
 * Responsibilities: `tableHeadingColours` resolves a layout's heading fill (else the organisation's accent) and text
 * colour (else black or white by contrast) as the renderers do (`DocumentStyles.table_head_colours`).
 *
 * Design decisions: this mirrors the server's rule only so a sample can show the result before a run. An unknown or
 * unreadable word falls back to the default rather than throwing.
 */
import { contrastTextHex } from "./color";
import { resolveColourWord, type ColourContext, type ColourEntry } from "./reportColours";
import type { TableHeadings } from "./reportPageSetup";

/**
 * @param headings The layout's two colour words.
 * @param context The branding colour and the organisation's scheme.
 * @param palette The layout's own scheme.
 * @returns The heading fill and text colour as `#rrggbb`.
 */
export function tableHeadingColours(
  headings: TableHeadings, context: ColourContext, palette: ColourEntry[] = [],
): { fill: string; text: string } {
  const fill = (headings.fill ? resolveColourWord(headings.fill, context, palette) : null) ?? context.accent;
  const text = (headings.text ? resolveColourWord(headings.text, context, palette) : null) ?? contrastTextHex(fill);
  return { fill, text };
}
