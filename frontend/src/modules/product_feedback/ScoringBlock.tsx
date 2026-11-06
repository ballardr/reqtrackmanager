/**
 * Module: modules/product_feedback/ScoringBlock
 *
 * A titled block inside a request's scoring area, so the *criteria* a person sets (Reach, Impact, Effort …) and the
 * *scores* the models derive from them read as two separate things: criteria are inputs shared by the models, a score
 * belongs to one model. Shared by the form and the request page. A thin rule above the title and spacing, no box: the
 * app uses no tinted panels inside a form or card.
 */
import type { ReactNode } from "react";

/**
 * @param title The block's title ("Criteria", "Scores").
 */
export function ScoringBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      className="stack"
      style={{ gap: "var(--space-3)", marginTop: "var(--space-3)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--color-border)" }}
    >
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {title}
      </span>
      {children}
    </div>
  );
}
