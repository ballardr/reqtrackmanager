/**
 * Module: modules/context_strategy/PainPointPrioritisationReportView
 *
 * The on-screen view of report R1 (Pain Point prioritisation), registered as
 * `TierAModuleDefinition.reportViews.r1` (Module 1 Phase 13). A table of
 * ranked rows fails the reader here: the point of R1 is *where* Pain Points
 * sit on the Severity × Frequency matrix and which are Blockers, so this view
 * draws the shared `ScoringMatrixChart` per scoring model and a ranked list
 * with score and Blocker badges, and chooses the model and persona roll-up
 * with the shared `ScoringModelSwitcher` (it owns the `model_key` and `rollup`
 * parameters, so the generic form hides them). Everything else R1 returns
 * (Blockers, unscored, intentional, per-persona breakdown) stays the generic
 * section tables so there is one rendering of each.
 *
 * Items are ranked within one model only; a group per model is never mixed.
 * Dependencies: core scoring components and `api/scoring` (read-only scheme
 * lookup for the switcher's model list).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { orgScoringApi, projectScoringApi, type ScoringAxis, type ScoringScheme } from "../../api/scoring";
import { ReportNothingToReport, ReportSectionTable, ReportSummary } from "../../components/ReportViewer";
import { ScoringMatrixChart, type ScoringMatrixPoint } from "../../components/ScoringMatrixChart";
import { ScoringModelSwitcher } from "../../components/ScoringModelSwitcher";
import type { ReportViewProps } from "../types";
import type { PainPointPrioritisationData, ReportLevel, ReportRankedPainPoint, ReportScoredGroup } from "./reportTypes";
import { PAIN_POINT_ROLLUP_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE, type PainPointRollup } from "./types";

const SCHEME_KEY = "pain_point";
/** Sections drawn by this view itself (the ranking table and the matrix). */
const REPLACED_SECTIONS = new Set(["ranking", "matrix"]);

function axis(key: string, label: string, levels: ReportLevel[]): ScoringAxis {
  return { key, label, description: null, levels: levels.map((l) => ({ id: l.name, name: l.name, description: null, weight: l.weight })) };
}

/** Plots each fixable, scored item at its worst persona's cell; dot size is its Confidence relative to the group's. */
function matrixPoints(items: ReportRankedPainPoint[]): ScoringMatrixPoint[] {
  const plotted = items.filter((i) => !i.is_intentional && i.matrix !== null);
  const top = Math.max(0, ...plotted.map((i) => i.matrix?.confidence_weight ?? 0));
  return plotted.map((i) => ({
    id: i.id,
    label: i.title,
    xLevelId: i.matrix!.frequency,
    yLevelId: i.matrix!.severity,
    size: top > 0 && i.matrix!.confidence_weight !== null ? i.matrix!.confidence_weight / top : undefined,
  }));
}

function GroupView({ group, showProject }: { group: ReportScoredGroup; showProject: boolean }) {
  const ranked = group.items.filter((i) => !i.is_intentional && i.score !== null).sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
  return (
    <section className="stack" aria-label={group.model_label}>
      <h3 style={{ margin: 0 }}>{group.model_label}</h3>
      <ScoringMatrixChart
        xAxis={axis("frequency", "Frequency", group.frequency_levels)}
        yAxis={axis("severity", "Severity", group.severity_levels)}
        bands={group.bands}
        points={matrixPoints(group.items)}
        caption={`${group.model_label}: Severity × Frequency, by each Pain Point's worst persona`}
      />
      {ranked.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>
          No scored Pain Points to rank under this model.
        </p>
      ) : (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <caption className="text-muted" style={{ textAlign: "left" }}>
              Ranked Pain Points
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Pain point</th>
                {showProject && <th scope="col">Project</th>}
                <th scope="col">Type</th>
                <th scope="col">Status</th>
                <th scope="col">Score</th>
                <th scope="col">Flags</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((item) => (
                <tr key={item.id}>
                  <td>{item.rank}</td>
                  <td>
                    <Link to={`/projects/${item.project_id}/modules/context_strategy/pain-points/${item.id}`}>{item.title}</Link>
                  </td>
                  {showProject && <td>{item.project_name}</td>}
                  <td>{item.type_name}</td>
                  <td>
                    <span className={`badge badge--${PAIN_POINT_STATUS_TONE[item.status]}`}>{PAIN_POINT_STATUS_LABEL[item.status]}</span>
                  </td>
                  <td>
                    <span className={`badge badge--${item.band_tone ?? "muted"}`}>
                      {item.band ? `${item.band} · ` : ""}
                      {Math.round((item.score ?? 0) * 100)}
                    </span>
                  </td>
                  <td>
                    <span className="row" style={{ gap: "0.35rem", flexWrap: "wrap" }}>
                      {item.is_blocker && (
                        <span className="badge badge--danger" title={item.blocker_personas.length ? `Unusable for: ${item.blocker_personas.join(", ")}` : "Unusable, no workaround"}>
                          Blocker
                        </span>
                      )}
                      {item.churn_risk && <span className="badge badge--warning">Churn risk</span>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * @param props The shared report view props (`ReportViewProps`).
 */
export function PainPointPrioritisationReportView({ result, scope, values, onValueChange }: ReportViewProps) {
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const data = result.data as PainPointPrioritisationData;
  const projectId = scope.kind === "project" ? scope.id : typeof values.project_id === "string" ? values.project_id : null;

  useEffect(() => {
    let cancelled = false;
    // A report narrowed to one project uses that project's own scheme (its default model and bands).
    (projectId ? projectScoringApi.get(projectId, SCHEME_KEY) : orgScoringApi.get(scope.id, SCHEME_KEY))
      .then((next) => !cancelled && setScheme(next))
      .catch(() => !cancelled && setScheme(null));
    return () => {
      cancelled = true;
    };
  }, [projectId, scope.id]);

  if (result.eligible_projects === 0) return <ReportNothingToReport />;
  const model = typeof values.model_key === "string" && values.model_key ? values.model_key : (scheme?.default_model_key ?? "");
  const rollup = (typeof values.rollup === "string" && values.rollup ? values.rollup : data.rollup) as PainPointRollup;
  return (
    <div className="stack">
      {scheme && (
        <ScoringModelSwitcher
          models={scheme.models.map((m) => ({ value: m.key, label: m.label }))}
          model={model}
          onModelChange={(next) => onValueChange("model_key", next)}
          rollups={Object.entries(PAIN_POINT_ROLLUP_LABEL).map(([value, label]) => ({ value, label }))}
          rollup={rollup}
          onRollupChange={(next) => onValueChange("rollup", next)}
        />
      )}
      <ReportSummary result={result} />
      {data.groups.map((group) => (
        <GroupView key={group.model_key} group={group} showProject={scope.kind === "organization" && !projectId} />
      ))}
      {result.sections
        .filter((s) => !REPLACED_SECTIONS.has(s.key))
        .map((section) => (
          <ReportSectionTable key={section.key} section={section} />
        ))}
    </div>
  );
}
