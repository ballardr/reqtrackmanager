/**
 * Module: utils/markdownIt
 *
 * The one Markdown reader the interface uses (markdown-it), configured for
 * untrusted text: parses source into tokens for `MarkdownView` (which makes React
 * elements), decides what may be a link and which fenced block is a Mermaid
 * diagram, and optionally reads equations (`utils/markdownMath`).
 * Design: raw HTML is off (read as text) and nothing here produces HTML, so a
 * stored value cannot run as markup. A link must be https, http or mailto; any
 * other address is left as typed, except a picture of the record's own
 * attachment (`attachment:<file id>`, `utils/markdownPicture`), which only
 * `MarkdownView` draws, as an image. A single line break is kept (`breaks`), and
 * nesting is capped at the reader's limit of 100 levels (the server's validation
 * refuses deeper), so a hostile document cannot exhaust the stack.
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
