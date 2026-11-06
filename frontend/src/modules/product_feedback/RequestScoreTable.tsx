/**
 * Module: modules/product_feedback/RequestScoreTable
 *
 * A request's scores as one small table: a column per scoring model (named without its formula, the full label on
 * hover), equal in width, with the score badge under each name. The one rendering of "the scores" for the form's live
 * preview and the request page's Scoring card, so the two read the same. A model with no score reads "Not scored";
 * its badge's tooltip says which criteria it still needs.
 */
import type { ScoringScheme } from "../../api/scoring";
import { missingAxisLabels, modelShortName, type LevelDraft } from "./requestLevels";
import { RequestScoreBadge } from "./RequestScoreBadge";
import type { RequestScore } from "./types";

/** No left padding, so the table's left edge is the edge of the block that holds it. */
const FLUSH = { paddingLeft: 0 } as const;

/** Model names are labels for the badges under them, not headings that compete with the badges, so they are not bold. */
const MODEL_NAME = { ...FLUSH, fontWeight: 400 } as const;

/**
 * @param scheme The scoring scheme in effect (model labels and axes).
 * @param scores The score under each model to show, by model key (null = not scored); the table's columns, in order.
 * @param levels The levels the scores were derived from, so a not-scored model can name what it lacks.
 * @param dimmed Fade the table (a newer answer is on its way).
 */
export function RequestScoreTable({
  scheme, scores, levels, dimmed = false,
}: { scheme: ScoringScheme; scores: Record<string, RequestScore | null>; levels: LevelDraft; dimmed?: boolean }) {
  const keys = Object.keys(scores);
  const label = (key: string) => scheme.models.find((m) => m.key === key)?.label ?? key;
  return (
    <table className="table" aria-label="Scores by model" style={{ opacity: dimmed ? 0.6 : 1, tableLayout: "fixed", width: "100%" }}>
      <thead>
        <tr>{keys.map((key) => <th key={key} scope="col" title={label(key)} style={MODEL_NAME}>{modelShortName(label(key))}</th>)}</tr>
      </thead>
      <tbody>
        <tr>
          {keys.map((key) => (
            <td key={key} style={FLUSH}><RequestScoreBadge score={scores[key]} missing={missingAxisLabels(scheme, key, levels)} /></td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}
