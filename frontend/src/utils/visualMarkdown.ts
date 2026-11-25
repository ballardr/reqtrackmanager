/**
 * Module: utils/visualMarkdown
 *
 * The Markdown vocabulary the visual editor (`VisualMarkdownEditor`) reads and writes, and the guard that keeps it
 * from changing a text it cannot hold.
 *
 * Responsibilities:
 * - Build the editor's extension set with Markdown as the stored format (`@tiptap/markdown`).
 * - Correct the places where the editor's Markdown writer changes meaning: a paragraph that starts like a block
 *   (`1.`, `#`, `-`, `>`), a code block whose text contains a fence, and an empty paragraph.
 * - Compare two texts by what the reader (`utils/markdownIt`) makes of them, so a round trip can be shown not to have
 *   changed the content (`findVisualBlocker`).
 *
 * Design decisions:
 * - Opening a text never writes it back; a text the editor cannot reproduce (HTML, an outside image, a footnote, a task
 *   list, mathematics outside a maths field, adjacent lists with different markers) is a blocker, so the field stays
 *   in Write view. An attachment picture (`utils/visualImageNode`) is an atom, not a blocker.
 * - TipTap's paste rules for bold, italic, strike-through and code are off: they would format `**text**` on paste and
 *   leave the conversion offer nothing to convert. Typing `**text**` still formats through the input rules.
 * - "Equal" means equal reader tokens, so `_a_` and `*a*`, `*` and `-` markers and hard or soft breaks do not block.
 * - In a maths field an equation is an atom (`utils/visualMathNode`) the writer never escapes; elsewhere mathematics is
 *   blocked, because the writer would escape the underscores a formula needs.
 *
 * Dependencies: TipTap (MIT), `utils/markdownIt`.
 */
import type { AnyExtension, Editor as TipTapEditor } from "@tiptap/core";
import { Editor } from "@tiptap/core";
import Bold from "@tiptap/extension-bold";
import Code from "@tiptap/extension-code";
import CodeBlock from "@tiptap/extension-code-block";
import Italic from "@tiptap/extension-italic";
import Paragraph from "@tiptap/extension-paragraph";
import Strike from "@tiptap/extension-strike";
import { TableKit } from "@tiptap/extension-table";
import { Placeholder } from "@tiptap/extensions";
import { Markdown } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";

import { parseMarkdown, SAFE_LINK } from "./markdownIt";
import { PictureNode } from "./visualImageNode";
import { MathNode } from "./visualMathNode";

/** Why a text cannot be edited visually: it has mathematics, or formatting the editor would change. */
export type VisualBlocker = "mathematics" | "unsupported";

