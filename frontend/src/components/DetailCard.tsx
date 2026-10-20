/**
 * Module: components/DetailCard
 *
 * The card a record detail page puts its own content in: the record's fields under a "Details"
 * heading, or another group of them, or a panel (held needs, versions, attachments, comments) under its own
 * heading. The page header (back link, title, status badges, transitions) stays on the page background and
 * is never in a card (docs/ux-style-guide.md, "Pattern: detail page content").
 *
 * Design decisions: cards never nest. A `DetailCard` is a page-level block, so one never holds another
 * card; `scripts/check_detail_cards.py` fails a file that puts a card directly inside a `DetailCard`. The
 * heading is a real `<h2>` and names the section for assistive technology.
 */
import type { ReactNode } from "react";

/**
 * @param heading The card's heading (default "Details").
 * @param action A control on the heading's line, e.g. an `AddPopoverButton`.
 * @param children The card's content.
 */
export function DetailCard({
  heading = "Details", action, children,
}: { heading?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card stack" aria-label={heading}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="detail-card__title">{heading}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
