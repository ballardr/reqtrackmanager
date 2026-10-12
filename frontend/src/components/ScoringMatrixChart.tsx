/**
 * Module: components/ScoringMatrixChart
 *
 * A two-axis scoring matrix (generic scoring-matrix core, Module 1 Phase
 * 10): rows are the Y axis's levels (top level first), columns the X
 * axis's; each cell is coloured by the rating band its normalised score
 * (x weight × y weight ÷ the product of both top weights) falls in. Items
 * can be plotted as dots in their cell, sized by an optional 0–1 value
 * (e.g. Confidence for Pain Points).
 *
 * A cell's band is its explicit rating (`cellRatings`) if it has one, else the
 * threshold band of its score (`bandForCell`). With `onCellRatingChange` the
 * grid is an editor: each cell also carries a `<select>` to pin the cell to a
 * band or return it to the thresholds.
 *
 * Rendered as a real `<table>` so the grid is navigable and every cell has
 * a spoken name (axis levels, band and item count). Colours come only from
 * the shared `BadgeTone` palette (`.scoring-cell--<tone>`, theme.css).
 */
import { bandForCell, topWeight, type ScoringAxis, type ScoringBand, type ScoringCellRating } from "../api/scoring";

export interface ScoringMatrixPoint {
  id: string;
  label: string;
  xLevelId: string;
  yLevelId: string;
  /** 0–1, scales the dot's diameter; omitted = mid size. */
  size?: number;
}

/**
 * @param xAxis Column axis.
 * @param yAxis Row axis.
 * @param bands Rating bands used to colour cells (may be empty).
 * @param cellRatings Explicit per-cell ratings (first axis = `yAxis`, second = `xAxis`).
 * @param onCellRatingChange Makes the grid editable; called with the cell's
 *   levels (first = row, second = column) and the chosen band label, or
 *   `null` for "use thresholds".
 * @param points Items to plot.
 * @param caption Accessible table caption.
 * @param onCellClick Optional handler, e.g. to filter a list to one cell.
 */
export function ScoringMatrixChart({
  xAxis, yAxis, bands, cellRatings = [], onCellRatingChange, points = [], caption, onCellClick,
}: {
  xAxis: ScoringAxis;
  yAxis: ScoringAxis;
  bands: ScoringBand[];
  cellRatings?: ScoringCellRating[];
  onCellRatingChange?: (firstLevelId: string, secondLevelId: string, bandLabel: string | null) => void;
  points?: ScoringMatrixPoint[];
  caption: string;
  onCellClick?: (xLevelId: string, yLevelId: string) => void;
}) {
  const max = topWeight(xAxis) * topWeight(yAxis);
  const rows = [...yAxis.levels].reverse();
  return (
    <div className="scoring-matrix">
      <table>
        <caption className="text-muted">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{`${yAxis.label} ↓ / ${xAxis.label} →`}</th>
            {xAxis.levels.map((x) => (
              <th key={x.id} scope="col">{x.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((y) => (
            <tr key={y.id}>
              <th scope="row">{y.name}</th>
              {xAxis.levels.map((x) => {
                const band = max > 0 ? bandForCell(y.id, x.id, (x.weight * y.weight) / max, bands, cellRatings) : null;
                const pinned = cellRatings.find((c) => c.first_level_id === y.id && c.second_level_id === x.id)?.band_label ?? "";
                const here = points.filter((p) => p.xLevelId === x.id && p.yLevelId === y.id);
                const name = `${yAxis.label} ${y.name}, ${xAxis.label} ${x.name}: ${band?.label ?? "no band"}, ${here.length} item${here.length === 1 ? "" : "s"}`;
                const content = (
                  <>
                    {band && <span className="scoring-matrix__band">{band.label}</span>}
                    {onCellRatingChange && (
                      <select className="input scoring-matrix__select" aria-label={`Rating for ${yAxis.label} ${y.name}, ${xAxis.label} ${x.name}`}
                        value={pinned} onChange={(e) => onCellRatingChange(y.id, x.id, e.target.value || null)}>
                        <option value="">Thresholds</option>
                        {bands.map((b) => <option key={b.label} value={b.label}>{b.label}</option>)}
                      </select>
                    )}
                    <span className="scoring-matrix__dots">
                      {here.map((p) => {
                        const d = 8 + 10 * (p.size ?? 0.5);
                        return <span key={p.id} className="scoring-matrix__dot" title={p.label} style={{ width: d, height: d }} />;
                      })}
                    </span>
                  </>
                );
                return (
                  <td key={x.id} className={band ? `scoring-cell--${band.tone}` : undefined} aria-label={onCellClick ? undefined : name}>
                    {onCellClick ? (
                      <button type="button" className="scoring-matrix__cell-btn" aria-label={name} onClick={() => onCellClick(x.id, y.id)}>
                        {content}
                      </button>
                    ) : content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
