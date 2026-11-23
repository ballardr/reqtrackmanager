/**
 * Module: components/MathText
 *
 * Shows text that may hold equations: `\( x \)` inline and `$$ x $$` as a block, drawn with KaTeX. Used for the
 * record fields a report layout also treats as math-capable (a requirement's description, reasoning and
 * clarification), so the screen matches the report.
 *
 * Splits the text (`utils/mathTex.splitMath`) and draws each equation with `MathEquation`, leaving every other
 * character as text (React children, never HTML). It refuses what the report engine refuses
 * (`utils/mathTex.texProblem`) and shows it as written.
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
