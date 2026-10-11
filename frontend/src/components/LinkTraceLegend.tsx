/**
 * Module: components/LinkTraceLegend
 *
 * The key to the trace map, shown in a popover from the map's "Key" button: what a node's
 * stripe, border, fade and arrow mean.
 *
 * Responsibilities: presentation only. Each swatch is a miniature of the real map element and
 * reuses its CSS classes (`link-trace__node-*`), so a restyle of the map restyles the key.
 * The swatches are decorative (`aria-hidden`); every entry also has its text.
 */
import { useStrings } from "../context/TerminologyContext";

const W = 26;
const H = 16;

/** A miniature node: a box, optionally with a direction stripe, dashed or faded. */
function NodeSwatch({ tone, className = "" }: { tone?: "upstream" | "downstream" | "related" | "focus"; className?: string }) {
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false"
      className={`link-trace__node ${tone ? `link-trace__node--${tone}` : ""} ${className}`}>
      <rect className="link-trace__node-box" x={1} y={1} width={W - 2} height={H - 2} rx={3} />
      {tone && tone !== "focus" && <path className="link-trace__node-bar" d={`M 5 1 A 4 4 0 0 0 1 5 L 1 ${H - 5} A 4 4 0 0 0 5 ${H - 1} Z`} />}
    </svg>
  );
}

/** The key to the trace map's symbols. */
export function LinkTraceLegend() {
  const strings = useStrings().artefactLinks;
  return (
    <ul className="link-trace__legend" aria-label={strings.traceLegendLabel}>
      <li><NodeSwatch tone="focus" />{strings.traceLegendFocus}</li>
      <li><NodeSwatch tone="upstream" />{strings.traceLegendUpstream}</li>
      <li><NodeSwatch tone="downstream" />{strings.traceLegendDownstream}</li>
      <li><NodeSwatch tone="related" />{strings.traceLegendRelated}</li>
      <li>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
          <line className="link-trace__edge" x1={1} y1={H / 2} x2={W - 6} y2={H / 2} />
          <path className="link-trace__arrow" d={`M ${W - 1} ${H / 2} L ${W - 8} ${H / 2 - 4} L ${W - 8} ${H / 2 + 4} Z`} />
        </svg>
        {strings.traceLegendArrow}
      </li>
      <li>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
          <line className="link-trace__edge link-trace__edge--joined" x1={1} y1={H / 2} x2={W - 1} y2={H / 2} />
        </svg>
        {strings.traceLegendJoined}
      </li>
      <li><NodeSwatch className="link-trace__node--elsewhere" />{strings.traceLegendElsewhere}</li>
      <li><NodeSwatch className="link-trace__node--archived" />{strings.traceLegendArchived}</li>
    </ul>
  );
}
