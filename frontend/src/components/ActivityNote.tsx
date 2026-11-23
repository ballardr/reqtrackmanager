/**
 * Module: components/ActivityNote
 *
 * The comment typed with a change, shown as a quoted block under an activity sentence. Long text collapses to
 * three lines with a "Show more" toggle. The text is user input: rendered as text (React escapes it), line breaks
 * kept with `white-space: pre-wrap`, never interpreted as HTML.
 */
import { useLayoutEffect, useRef, useState } from "react";

/**
 * @param text The comment or note.
 */
export function ActivityNote({ text }: { text: string }) {
  const ref = useRef<HTMLQuoteElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  // Whether the collapsed text is cut off, measured on the rendered block rather than guessed from its length.
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !expanded) setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, expanded]);

  return (
    <div className="stack" style={{ gap: "0.1rem" }}>
      <blockquote ref={ref} className={`activity-note${expanded ? "" : " activity-note-collapsed"}`}>
        {text}
      </blockquote>
      {(overflows || expanded) && (
        <button type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
