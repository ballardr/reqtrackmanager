/**
 * Module: utils/visualMarkdown
 *
 * The Markdown vocabulary the visual editor (`VisualMarkdownEditor`) reads and writes, and the guard that keeps it
 * from changing a text it cannot hold.
 *
 * Responsibilities:
 * - Build the editor's extension set: paragraphs, headings, lists, quotations, emphasis, links, code, tables and a
 *   horizontal rule, with Markdown as the stored format (`@tiptap/markdown`).
 * - Correct the three places where the editor's Markdown writer changes meaning: a paragraph that starts like a
 *   block (`1.`, `#`, `-`, `>`), a code block whose text contains a fence, and an empty paragraph.
 * - Compare two Markdown texts by what the reader (`utils/markdownIt`) makes of them, so a round trip through the
 *   editor can be shown not to have changed the content (`findVisualBlocker`).
 *
 * Design decisions:
 * - The stored value is Markdown source, written by the editor only after a person edits. Opening a text never
 *   writes it back, and a text the editor cannot reproduce (HTML, an image, a footnote, a task list, mathematics, two
 *   adjacent lists with different markers) is reported as a blocker so the field stays in Write view.
 * - TipTap's paste rules for bold, italic, strike-through and code are off: they would format `**text**` the moment it
 *   is pasted, leaving the conversion offer (`VisualMarkdownEditor`) nothing to convert and no way to keep the text
 *   as typed. Typing `**text**` still formats through the input rules.
 * - "Equal" means the reader's tokens are equal, not the characters: `_a_` and `*a*`, `*` and `-` markers and a
 *   hard or soft line break all read the same, so a text is not blocked for a cosmetic difference.
 * - Mathematics is blocked outright because the writer escapes the underscores a formula needs.
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
import { Markdown } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";

import { parseMarkdown, SAFE_LINK } from "./markdownIt";

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
 * @returns The extensions of the visual Markdown editor.
 */
export function visualMarkdownExtensions(codeBlock: AnyExtension = MarkdownCodeBlock): AnyExtension[] {
  return [
    StarterKit.configure({
      underline: false, paragraph: false, codeBlock: false, bold: false, italic: false, strike: false, code: false,
      link: { openOnClick: false, autolink: false, linkOnPaste: true, isAllowedUri: (url) => SAFE_LINK.test(url), HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" } },
    }),
    ...InlineMarks,
    MarkdownParagraph,
    codeBlock,
    TableKit.configure({ table: { resizable: false } }),
    Markdown,
  ];
}

/**
 * Reduces Markdown to what the reader makes of it, ignoring markup that only changes how it is written.
 *
 * @param source Markdown text.
 * @returns One line per reader token (type, tag, content, link and fence details).
 */
export function readerSignature(source: string): string {
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
      const info = type === "fence" ? token.info.trim() : "";
      lines.push(`${type}|${depth}|${token.tag}|${attrs}|${info}|${content}`);
      if (token.children) walk(token.children, depth + 1);
    }
  };
  walk(parseMarkdown(source), 0);
  return lines.join("\n");
}

/** Whether the text holds dollar-delimited mathematics, which the editor's writer would change. */
export function containsMathematics(source: string): boolean {
  return /\$\$|\$[^$\n]+\$/.test(source);
}

/**
 * @param source The stored Markdown.
 * @param written What the editor wrote after reading `source` (its `getMarkdown()`).
 * @returns Why the text cannot be edited visually, or null when the editor holds it without change.
 */
export function findVisualBlocker(source: string, written: string): VisualBlocker | null {
  if (containsMathematics(source)) return "mathematics";
  return readerSignature(source) === readerSignature(written) ? null : "unsupported";
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
 * @returns What the editor writes for it.
 */
export function roundTripMarkdown(source: string): string {
  const editor = new Editor({ extensions: visualMarkdownExtensions(), content: source, contentType: "markdown" });
  try {
    return writtenMarkdown(editor);
  } finally {
    editor.destroy();
  }
}
