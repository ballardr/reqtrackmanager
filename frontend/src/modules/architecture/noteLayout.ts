/**
 * Module: modules/architecture/noteLayout
 *
 * The layout of an annotation note's text on a diagram: where its lines break and, for an Automatic size, the frame holding
 * them. Pure functions, no React.
 * - `noteLines`: breaks the bold title and the text at an inner width, keeping typed line breaks (a blank line stays one
 *   empty line) and wrapping between words only.
 * - `automaticFrame`: the widest line and the line count with `NOTE_PADDING` around them, wrapped at `NOTE_MAX_WIDTH` (a
 *   single wider word is kept whole and sets the width). `drawnSize`: that frame for an Automatic note with content, else the
 *   stored size (an empty note keeps it, as the editor shows the placeholder). A toned note's caption adds `NOTE_CAPTION_HEIGHT`.
 * - The server draws the same lines with `diagram_note_layout.py`; `noteLayoutCases.json` holds the cases both are tested
 *   against, so a change is made in both. Widths come from the symbol label's width table (wider than system glyphs), so a
 *   note may draw a little larger than its text needs and never smaller; the title is measured `TITLE_PERCENT` wider.
 */

import { textWidth, wrapLabel } from "./symbolLabelLayout";
import type { NoteSizeMode, NoteTone } from "./types";

/** The font size and line height a note's text is drawn at (canvas units). */
export const NOTE_FONT_SIZE = 13;
export const NOTE_LINE_HEIGHT = 16;

/** The distance from a note's frame to its text, on every side (canvas units, borders included). */
export const NOTE_PADDING = 6;

/** The widest an Automatic note's text is wrapped to, the narrowest its frame is drawn, and the height of the caption row. */
export const NOTE_MAX_WIDTH = 320;
export const NOTE_MIN_WIDTH = 48;
export const NOTE_CAPTION_HEIGHT = 14;

/** How much wider (percent) the bold title is measured than regular text. */
export const TITLE_PERCENT = 110;

/** The lines a note draws, top to bottom. */
export interface NoteLines {
  /** The title's lines (bold), none when there is no title. */
  title: string[];
  /** The text's lines, an empty string for a blank line the person typed. */
  text: string[];
}

/** @param text A note's text. @returns It as drawn: line endings made `\n`, leading line breaks and trailing whitespace dropped. */
export function cleanText(text: string): string {
  return text.replace(/\r\n?/g, "\n").replace(/^\n+/, "").trimEnd();
}

/** @param title A note's title. @returns It as drawn: one line, its whitespace collapsed. */
export function cleanTitle(title: string): string {
  return title.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * @param text A note's text, already cleaned.
 * @param limit The widest a line may be, in thousandths of a unit.
 * @returns The text wrapped to `limit`, each typed line on its own and a blank line kept as an empty line.
 */
function paragraphs(text: string, limit: number): string[] {
  const out: string[] = [];
  for (const paragraph of text.split("\n")) {
    const wrapped = wrapLabel(paragraph, limit, NOTE_FONT_SIZE);
    out.push(...(wrapped.length > 0 ? wrapped : [""]));
  }
  return out;
}

/**
 * The lines a note draws at a given width.
 *
 * @param title The note's title (may be empty).
 * @param text The note's text (may be empty).
 * @param innerWidth The width available to the text, in canvas units (the frame's width less its padding).
 * @returns The title's lines and the text's lines, wrapped between words, the typed line breaks kept.
 */
export function noteLines(title: string, text: string, innerWidth: number): NoteLines {
  const limit = Math.max(innerWidth, 1) * 1000;
  const head = cleanTitle(title);
  const body = cleanText(text);
  return {
    title: head ? wrapLabel(head, limit, NOTE_FONT_SIZE, TITLE_PERCENT) : [],
    text: body ? paragraphs(body, limit) : [],
  };
}

/** @returns The widest line, in whole canvas units rounded up. */
function widest(lines: NoteLines): number {
  const widths = [
    ...lines.title.map((line) => textWidth(line, NOTE_FONT_SIZE, TITLE_PERCENT)),
    ...lines.text.map((line) => textWidth(line, NOTE_FONT_SIZE)),
  ];
  return Math.floor((Math.max(0, ...widths) + 999) / 1000);
}

/**
 * The frame that holds a note's content.
 *
 * @param title The note's title.
 * @param text The note's text.
 * @param hasCaption Whether the note draws a caption under its text (a toned note does).
 * @returns The width and height in canvas units, or null when the note has neither title nor text.
 */
export function automaticFrame(title: string, text: string, hasCaption: boolean): { width: number; height: number } | null {
  const lines = noteLines(title, text, NOTE_MAX_WIDTH - 2 * NOTE_PADDING);
  const count = lines.title.length + lines.text.length;
  if (count === 0) return null;
  return {
    width: Math.max(NOTE_MIN_WIDTH, widest(lines) + 2 * NOTE_PADDING),
    height: count * NOTE_LINE_HEIGHT + 2 * NOTE_PADDING + (hasCaption ? NOTE_CAPTION_HEIGHT : 0),
  };
}

/**
 * The size a note is drawn at.
 *
 * @param note The note's size mode, tone, title, text and stored width and height.
 * @returns The computed frame for an Automatic note with a title or text, else the stored width and height.
 */
export function drawnSize(
  note: { sizeMode: NoteSizeMode; tone: NoteTone; title: string; text: string; width: number; height: number },
): { width: number; height: number } {
  if (note.sizeMode === "automatic") {
    const frame = automaticFrame(note.title, note.text, note.tone !== "none");
    if (frame) return frame;
  }
  return { width: note.width, height: note.height };
}
