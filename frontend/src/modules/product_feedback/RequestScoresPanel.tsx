/**
 * Module: modules/product_feedback/RequestScoresPanel
 *
 * A request's scoring on the request page, laid out like the form that edits it, in two titled blocks so the inputs
 * and the results are never mistaken for each other: **Criteria** (the level chosen on each criterion of the scheme,
 * name above level; the criteria are shared by the models, none belongs to one) and **Scores** (the
 * score under each model, `RequestScoreTable`; a model missing a criterion reads "Not scored", never zero). The derived criterion (Demand) shows its level with a calculator icon whose tooltip gives the demand it was worked
 * out from (or says a person chose it instead); weighted demand is never folded into a score.
 */
import { Calculator } from "lucide-react";
import { useId } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { DetailCard } from "../../components/DetailCard";
import { Tooltip } from "../../components/Tooltip";
import { isDerivedAxis } from "./requestLevels";
import { demandText } from "./requestListState";
import { RequestScoreTable } from "./RequestScoreTable";
import { ScoringBlock } from "./ScoringBlock";
import type { EnhancementRequest } from "./types";

/** The "calculated" mark beside a derived criterion's level: an icon whose tooltip says where the level came from. */
function DerivedNote({ note }: { note: string }) {
  const textId = useId();
  return (
    <Tooltip label={note} pinnable wrap bubbleId={textId}>
      <button type="button" className="field-help__button" aria-describedby={textId}>
        <Calculator aria-hidden="true" />
        <span className="sr-only">{note}</span>
      </button>
    </Tooltip>
  );
}

/**
 * @param request The request.
 * @param scheme The scoring scheme in effect (model and level names); null leaves the panel's detail out.
 * @param showDemand True on the project tier, where a request has requesters (the Demand level then names them).
 */
export function RequestScoresPanel({
  request, scheme, showDemand,
}: { request: EnhancementRequest; scheme: ScoringScheme | null; showDemand: boolean }) {
  return (
    <DetailCard heading="Scoring">
      {scheme && (
        <ScoringBlock title="Criteria">
          <dl
            style={{
              margin: 0, display: "grid", gap: "var(--space-4) var(--space-5)", alignItems: "start",
              gridTemplateColumns: "repeat(auto-fill, minmax(11.5rem, 1fr))",
            }}
          >
            {scheme.axes.map((axis) => {
              const chosen = axis.levels.find((l) => l.id === request.levels[axis.key]);
              const worked = isDerivedAxis(axis) && !chosen ? axis.levels.find((l) => l.id === request.derived_levels[axis.key]) : undefined;
              const level = chosen ?? worked;
              const note = isDerivedAxis(axis)
                ? `${chosen ? "Chosen manually" : "Calculated"}${showDemand ? ` from ${demandText(request)}` : " from demand"}`
                : null;
              return (
                <div key={axis.key} className="stack" style={{ gap: "var(--space-1)" }}>
                  <dt className="text-muted">{axis.label}</dt>
                  <dd className="row" style={{ margin: 0, gap: "var(--space-2)", alignItems: "center" }}>
                    {level ? level.name : <span className="text-muted">Not set</span>}
                    {note && <DerivedNote note={note} />}
                  </dd>
                </div>
              );
            })}
          </dl>
        </ScoringBlock>
      )}
      {scheme && Object.keys(request.scores).length > 0 && (
        <ScoringBlock title="Scores">
          <RequestScoreTable scheme={scheme} scores={request.scores} levels={request.levels} />
        </ScoringBlock>
      )}
    </DetailCard>
  );
}
