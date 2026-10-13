/**
 * Module: modules/stakeholders/PowerInterestGridReportView
 *
 * The on-screen view of report S1 (Power/interest grid), registered as
 * `TierAModuleDefinition.reportViews.s1` (Module 2 Phase 6). The point of S1 is
 * *where* each Stakeholder sits, which four stacked tables hide, so this draws
 * the classic 2×2 grid (Influence up, Interest across) with each Stakeholder
 * linking to its page in the quadrant it falls in, then the Stakeholders with no
 * position as the generic gap table. Quadrant names go through
 * `GRID_QUADRANT_LABEL`. The view owns `group_id` and `group_by`, which narrow
 * the run and add a Branch column to the generic tables. A quadrant can hold any number of
 * Stakeholders, so each shows the first ten and puts the rest behind "Show all N", a scrolling
 * modal (`CappedList`), keeping the grid one screen tall.
 */
import { Link } from "react-router-dom";

import { CappedList } from "../../components/CappedList";
import { ReportNothingToReport, ReportSectionTable, ReportSummary } from "../../components/ReportViewer";
import type { ReportViewProps } from "../types";
import { StakeholderReportGroupControls } from "./StakeholderReportGroupControls";
import type { GridItem, PowerInterestGridData } from "./reportTypes";
import { GRID_QUADRANT_LABEL, type GridQuadrant } from "./types";

/** Rows of the grid from the top: high influence first. Within a row, interest rises left to right. */
const GRID_LAYOUT: GridQuadrant[][] = [
  ["keep_satisfied", "manage_closely"],
  ["monitor", "keep_informed"],
];
const QUADRANT_TONE: Record<GridQuadrant, string> = {
  manage_closely: "danger",
  keep_satisfied: "warning",
  keep_informed: "info",
  monitor: "muted",
};

function Quadrant({ quadrant, items }: { quadrant: GridQuadrant; items: GridItem[] }) {
  return (
    <section className="card stack" style={{ gap: "0.5rem", minHeight: "8rem" }} aria-label={GRID_QUADRANT_LABEL[quadrant]}>
      <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
        <h3 style={{ margin: 0 }}>{GRID_QUADRANT_LABEL[quadrant]}</h3>
        <span className={`badge badge--${QUADRANT_TONE[quadrant]}`}>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>
          Nobody here.
        </p>
      ) : (
        <CappedList
          items={items}
          noun="Stakeholders"
          modalTitle={GRID_QUADRANT_LABEL[quadrant]}
          renderList={(shown) => (
            <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {shown.map((item) => (
                <li key={`${item.project_id}-${item.id}`}>
                  <Link to={`/projects/${item.project_id}/modules/stakeholders/stakeholders/${item.id}`}>{item.name}</Link>{" "}
                  <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {item.influence} influence, {item.interest} interest
                  </span>
                </li>
              ))}
            </ul>
          )}
        />
      )}
    </section>
  );
}

/**
 * @param props The shared report view props (`ReportViewProps`).
 */
export function PowerInterestGridReportView({ result, scope, values, onValueChange, figureAction }: ReportViewProps) {
  if (result.eligible_projects === 0) return <ReportNothingToReport />;
  const data = result.data as PowerInterestGridData;
  return (
    <div className="stack">
      <StakeholderReportGroupControls projectId={scope.kind === "project" ? scope.id : null} values={values} onValueChange={onValueChange} />
      <ReportSummary result={result} figureAction={figureAction} />
      <div className="stack" style={{ gap: "0.5rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr", gap: "0.75rem", alignItems: "stretch" }}>
          {GRID_LAYOUT.map((row, index) => (
            <div key={row[0]} style={{ display: "contents" }}>
              <span className="text-muted" style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", textAlign: "center", fontWeight: 600 }}>
                {index === 0 ? "Higher influence" : "Lower influence"}
              </span>
              {row.map((quadrant) => (
                <Quadrant key={quadrant} quadrant={quadrant} items={data.quadrants[quadrant]} />
              ))}
            </div>
          ))}
          <span />
          <span className="text-muted" style={{ textAlign: "center", fontWeight: 600 }}>
            Lower interest
          </span>
          <span className="text-muted" style={{ textAlign: "center", fontWeight: 600 }}>
            Higher interest
          </span>
        </div>
      </div>
      {result.sections
        .filter((s) => s.key === "unscored")
        .map((section) => (
          <ReportSectionTable key={section.key} section={section} />
        ))}
    </div>
  );
}
