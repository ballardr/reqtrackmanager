/**
 * Module: components/Gauge
 *
 * A half-dial showing one figure between a minimum and a maximum, coloured by its level (within range,
 * warning, critical). Used by the project overview's gauge widget.
 *
 * Design decisions:
 * - The level is also written as text and in the accessible name, never colour alone.
 * - Drawn as one SVG arc with `pathLength` so the filled share is a plain dash length; no charting dependency.
 */
import { gaugeFraction, gaugeTone, type GaugeTone } from "../utils/overviewWidgets";

const TONE_COLOUR: Record<GaugeTone, string> = {
  ok: "var(--color-accent)",
  warning: "var(--color-warning)",
  critical: "var(--color-danger)",
};

/**
 * @param value The figure shown.
 * @param valueText The figure as formatted text (the centre of the dial).
 * @param minimum The value at the left end.
 * @param maximum The value at the right end.
 * @param warning Level at which the gauge turns to warning; omit for none.
 * @param critical Level at which the gauge turns to critical; omit for none.
 * @param direction `above`: a level is reached at or above it; `below`: at or below it.
 * @param label The accessible name's subject (the widget title).
 * @param levelLabels The words for each level.
 */
export function Gauge({
  value, valueText, minimum, maximum, warning, critical, direction = "above", label, levelLabels, ariaLabel,
}: {
  value: number;
  valueText: string;
  minimum: number;
  maximum: number;
  warning?: number | null;
  critical?: number | null;
  direction?: "above" | "below";
  label: string;
  levelLabels: Record<GaugeTone, string>;
  ariaLabel: (label: string, value: string, level: string) => string;
}) {
  const tone = gaugeTone(value, { warning, critical, direction });
  const fraction = gaugeFraction(value, minimum, maximum);
  return (
    <div className="stack" style={{ alignItems: "center", gap: "var(--space-1)" }} data-gauge-level={tone}>
      <svg
        viewBox="0 0 100 58" role="img" aria-label={ariaLabel(label, valueText, levelLabels[tone])}
        style={{ width: "100%", maxWidth: 220 }}
      >
        <path d="M 10 50 A 40 40 0 0 1 90 50" pathLength={100} fill="none" stroke="var(--color-surface-alt)" strokeWidth={10} strokeLinecap="round" />
        {fraction > 0 && (
          <path
            d="M 10 50 A 40 40 0 0 1 90 50" pathLength={100} fill="none" stroke={TONE_COLOUR[tone]} strokeWidth={10}
            strokeLinecap="round" strokeDasharray={`${fraction * 100} 100`}
          />
        )}
      </svg>
      <div style={{ fontSize: "1.8rem", fontWeight: 700, lineHeight: 1 }}>{valueText}</div>
      <div className="row text-muted" style={{ justifyContent: "space-between", width: "100%", maxWidth: 220, fontSize: "0.8rem" }}>
        <span>{minimum}</span>
        <span style={{ color: tone === "ok" ? undefined : TONE_COLOUR[tone], fontWeight: tone === "ok" ? undefined : 600 }}>
          {levelLabels[tone]}
        </span>
        <span>{maximum}</span>
      </div>
    </div>
  );
}
