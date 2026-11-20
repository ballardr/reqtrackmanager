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
 * - Text goes in as React children, never as HTML; each equation is drawn by `MathEquation`, which shows one that
 *   may not or cannot be drawn as the author typed it, as the reports do.
 *
 * Dependencies: `components/MathEquation` (KaTeX), `utils/mathTex`.
 */
import { Fragment, useMemo } from "react";

import { splitMath } from "../utils/mathTex";
import { MathEquation } from "./MathEquation";

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
      {segments.map((segment, index) =>
        segment.kind === "text"
          ? <Fragment key={index}>{segment.value}</Fragment>
          : <MathEquation key={index} tex={segment.value} display={segment.kind === "display"} />)}
    </>
  );
}
