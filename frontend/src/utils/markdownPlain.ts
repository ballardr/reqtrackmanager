/**
 * Module: utils/markdownPlain
 *
 * The readable words of a Markdown text, with no marks, for a place that shows
 * one line of it (a summary card, list cell, tooltip). The browser counterpart
 * of the server's `services.markdown_text.plain_text`, so both read a text the
 * same way. Reads the text with `parseMarkdown` and joins every block's words
 * with single spaces; a diagram is `[Diagram]`, a fenced block keeps its text,
 * an equation its TeX, a picture its alternative text. Nothing here produces
 * markup, so the result can be shown wherever a plain string is.
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

/** One piece of a Markdown summary: words, or an equation (its TeX) that a screen draws. */
export type SummaryPart = { kind: "text"; value: string } | { kind: "math"; tex: string };

/**
 * @param source Markdown text, as stored.
 * @param options `math`: read equations (`math` parts); `limit`: the most characters (an equation counts as its TeX) to keep, the text ending in an ellipsis.
 * @returns The words of `source` and its equations (their TeX trimmed), in order, with whitespace collapsed to single spaces and the text trimmed at both ends.
 */
export function markdownSummaryParts(source: string, options: { limit?: number; math?: boolean } = {}): SummaryPart[] {
  const raw: SummaryPart[] = [];
  const addText = (value: string) => raw.push({ kind: "text", value });
  for (const token of parseMarkdown(source, { math: options.math })) {
    if (token.type === "inline") {
      let run = "";
      const flush = () => { if (run) { addText(run); run = ""; } };
      const visit = (tokens: Token[]) => {
        for (const child of tokens) {
          if (child.type === "text" || child.type === "code_inline") run += child.content;
          else if (child.type === "softbreak" || child.type === "hardbreak") run += " ";
          else if (child.type === "image") run += imageAlt(child);
          else if (child.type === "math") { flush(); raw.push({ kind: "math", tex: child.content.replace(/\s+/g, " ").trim() }); }
          if (child.children && child.type !== "image") visit(child.children);
        }
      };
      visit(token.children ?? []);
      flush();
    } else if (isMermaidFence(token)) addText(DIAGRAM);
    else if (token.type === "fence" || token.type === "code_block") addText(token.content);
    addText(" ");
  }
  const parts: SummaryPart[] = [];
  for (const part of raw) {
    const last = parts[parts.length - 1];
    const value = part.kind === "text" ? part.value.replace(/\s+/g, " ") : "";
    if (part.kind === "math") parts.push(part);
    else if (last?.kind === "text") last.value = (last.value + value).replace(/\s+/g, " ");
    else parts.push({ kind: "text", value });
  }
  const first = parts[0];
  if (first?.kind === "text") first.value = first.value.trimStart();
  const end = parts[parts.length - 1];
  if (end?.kind === "text") end.value = end.value.trimEnd();
  const kept = parts.filter((part) => part.kind === "math" || part.value !== "");
  const { limit } = options;
  if (limit === undefined) return kept;
  const length = kept.reduce((sum, part) => sum + (part.kind === "text" ? part.value.length : part.tex.length), 0);
  if (length <= limit) return kept;
  const out: SummaryPart[] = [];
  let room = Math.max(0, limit - 1);
  for (const part of kept) {
    const size = part.kind === "text" ? part.value.length : part.tex.length;
    if (part.kind === "math") {
      if (size > room) break;
      out.push(part);
    } else {
      out.push({ kind: "text", value: part.value.slice(0, room) });
    }
    room -= Math.min(size, room);
    if (room === 0) break;
  }
  const tail = out[out.length - 1];
  if (tail?.kind === "text") tail.value = `${tail.value.trimEnd()}…`;
  else out.push({ kind: "text", value: "…" });
  return out;
}

/**
 * @param source Markdown text, as stored.
 * @param options `limit`: the most characters to return (a longer text ends in an ellipsis); `math`: read equations.
 * @returns The words of `source` on one line; an equation is its TeX.
 */
export function markdownPlainText(source: string, options: { limit?: number; math?: boolean } = {}): string {
  return markdownSummaryParts(source, options).map((part) => (part.kind === "text" ? part.value : part.tex)).join("");
}
