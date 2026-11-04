/**
 * Module: components/StepIndicator
 *
 * The numbered steps of a short multi-step dialog ("1 Choose a report, 2 Configure"), with the current one marked.
 *
 * Responsibilities:
 * - Show every step in order with its number, so the person sees how far through they are.
 * - Mark the current step for assistive technology (`aria-current="step"`); finished steps stay readable.
 *
 * Design decisions: purely presentational; the host owns the current step and the navigation (a Back button), so
 * the indicator is not clickable.
 */

/**
 * @param steps The step labels in order.
 * @param current Zero-based index of the current step.
 * @param label Accessible name of the list ("Download steps").
 */
export function StepIndicator({ steps, current, label }: { steps: readonly string[]; current: number; label: string }) {
  return (
    <ol
      aria-label={label}
      className="row"
      style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-5)", flexWrap: "wrap" }}
    >
      {steps.map((step, index) => {
        const active = index === current;
        return (
          <li
            key={step}
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
          </li>
        );
      })}
    </ol>
  );
}
