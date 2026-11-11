/**
 * Module: components/StepIndicator
 *
 * The numbered steps of an ordered process, with the current one marked: across the top of a short multi-step dialog
 * ("1 Choose a report, 2 Configure"), or down the page as a list of steps with a detail under each (the phases of a
 * stage workflow).
 *
 * Responsibilities:
 * - Show every step in order with its number, so the person sees the sequence (and how far through they are).
 * - Mark the current step for assistive technology (`aria-current="step"`); finished steps stay readable.
 *
 * Design decisions: purely presentational; the host owns the current step and the navigation (a Back button), so
 * the indicator is not clickable. With no `current` step nothing is marked, for a list that only describes an order.
 */

/**
 * @param steps The step labels in order.
 * @param current Zero-based index of the current step; omit to mark none.
 * @param label Accessible name of the list ("Download steps").
 * @param details A short line under each step's label (same order; an entry may be undefined), shown muted.
 * @param vertical Lays the steps out as a column rather than a row.
 */
export function StepIndicator({
  steps, current, label, details, vertical = false,
}: { steps: readonly string[]; current?: number; label: string; details?: readonly (string | undefined)[]; vertical?: boolean }) {
  return (
    <ol
      aria-label={label}
      className={vertical ? "stack" : "row"}
      style={{ listStyle: "none", margin: 0, padding: 0, gap: vertical ? "var(--space-2)" : "var(--space-5)", flexWrap: "wrap" }}
    >
      {steps.map((step, index) => {
        const active = index === current;
        const detail = details?.[index];
        return (
          <li
            key={`${index}-${step}`}
            aria-current={active ? "step" : undefined}
            className="row"
            style={{ gap: "var(--space-2)", fontWeight: active ? 600 : 400, color: active ? "var(--color-text)" : "var(--color-text-muted)" }}
          >
            <span
              aria-hidden="true"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center", width: "1.5rem", height: "1.5rem",
                borderRadius: "50%", fontSize: "0.8rem",
                background: active ? "var(--color-primary)" : "var(--color-surface-alt)",
                color: active ? "var(--color-primary-contrast)" : "var(--color-text-muted)",
                border: "1px solid var(--color-border)",
              }}
            >
              {index + 1}
            </span>
            <span>{step}</span>
            {detail && <span className="text-muted" style={{ fontWeight: 400, fontSize: "0.85rem" }}>{detail}</span>}
          </li>
        );
      })}
    </ol>
  );
}
