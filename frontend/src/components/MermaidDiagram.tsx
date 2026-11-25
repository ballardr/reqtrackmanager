/**
 * Module: components/MermaidDiagram
 *
 * Shows Mermaid diagram text as a drawing, inside rendered Markdown.
 *
 * Draws the text with `utils/mermaidRender` for the page's current theme (redrawn when it changes), as an image with
 * a text alternative: the diagram's type as its name and the source in an expandable block. On failure it shows the
 * source and the reason, so one bad diagram never hides the rest.
 *
 * The drawing is an `<img>` of a data URI, never inline SVG, so nothing in a diagram can run script. The library
 * loads on first use only. The theme is read from the `data-theme` attribute, so the component needs no provider
 * and stories can switch it.
 */
import { useEffect, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { DiagramError, renderDiagram, type DiagramTheme, type RenderedDiagram } from "../utils/mermaidRender";

function currentTheme(): DiagramTheme {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function useDiagramTheme(): DiagramTheme {
  const [theme, setTheme] = useState<DiagramTheme>(currentTheme);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/** The diagram's type, from the first line of its text (`flowchart`, `sequenceDiagram`, ...). */
function diagramKind(source: string): string {
  const first = source.split("\n").map((line) => line.trim()).find((line) => line !== "" && !line.startsWith("%%") && line !== "---");
  return first?.split(/[\s;{]/)[0] || "diagram";
}

type Outcome = { drawing: RenderedDiagram } | { reason: string };

/**
 * @param source The Mermaid text (the body of the fenced block).
 * @param showSource Whether the expandable source block is offered (the visual editor shows the source itself).
 */
export function MermaidDiagram({ source, showSource = true }: { source: string; showSource?: boolean }) {
  const text = useStrings().markdown;
  const theme = useDiagramTheme();
  // The outcome belongs to the text and theme it was drawn for; until it matches the current ones, the diagram is drawing.
  const key = `${theme}\n${source}`;
  const [settled, setSettled] = useState<{ key: string; outcome: Outcome } | null>(null);

  useEffect(() => {
    let current = true;
    renderDiagram(source, theme).then(
      (drawing) => { if (current) setSettled({ key, outcome: { drawing } }); },
      (error: unknown) => {
        if (current) setSettled({ key, outcome: { reason: error instanceof DiagramError ? error.message : "Unexpected error." } });
      },
    );
    return () => { current = false; };
  }, [source, theme, key]);

  const outcome = settled?.key === key ? settled.outcome : null;
  const status = outcome === null ? "drawing" : "drawing" in outcome ? "drawn" : "failed";
  const kind = diagramKind(source);
  return (
    <figure className="markdown-diagram" data-diagram-state={status}>
      {outcome === null && <p className="text-muted" role="status">{text.diagramDrawing}</p>}
      {outcome !== null && "drawing" in outcome && (
        <img
          src={outcome.drawing.src} alt={text.diagramLabel(kind)} width={outcome.drawing.width} height={outcome.drawing.height}
          style={{ maxWidth: "100%", height: "auto" }}
        />
      )}
      {outcome !== null && "reason" in outcome && <p className="markdown-diagram-error" role="alert">{text.diagramFailed(outcome.reason)}</p>}
      {outcome !== null && showSource && (
        <details open={"reason" in outcome || undefined}>
          <summary>{text.diagramSource}</summary>
          <pre><code>{source}</code></pre>
        </details>
      )}
    </figure>
  );
}
