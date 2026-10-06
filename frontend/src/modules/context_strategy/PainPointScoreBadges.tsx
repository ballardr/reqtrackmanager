/**
 * Module: modules/context_strategy/PainPointScoreBadges
 *
 * The two badges a Pain Point's per-persona score is shown with, shared by
 * the list page and the detail page's scoring panel (Phase 11): the rolled-up
 * score in its rating band's tone, and the Blocker flag that stays visible
 * whichever model or roll-up is chosen (a Blocker for one low-weight persona
 * can't be averaged away). Band tones come from the generic scoring core's
 * `BadgeTone`, never a per-module colour.
 */
import type { PainPointScoreValue, PainPointScoringSummary } from "./types";

/** Renders `score` as `<band> · <raw>` in the band's tone, or a muted
 * "Not scored" when nothing could be scored under the chosen model.
 *
 * @param score The computed score, or null for "not scored under this model".
 */
export function PainPointScoreBadge({ score }: { score: PainPointScoreValue | null }) {
  if (score === null) return <span className="badge badge--muted">Not scored</span>;
  const raw = Number.isInteger(score.raw) ? String(score.raw) : score.raw.toFixed(1);
  return (
    <span className={`badge badge--${score.band_tone ?? "muted"}`}>
      {score.band_label ? `${score.band_label} · ${raw}` : raw}
    </span>
  );
}

/** Renders the red "Blocker" badge when `summary.is_blocker`, naming the
 * blocked personas in its tooltip; renders nothing otherwise.
 *
 * @param summary The Pain Point's roll-up (or one score row).
 */
export function BlockerBadge({ summary }: { summary: Pick<PainPointScoringSummary, "is_blocker" | "blocker_labels"> }) {
  if (!summary.is_blocker) return null;
  const who = summary.blocker_labels.length ? `Unusable for: ${summary.blocker_labels.join(", ")}` : "Unusable, no workaround";
  return <span className="badge badge--danger" title={who}>Blocker</span>;
}
