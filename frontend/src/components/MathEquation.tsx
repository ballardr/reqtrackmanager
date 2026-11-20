/**
 * Module: components/MathEquation
 *
 * One equation drawn with KaTeX, shared by `MathText` (a text with equations in it) and `MarkdownView` (a Markdown
 * document read with equations), so the two draw an equation the same way.
 *
 * Responsibilities:
 * - Draw `tex` as an inline or display equation, or show it as the author typed it (with its delimiters) when it may
 *   not or cannot be drawn: the report engine's allow-list (`utils/mathTex.texProblem`) and KaTeX's own errors.
 *
 * Design decisions:
 * - Only KaTeX's own output is inserted as markup, and only after `trust: false` rendering and a DOMPurify pass (HTML,
 *   MathML and SVG profiles), so a hostile record cannot inject script or a link through an equation.
 * - KaTeX emits MathML beside the visual layer, so a screen reader reads the equation.
 * - Results are cached per equation, because a list can repeat one.
 * - This file is the only importer of KaTeX; `MarkdownView` loads it on first use, so a page with no equation does not
 *   download the library.
 *
 * Dependencies: `katex` (MIT), `dompurify`, `utils/mathTex`.
 */
import DOMPurify from "dompurify";
import katex from "katex";
import "katex/dist/katex.min.css";

import { mathSource, texProblem, type MathSegment } from "../utils/mathTex";

const cache = new Map<string, string | null>();
const CACHE_LIMIT = 500;

/** KaTeX's markup for an equation, or `null` when it may not or cannot be drawn. */
function draw(tex: string, display: boolean): string | null {
  const key = `${display ? "d" : "i"}:${tex}`;
  if (cache.has(key)) return cache.get(key) ?? null;
  let html: string | null = null;
  if (texProblem(tex) === null) {
    try {
      html = DOMPurify.sanitize(
        katex.renderToString(tex, {
          displayMode: display, throwOnError: true, trust: false, strict: "ignore", maxExpand: 200, maxSize: 20,
          output: "htmlAndMathml",
        }),
        { USE_PROFILES: { html: true, mathMl: true, svg: true }, ADD_TAGS: ["annotation"], ADD_ATTR: ["encoding"] }, // the TeX, kept for copying
      );
    } catch {
      html = null; // a parse error: shown as written
    }
  }
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(key, html);
  return html;
}

/**
 * @param tex The TeX source.
 * @param display Whether it is a display equation (its own line) rather than inline.
 */
export function MathEquation({ tex, display }: { tex: string; display: boolean }) {
  const html = draw(tex, display);
  if (html === null) {
    const segment: MathSegment = { kind: display ? "display" : "inline", value: tex };
    return <>{mathSource(segment)}</>;
  }
  return <span className={display ? "math-text math-text--display" : "math-text"} dangerouslySetInnerHTML={{ __html: html }} />;
}
