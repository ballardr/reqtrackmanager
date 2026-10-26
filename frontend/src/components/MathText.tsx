/**
 * Module: components/MathText
 *
 * Shows text that may hold equations: `\( x \)` inline and `$$ x $$` as a block, drawn with KaTeX. It is used for the
 * record fields a report layout also treats as math-capable (a requirement's description, reasoning and
 * clarification), so what a person reads on screen is what the report draws.
 *
 * Responsibilities:
 * - Split the text (`utils/mathTex.splitMath`) and draw each equation, leaving every other character as text.
 * - Refuse what the report engine refuses (`utils/mathTex.texProblem`, from the backend's allow-list) and show it
 *   as written, so the screen and the report never disagree about which equations exist.
 *
 * Design decisions:
 * - Text goes in as React children, never as HTML; only KaTeX's own output is inserted as markup, and only after
 *   `trust: false` rendering and a DOMPurify pass (HTML, MathML and SVG profiles), so a hostile record cannot
 *   inject script or a link through an equation.
 * - KaTeX emits MathML beside the visual layer, so a screen reader reads the equation.
 * - A segment that fails (allow-list, KaTeX error) is shown as the author typed it with its delimiters, as in
 *   the reports. Results are cached per equation, because a list can repeat one.
 *
 * Dependencies: `katex` (MIT), `dompurify`, `utils/mathTex`.
 */
import DOMPurify from "dompurify";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Fragment, useMemo } from "react";

import { mathSource, splitMath, texProblem } from "../utils/mathTex";

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

interface MathTextProps {
  /** The text, as stored. */
  text: string;
}

/**
 * Text with its equations drawn.
 *
 * @param props.text The text; `\( x \)` and `$$ x $$` become equations, anything else is shown unchanged.
 */
export function MathText({ text }: MathTextProps) {
  const segments = useMemo(() => splitMath(text), [text]);
  if (segments.every((segment) => segment.kind === "text")) return <>{text}</>;
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") return <Fragment key={index}>{segment.value}</Fragment>;
        const html = draw(segment.value, segment.kind === "display");
        if (html === null) return <Fragment key={index}>{mathSource(segment)}</Fragment>;
        return (
          <span
            key={index}
            className={segment.kind === "display" ? "math-text math-text--display" : "math-text"}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        );
      })}
    </>
  );
}
