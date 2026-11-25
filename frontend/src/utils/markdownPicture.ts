/**
 * Module: utils/markdownPicture
 *
 * The one way a picture is written in, and read from, a record's Markdown text:
 * `![alt](attachment:<file id> "caption")`, where the file is an attachment of
 * the same record. `pictureMarkdown` writes it (escaping what would end the
 * alternative text or caption early); `attachmentFileId` and `PICTURE_START`
 * recognise it, so the reader, the editors and the round-trip checks agree.
 * Design: a picture is never an outside address, so opening a record makes no
 * request to another site and the file's own access rules (and confidential
 * mark) decide who sees it. Only the lower-case canonical id is an address, as
 * on the server (`services.markdown_text`). Alternative text and caption are one
 * line; a line break is written as a space.
 */

/** The address scheme of a picture that is an attachment of the record. */
export const ATTACHMENT_SCHEME = "attachment:";

/** The longest caption, in characters (equal to the server's `MAX_CAPTION_CHARS`). */
export const MAX_CAPTION_CHARS = 200;

const FILE_ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const ADDRESS = new RegExp(`^attachment:(${FILE_ID})$`);
const LABEL = String.raw`(?:[^\]\\\n]|\\.)*`;
const TITLE = String.raw`(?:[^"\\\n]|\\.)*`;

/**
 * A picture at the start of a text: the alternative text, the file id and the caption (groups 1 to 3).
 * The alternative text and the caption keep the backslash escapes they were written with (`unescapeLine`).
 */
export const PICTURE_START = new RegExp(String.raw`^!\[(${LABEL})\]\(attachment:(${FILE_ID})(?:\s+"(${TITLE})")?\)`);

/**
 * @param src The address of an image as the reader gives it.
 * @returns The attachment's file id, or `null` when the address is not an attachment picture.
 */
export function attachmentFileId(src: string): string | null {
  return ADDRESS.exec(src.trim())?.[1] ?? null;
}

/** @returns `text` as one line with `\` and the characters in `special` escaped. */
function escapeLine(text: string, special: RegExp): string {
  return text.replace(/\s*\n\s*/g, " ").replace(special, "\\$&");
}

/** @returns `text` with the backslash escapes `pictureMarkdown` added removed. */
export function unescapeLine(text: string): string {
  return text.replace(/\\(.)/g, "$1");
}

/**
 * @param fileId The attachment's file id.
 * @param alt The alternative text (may be empty).
 * @param caption The caption (may be empty; longer than `MAX_CAPTION_CHARS` is cut).
 * @returns The Markdown source of the picture.
 */
export function pictureMarkdown(fileId: string, alt: string, caption = ""): string {
  const label = escapeLine(alt.trim(), /[\\[\]]/g);
  const title = escapeLine(caption.trim().slice(0, MAX_CAPTION_CHARS), /[\\"]/g);
  return `![${label}](${ATTACHMENT_SCHEME}${fileId}${title ? ` "${title}"` : ""})`;
}
