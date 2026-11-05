/**
 * Module: modules/product_feedback/RequestScoresPanel
 *
 * A request's scoring on the detail page: the score under each model scored, side by side, and the level chosen on
 * each criterion of the scheme. Scores are derived on every read, so showing several models costs nothing and no
 * model "wins": a model that needs a criterion the request has no level for reads "Not scored", never zero. A derived
 * criterion (Demand) shows the level worked out from the requesters and says so; a level chosen by hand wins.
 * The weighted demand is shown beside the scores, not folded into them.
 */
import type { ScoringScheme } from "../../api/scoring";
import { DetailCard } from "../../components/DetailCard";
import { isDerivedAxis } from "./requestLevels";
import { demandText } from "./requestListState";
import { RequestScoreBadge } from "./RequestScoreBadge";
import type { EnhancementRequest } from "./types";

/**
 * @param request The request.
 * @param scheme The scoring scheme in effect (model and level names); null leaves the panel's detail out.
 * @param showDemand True on the project tier, where a request has requesters.
 */
export function RequestScoresPanel({
  request, scheme, showDemand,
}: { request: EnhancementRequest; scheme: ScoringScheme | null; showDemand: boolean }) {
  const modelKeys = Object.keys(request.scores);
  const modelLabel = (key: string) => scheme?.models.find((m) => m.key === key)?.label ?? key;
  return (
    <DetailCard heading="Scoring">
      <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap" }}>
        {modelKeys.map((key) => (
          <div key={key} className="stack" style={{ gap: "var(--space-1)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{modelLabel(key)}</span>
            <RequestScoreBadge score={request.scores[key]} />
          </div>
        ))}
        {showDemand && (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Demand</span>
            <span>{demandText(request)}</span>
          </div>
        )}
      </div>
      {scheme && (
        <dl className="stack" style={{ margin: 0, gap: "var(--space-2)" }}>
          {scheme.axes.map((axis) => {
            const chosen = axis.levels.find((l) => l.id === request.levels[axis.key]);
            const worked = isDerivedAxis(axis) ? axis.levels.find((l) => l.id === request.derived_levels[axis.key]) : undefined;
            return (
              <div key={axis.key} className="row" style={{ gap: "var(--space-2)" }}>
                <dt className="text-muted" style={{ minWidth: "8rem" }}>{axis.label}</dt>
                <dd style={{ margin: 0 }}>
                  {chosen ? chosen.name : worked ? <>{worked.name} <span className="text-muted">(worked out from demand)</span></> : <span className="text-muted">Not set</span>}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </DetailCard>
  );
}
