/**
 * Module: utils/markdownPlain
 *
 * The readable words of a Markdown text, with no marks, for a place that shows one line of it (a summary card, a list
 * cell, a tooltip). The browser counterpart of the server's `services.markdown_text.plain_text`, which a list, search
 * snippet or notification uses, so the two read a text the same way.
 *
 * Responsibilities:
 * - Read the text with the product's reader (`parseMarkdown`) and join the words of every block with single spaces;
 *   a diagram is named `[Diagram]`, a fenced block keeps its text, an equation keeps its TeX, a picture is its
 *   alternative text.
 *
 * Design decisions:
 * - Nothing here produces markup, so the result can be shown as text wherever a plain string is shown.
 */
import { isMermaidFence, parseMarkdown, type Token } from "./markdownIt";

const DIAGRAM = "[Diagram]";

/** @returns The alternative text of an `image` token as words (the reader keeps its raw source in `content`). */
export function imageAlt(token: Token): string {
  return inlineText(token.children ?? []);
}

function inlineText(tokens: Token[]): string {
  let out = "";
  for (const token of tokens) {
    if (token.type === "text" || token.type === "code_inline") out += token.content;
    else if (token.type === "softbreak" || token.type === "hardbreak") out += " ";
    else if (token.type === "image") out += imageAlt(token);
    else if (token.type === "math") out += token.content;
    if (token.children && token.type !== "image") out += inlineText(token.children);
  }
  return out;
}

/**
 * @param source Markdown text, as stored.
 * @param options `limit`: the most characters to return (a longer text ends in an ellipsis); `math`: read equations.
 * @returns The words of `source` on one line.
 */
export function markdownPlainText(source: string, options: { limit?: number; math?: boolean } = {}): string {
  const parts: string[] = [];
  for (const token of parseMarkdown(source, { math: options.math })) {
    if (token.type === "inline") parts.push(inlineText(token.children ?? []));
    else if (isMermaidFence(token)) parts.push(DIAGRAM);
    else if (token.type === "fence" || token.type === "code_block") parts.push(token.content);
  }
  const text = parts.join(" ").replace(/\s+/g, " ").trim();
  const { limit } = options;
  return limit !== undefined && text.length > limit ? `${text.slice(0, Math.max(0, limit - 1)).trimEnd()}…` : text;
}
