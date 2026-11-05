/**
 * Module: modules/product_feedback/RequestScoreBadge
 *
 * A request's derived score as `<band> · <raw>` in its rating band's tone, or a muted "Not scored" when a manual
 * axis the model needs has no level yet (never zero). Shared by the list's score columns and the detail page.
 * Band tones come from the generic scoring core's `BadgeTone`, never a per-module colour. The explanation (what a
 * not-scored badge still needs, what a score is a share of) is the shared `Tooltip`, not a native `title`, which is
 * slow to appear and does not show on touch or keyboard focus.
 */
import { Badge } from "../../components/Badge";
import { Tooltip } from "../../components/Tooltip";
import type { BadgeTone } from "../../api/types";
import type { RequestScore } from "./types";

const TONES: readonly BadgeTone[] = ["muted", "info", "accent", "warning", "danger"];

/**
 * @param score The score under one model, or null when the request is not scored under it.
 * @param missing The criteria a not-scored request still lacks, named in the badge's tooltip (and accessible name).
 */
export function RequestScoreBadge({ score, missing = [] }: { score: RequestScore | null | undefined; missing?: string[] }) {
  if (!score) {
    const needs = missing.length > 0 ? `Needs ${missing.join(", ")} to be scored` : undefined;
    const badge = <Badge tone="muted" aria-label={needs ? `Not scored. ${needs}` : undefined}>Not scored</Badge>;
    return needs ? <Tooltip label={needs}>{badge}</Tooltip> : badge;
  }
  const raw = Number.isInteger(score.raw) ? String(score.raw) : score.raw.toFixed(1);
  const tone = TONES.find((t) => t === score.tone) ?? "muted";
  return (
    <Tooltip label={`${Math.round(score.normalised * 100)}% of the best possible score for this model`}>
      <Badge tone={tone}>{score.label ? `${score.label} · ${raw}` : raw}</Badge>
    </Tooltip>
  );
}
