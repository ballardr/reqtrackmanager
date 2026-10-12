/**
 * Module: modules/risk_management/RiskRatingBadge
 *
 * A risk's derived rating as a badge in its band's tone — the register's
 * Inherent/Residual columns, the detail page and the review history all show
 * ratings this one way. Tones come from the shared `BadgeTone` palette, never a
 * module colour. A rating the model cannot produce (a level is missing) shows a
 * muted "Not rated".
 */
import type { RiskRating } from "./types";

/**
 * @param rating The derived rating, or null when the risk has no complete set of levels.
 * @param label Overrides the band label (the review history stores labels, not ratings).
 * @param tone Overrides the tone (used with `label`).
 */
export function RiskRatingBadge({
  rating, label, tone,
}: {
  rating?: RiskRating | null;
  label?: string | null;
  tone?: RiskRating["tone"];
}) {
  const shown = label ?? rating?.label ?? null;
  if (!shown) return <span className="badge badge--muted">Not rated</span>;
  return <span className={`badge badge--${tone ?? rating?.tone ?? "muted"}`}>{shown}</span>;
}
