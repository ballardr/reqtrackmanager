/**
 * Module: components/LinkTraceChip
 *
 * The drawn face of the trace map's "Show more" pill: a rounded outline, a "+" (or a
 * spinner while it loads) and a label. Shared by the live control on each map node and
 * the key's miniature of it, so the two cannot drift apart.
 *
 * Responsibilities: presentation only; the caller supplies the interactive element around it.
 */
import { Loader2, Plus } from "lucide-react";

export const CHIP_W = 104;
export const CHIP_H = 22;
/** Space between the pill's outline and its content on each side, and between the icon and the label. */
const CHIP_PAD_X = 14;
const ICON = 12;
const ICON_GAP = 6;

/**
 * @param x Left edge, in the caller's SVG coordinates.
 * @param y Top edge.
 * @param label The visible text ("Show more" / "Loading…").
 * @param pending Show a spinner instead of the "+".
 */
export function ChipFace({ x, y, label, pending = false }: { x: number; y: number; label: string; pending?: boolean }) {
  return (
    <g className="link-trace__chip">
      <rect x={x} y={y} width={CHIP_W} height={CHIP_H} rx={CHIP_H / 2} />
      {pending ? (
        <Loader2 className="link-trace__spin" x={x + CHIP_PAD_X} y={y + (CHIP_H - ICON) / 2} width={ICON} height={ICON} />
      ) : (
        <Plus x={x + CHIP_PAD_X} y={y + (CHIP_H - ICON) / 2} width={ICON} height={ICON} />
      )}
      <text x={x + CHIP_PAD_X + ICON + ICON_GAP} y={y + CHIP_H / 2} dominantBaseline="central">{label}</text>
    </g>
  );
}
