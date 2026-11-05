/**
 * Module: modules/product_feedback/RequestScoreBadge
 *
 * A request's derived score as `<band> · <raw>` in its rating band's tone, or a muted "Not scored" when a manual
 * axis the model needs has no level yet (never zero). Shared by the list's score columns and the detail page.
 * Band tones come from the generic scoring core's `BadgeTone`, never a per-module colour.
 */
import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../api/types";
import type { RequestScore } from "./types";

const TONES: readonly BadgeTone[] = ["muted", "info", "accent", "warning", "danger"];

/**
 * @param score The score under one model, or null when the request is not scored under it.
 */
export function RequestScoreBadge({ score }: { score: RequestScore | null | undefined }) {
  if (!score) return <Badge tone="muted">Not scored</Badge>;
  const raw = Number.isInteger(score.raw) ? String(score.raw) : score.raw.toFixed(1);
  const tone = TONES.find((t) => t === score.tone) ?? "muted";
  return <Badge tone={tone}>{score.label ? `${score.label} · ${raw}` : raw}</Badge>;
}
