/**
 * Module: components/ProgressMeter
 *
 * A small horizontal meter with its value in words beside it: how far something has got, for example the step a stage or
 * component track has reached in its workflow.
 *
 * Responsibilities:
 * - Draw a `role="progressbar"` track whose fill is `value` of `max`, named by `label` for assistive technology.
 * - Show `label` as visible text next to the bar, so the figure is never conveyed by the bar alone.
 *
 * Design decisions: theme tokens only; a value above `max` is clamped to a full bar.
 */

/**
 * @param value How much is done (0 to `max`).
 * @param max The full amount; a `max` of 0 draws an empty bar.
 * @param label The value in words ("Step 2 of 5"), shown and used as the accessible name.
 */
export function ProgressMeter({ value, max, label }: { value: number; max: number; label: string }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <span className="progress-meter">
      <span className="progress-meter-track" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.min(value, max)} aria-label={label}>
        <span className="progress-meter-fill" style={{ width: `${percent}%` }} />
      </span>
      <span>{label}</span>
    </span>
  );
}