const ORDERED_MARKER = /^(\s*)(\d{1,9})([.)])(?=\s|$)/;
const BLOCK_MARKER = /^(\s*)(#{1,6}(?=\s|$)|[-+*>](?=\s|$)|[-=]+\s*$|~{3,}|`{3,})/;

/**
 * Escapes a line that would otherwise start a block (a heading, list, quotation, rule or fence) when read back.
 *
 * @param line One line of a paragraph's written text.
 * @returns The line with its first marker character escaped, or the line unchanged.
 */
export function escapeBlockMarker(line: string): string {
  return line
    .replace(ORDERED_MARKER, "$1$2\\$3")
    .replace(BLOCK_MARKER, (_match, space: string, mark: string) => `${space}\\${mark}`);
}

/**
 * @param body The text of a code block.
 * @returns A fence one backtick longer than the longest run in the text (at least three), so the text cannot close it.
 */
export function fenceFor(body: string): string {
  const longest = Math.max(2, ...Array.from(body.matchAll(/`+/g), (match) => match[0].length));
  return "`".repeat(longest + 1);
}

/** The paragraph, writing an empty one as nothing and escaping a line that would start a block. */
export const MarkdownParagraph = Paragraph.extend({
  renderMarkdown: (node, helpers) => {
    const content = Array.isArray(node.content) ? node.content : [];
    if (content.length === 0) return "";
    return helpers.renderChildren(content).split("\n").map(escapeBlockMarker).join("\n");
  },
});

/** The code block, writing the longest fence its text needs. */
export const MarkdownCodeBlock = CodeBlock.extend({
  renderMarkdown: (node, helpers) => {
    const language = typeof node.attrs?.language === "string" ? node.attrs.language : "";
    const body = node.content ? helpers.renderChildren(node.content) : "";
    const fence = fenceFor(body);
    return `${fence}${language}\n${body}\n${fence}`;
  },
});

/** Inline marks without TipTap's paste rules, so pasted `**text**` stays as typed until the person converts it. */
const InlineMarks = [Bold, Italic, Strike, Code].map((mark) => mark.extend({ addPasteRules: () => [] }));

/**
 * @param codeBlock The code block extension (the editor passes one with its diagram view).
 * @param mathNode The equation node, for a field that holds mathematics (the editor passes one with its view); none
 *   leaves equations as ordinary text.
 * @param pictureNode The picture node (the editor passes one with its view).
 * @param placeholder The field's hint, drawn while the document is empty.
 * @returns The extensions of the visual Markdown editor.
 */
export function visualMarkdownExtensions(
  codeBlock: AnyExtension = MarkdownCodeBlock, mathNode: AnyExtension | null = null, pictureNode: AnyExtension = PictureNode,
  placeholder = "",
): AnyExtension[] {
  return [
    StarterKit.configure({
      underline: false, paragraph: false, codeBlock: false, bold: false, italic: false, strike: false, code: false,
      link: { openOnClick: false, autolink: false, linkOnPaste: true, isAllowedUri: (url) => SAFE_LINK.test(url), HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" } },
    }),
    ...InlineMarks,
    MarkdownParagraph,
    codeBlock,
    TableKit.configure({ table: { resizable: false } }),
    ...(mathNode ? [mathNode] : []),
    pictureNode,
    // The field's hint, drawn while the document is empty (the Write view's own placeholder).
    Placeholder.configure({ placeholder }),
    Markdown,
  ];
}

/**
 * Reduces Markdown to what the reader makes of it, ignoring markup that only changes how it is written.
 *
 * @param source Markdown text.
 * @param math Whether the reader also reads equations (a field that holds mathematics).
 * @returns One line per reader token (type, tag, content, link and fence details).
 */
export function readerSignature(source: string, math = false): string {
  const lines: string[] = [];
  const walk = (tokens: ReturnType<typeof parseMarkdown>, depth: number) => {
    for (const token of tokens) {
      const type = token.type === "softbreak" ? "hardbreak" : token.type === "code_block" ? "fence" : token.type;
      const last = lines.length - 1;
      if (type === "text" && last >= 0 && lines[last].startsWith(`text|${depth}|`)) {
        lines[last] += token.content;
        continue;
      }
      const attrs = (token.attrs ?? []).filter(([name]) => name !== "rel" && name !== "target").map(([name, value]) => `${name}=${value}`).join(",");
      const content = type === "inline" ? "" : type === "fence" ? token.content.replace(/\n$/, "") : token.content;
      const info = type === "fence" ? token.info.trim() : type === "math" ? String((token.meta as { display?: boolean } | null)?.display) : "";
      lines.push(`${type}|${depth}|${token.tag}|${attrs}|${info}|${content}`);
      if (token.children) walk(token.children, depth + 1);
    }
  };
  walk(parseMarkdown(source, { math }), 0);
  return lines.join("\n");
}

/** Whether the text holds mathematics (`$$ x $$`, `$x$` or `\( x \)`), which the editor's writer would change. */
export function containsMathematics(source: string): boolean {
  return /\$\$|\$[^$\n]+\$|\\\(/.test(source);
}

/**
 * @param source The stored Markdown.
 * @param written What the editor wrote after reading `source` (its `getMarkdown()`).
 * @param math Whether the field holds mathematics, so the editor has the equation node and an equation is not a blocker.
 * @returns Why the text cannot be edited visually, or null when the editor holds it without change.
 */
export function findVisualBlocker(source: string, written: string, math = false): VisualBlocker | null {
  if (!math && containsMathematics(source)) return "mathematics";
  return readerSignature(source, math) === readerSignature(written, math) ? null : "unsupported";
}

/**
 * @param text Plain text that was pasted.
 * @returns Whether it contains Markdown syntax worth offering to convert (a heading, list, quotation, fence, table row,
 *   emphasis, inline code or link).
 */
export function looksLikeMarkdown(text: string): boolean {
  return /^ {0,3}(#{1,6}\s|[-*+]\s|\d{1,9}[.)]\s|>\s|```|~~~|\|.+\|)/m.test(text) || /\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\)/.test(text);
}

/** @returns The Markdown the editor writes (trailing blank lines removed). */
export function writtenMarkdown(editor: TipTapEditor): string {
  return editor.getMarkdown().replace(/\s+$/, "");
}

/**
 * Reads a text into a detached editor and writes it back, as the visual editor does on opening and after an edit.
 *
 * @param source Markdown text.
 * @param math Whether the editor has the equation node (a field that holds mathematics).
 * @returns What the editor writes for it.
 */
export function roundTripMarkdown(source: string, math = false): string {
  const editor = new Editor({ extensions: visualMarkdownExtensions(MarkdownCodeBlock, math ? MathNode : null), content: source, contentType: "markdown" });
  try {
    return writtenMarkdown(editor);
  } finally {
    editor.destroy();
  }
}
