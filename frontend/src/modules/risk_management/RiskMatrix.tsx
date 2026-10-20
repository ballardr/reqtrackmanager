/**
 * Module: modules/risk_management/RiskMatrix
 *
 * The project's configured Likelihood × Consequence grid with the register's
 * risks plotted in their cells (a Risk Management UI without a visible matrix
 * loses most of its communicative value). A thin adapter over the
 * shared `ScoringMatrixChart`: it picks the scheme's two-axis model, so cell
 * colours follow the organisation's bands and per-cell ratings, and plots each
 * risk by its inherent levels, its residual levels, or both (a point per rating,
 * named in its tooltip). Risks with no level on either axis are not plotted; the
 * caller lists how many.
 */
import type { ScoringScheme } from "../../api/scoring";
import { ScoringMatrixChart } from "../../components/ScoringMatrixChart";
import { CONSEQUENCE_AXIS, findAxis, gridModel, LIKELIHOOD_AXIS } from "./useRiskScheme";
import { cellOf, type RiskMatrixBasis, type RiskMatrixPlot } from "./riskFields";
import type { Risk } from "./types";

/**
 * @param scheme The project's effective `risk` scheme; the grid is omitted while it is null.
 * @param risks The risks to plot.
 * @param basis Plot by inherent levels, residual levels or both.
 * @param onCellClick Called with a cell's likelihood and consequence level ids (e.g. to filter the list).
 */
export function RiskMatrix({
  scheme, risks, basis, onCellClick,
}: {
  scheme: ScoringScheme | null;
  risks: Risk[];
  basis: RiskMatrixPlot;
  onCellClick?: (likelihoodLevelId: string, consequenceLevelId: string) => void;
}) {
  const likelihood = findAxis(scheme, LIKELIHOOD_AXIS);
  const consequence = findAxis(scheme, CONSEQUENCE_AXIS);
  const model = gridModel(scheme);
  if (!likelihood || !consequence || !model) return null;

  const bases: RiskMatrixBasis[] = basis === "both" ? ["inherent", "residual"] : [basis];
  const points = risks.flatMap((r) =>
    bases.flatMap((b) => {
      const cell = cellOf(r, b);
      if (!cell) return [];
      const label = basis === "both" ? `${r.unique_code} ${r.title} (${b})` : `${r.unique_code} ${r.title}`;
      return [{ id: `${r.id}:${b}`, label, xLevelId: cell.consequence, yLevelId: cell.likelihood }];
    }),
  );
  return (
    <ScoringMatrixChart
      xAxis={consequence}
      yAxis={likelihood}
      bands={model.bands}
      cellRatings={model.cell_ratings}
      points={points}
      caption={basis === "both" ? "Risk matrix: inherent and residual rating" : `Risk matrix by ${basis} rating`}
      onCellClick={onCellClick ? (x, y) => onCellClick(y, x) : undefined}
    />
  );
}
