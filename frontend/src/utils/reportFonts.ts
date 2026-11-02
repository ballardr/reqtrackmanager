/**
 * Module: utils/reportFonts
 *
 * The facts about document fonts the designer needs without asking the server: the four standard fonts (the same keys as
 * `backend/app/services/report_fonts.py`) and the shape of a layout's stored `styles` value.
 *
 * Responsibilities: name the standard fonts for places that have no list from the server (a story, an older server), and
 * type the `styles` value. The server is the judge of what is valid and available.
 */
import type { ReportFontChoice } from "../api/reportLayouts";

/** The four standard fonts, offered when the server's list is not available. */
export const STANDARD_FONT_CHOICES: ReportFontChoice[] = [
  { key: "sans", label: "Sans", bundled: true, generic: "sans-serif" },
  { key: "serif", label: "Serif", bundled: true, generic: "serif" },
  { key: "mono", label: "Mono", bundled: true, generic: "monospace" },
  { key: "unicode", label: "Unicode Sans", bundled: true, generic: "sans-serif" },
];

/** A layout's stored `styles` value: every part and setting optional. */
export interface DocumentStyles {
  body?: { font?: string; size?: number };
  headings?: { font?: string; bold?: boolean; italic?: boolean; colour?: string };
}
