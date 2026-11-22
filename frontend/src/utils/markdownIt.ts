/**
 * Module: utils/markdownIt
 *
 * The one Markdown reader the interface uses (markdown-it), configured for text that is never trusted.
 *
 * Responsibilities:
 * - Parse Markdown source into tokens for `MarkdownView`, which turns them into React elements.
 * - Decide what may be a link and which fenced block is a Mermaid diagram.
 * - Optionally read equations (`utils/markdownMath`), for the fields that hold mathematics.
 *
 * Design decisions:
 * - Raw HTML is off (it is read as text), and nothing here produces HTML: the reader's tokens are the only output,
 *   so a stored value can never run as markup.
 * - A link must be https, http or mailto; any other address (a script, a relative path) is left as the text typed. The one
 *   other address the reader accepts is a picture of the record's own attachment (`attachment:<file id>`,
 *   `utils/markdownPicture`), which only `MarkdownView` draws, and only as an image: as a link it is shown as its text.
 * - A single line break is kept (`breaks`), because existing plain text relied on it, and nesting is capped at the
 *   reader's own limit of 100 levels (deeper content is not read, which the server's validation refuses), so a
 *   hostile document cannot exhaust the stack.
 *
 * Dependencies: `markdown-it` (MIT).
 */
import MarkdownItReader, { type MarkdownIt, type Token } from "markdown-it";

import { mathPlugin } from "./markdownMath";
import { attachmentFileId } from "./markdownPicture";

/** Addresses that may be a link. */
export const SAFE_LINK = /^(https?:|mailto:)/i;

function createReader(): MarkdownIt {
  const instance = new MarkdownItReader({ html: false, linkify: false, breaks: true, typographer: false, maxNesting: 100 });
  instance.validateLink = (url) => SAFE_LINK.test(url.trim()) || attachmentFileId(url) !== null;
  return instance;
}

const reader = createReader();
// A second reader that also reads equations, for the fields where people write them (`MarkdownField.math`).
const mathReader = createReader();
mathReader.use(mathPlugin);

/**
 * @param source Markdown text, as stored.
 * @param options `math`: also read `\( x \)` and `$$ x $$` as equations (`math` tokens).
 * @returns The block tokens of the document (inline content is in each `inline` token's `children`).
 */
export function parseMarkdown(source: string, options: { math?: boolean } = {}): Token[] {
  return (options.math ? mathReader : reader).parse(source.replace(/\r\n?/g, "\n"), {});
}

/** Whether a fenced block is a Mermaid diagram (its info string starts with `mermaid`). */
export function isMermaidFence(token: Token): boolean {
  return token.type === "fence" && token.info.trim().split(/\s+/)[0]?.toLowerCase() === "mermaid";
}

export type { Token };
