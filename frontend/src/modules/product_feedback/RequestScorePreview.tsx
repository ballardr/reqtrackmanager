/**
 * Module: modules/product_feedback/RequestScorePreview
 *
 * The scores a request would get from the levels chosen so far, as a `RequestScoreTable` under the level pickers, so
 * the effect of each choice is visible before saving. The numbers come from the server (`useScorePreview`), never
 * computed here.
 */
import type { ScoringScheme } from "../../api/scoring";
import type { LevelDraft } from "./requestLevels";
import { RequestScoreTable } from "./RequestScoreTable";
import type { ScorePreviewState } from "./useScorePreview";

/**
 * @param scheme The scoring scheme in effect (model labels and axes).
 * @param levels The levels chosen so far, to say what a model still needs.
 * @param state The latest preview from `useScorePreview`.
 */
export function RequestScorePreview({
  scheme, levels, state,
}: { scheme: ScoringScheme; levels: LevelDraft; state: ScorePreviewState }) {
  return (
    <section aria-label="Scores" aria-busy={state.loading} className="stack" style={{ gap: "var(--space-2)" }}>
      {state.failed && <span className="text-muted" role="status">Scores could not be calculated just now.</span>}
      {!state.preview && !state.failed && <span className="text-muted">Calculating…</span>}
      {state.preview && <RequestScoreTable scheme={scheme} scores={state.preview.scores} levels={levels} dimmed={state.loading} />}
    </section>
  );
}
