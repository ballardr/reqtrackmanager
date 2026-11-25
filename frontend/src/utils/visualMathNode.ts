/**
 * Module: utils/visualMathNode
 *
 * The equation node of the Visual Markdown editor: one inline, indivisible node that holds an equation's TeX and
 * whether it is a display equation, read from and written back as the delimiters the reader uses.
 *
 * Responsibilities: read `\( x \)` (inline) and `$$ x $$` (display) into a node and write it back with the TeX exactly
 *   as stored; carry the node through copy and paste inside the editor (`data-math` markup).
 *
 * Design decisions:
 * - The node is an atom: the editor never reads or escapes the characters inside it, so the underscores a formula
 *   needs survive.
 * - A display equation is an inline node, as the reader makes it, so a text reads the same in the Visual, Write and
 *   Preview views.
 * - The delimiters and the "an opener with no closer, or enclosing nothing, is ordinary text" rule are those of
 *   `utils/markdownMath`; the round-trip cases hold the two to each other.
 * - This file draws nothing: the editor extends the node with a view (`VisualMarkdownEditor`).
 *
 * Dependencies: TipTap (MIT).
 */
import { mergeAttributes, Node } from "@tiptap/core";

/** The delimiters of an equation: what opens it, what closes it and whether it is a display equation. */
const DELIMITERS = [
  { open: "$$", close: "$$", display: true },
  { open: "\\(", close: "\\)", display: false },
] as const;

/**
 * @param tex The TeX of an equation.
 * @param display Whether it is a display equation.
 * @returns The Markdown source of the equation.
 */
export function equationMarkdown(tex: string, display: boolean): string {
  return display ? `$$${tex}$$` : `\\(${tex}\\)`;
}

/**
 * @param tex TeX a person typed for an equation.
 * @param display Whether it is a display equation.
 * @returns Why it cannot be stored as an equation, or null when it can: it is empty, holds the closing delimiter
 *   (which would end the equation early) or holds a blank line (which would end the paragraph).
 */
export function mathProblem(tex: string, display: boolean): "empty" | "delimiter" | "blank-line" | null {
  if (!tex.trim()) return "empty";
  const close = display ? "$$" : "\\)";
  if (tex.includes(close)) return "delimiter";
  if (/\n\s*\n/.test(tex)) return "blank-line";
  return null;
}

/** The equation node. */
export const MathNode = Node.create({
  name: "math",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return { tex: { default: "" }, display: { default: false } };
  },

  parseHTML() {
    return [{
      tag: "span[data-math]",
      getAttrs: (element) => ({
        tex: (element as HTMLElement).getAttribute("data-tex") ?? "",
        display: (element as HTMLElement).getAttribute("data-math") === "display",
      }),
    }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, {
      "data-math": node.attrs.display ? "display" : "inline", "data-tex": node.attrs.tex,
    }), equationMarkdown(String(node.attrs.tex), Boolean(node.attrs.display))];
  },

  markdownTokenName: "math",

  markdownTokenizer: {
    name: "math",
    level: "inline",
    start: (src: string) => {
      const found = DELIMITERS.map((d) => src.indexOf(d.open)).filter((index) => index >= 0);
      return found.length === 0 ? -1 : Math.min(...found);
    },
    tokenize: (src: string) => {
      const delimiter = DELIMITERS.find((d) => src.startsWith(d.open));
      if (!delimiter) return undefined;
      const end = src.indexOf(delimiter.close, delimiter.open.length);
      const tex = end < 0 ? "" : src.slice(delimiter.open.length, end);
      if (end < 0 || !tex.trim()) return undefined;
      return { type: "math", raw: src.slice(0, end + delimiter.close.length), text: tex, display: delimiter.display };
    },
  },

  parseMarkdown: (token) => ({
    type: "math",
    attrs: { tex: String(token.text ?? ""), display: Boolean((token as { display?: boolean }).display) },
  }),

  renderMarkdown: (node) => equationMarkdown(String(node.attrs?.tex ?? ""), Boolean(node.attrs?.display)),
});
