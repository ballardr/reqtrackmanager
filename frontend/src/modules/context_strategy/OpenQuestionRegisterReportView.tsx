/**
 * Module: modules/context_strategy/OpenQuestionRegisterReportView
 *
 * The on-screen view of report R4 (Open Question register), registered as
 * `TierAModuleDefinition.reportViews.r4` (Module 1 Phase 13). The generic
 * tables list overdue and unowned questions separately from the register, so
 * a reader has to cross-reference; this view shows one ageing table with
 * overdue and unowned rows highlighted in place, then the by-priority and
 * by-owner counts as the generic section tables. Statuses and priorities go
 * through the module's label maps.
 */
import { Link } from "react-router-dom";

import { ReportNothingToReport, ReportSectionTable, ReportSummary } from "../../components/ReportViewer";
import type { ReportViewProps } from "../types";
import type { OpenQuestionRegisterData } from "./reportTypes";
import { OPEN_QUESTION_PRIORITY_LABEL, OPEN_QUESTION_STATUS_LABEL, OPEN_QUESTION_STATUS_TONE } from "./types";

/** Sections replaced by the ageing table (the register and the two gap lists it highlights). */
const REPLACED_SECTIONS = new Set(["open", "overdue", "unowned"]);

/**
 * @param props The shared report view props (`ReportViewProps`).
 */
export function OpenQuestionRegisterReportView({ result, scope, values, figureAction }: ReportViewProps) {
  if (result.eligible_projects === 0) return <ReportNothingToReport />;
  const { items } = result.data as OpenQuestionRegisterData;
  const showProject = scope.kind === "organization" && !values.project_id;
  return (
    <div className="stack">
      <ReportSummary result={result} figureAction={figureAction} />
      <section className="stack" style={{ gap: "0.5rem" }} aria-label="Open Questions">
        <h3 style={{ margin: 0 }}>Open Questions</h3>
        {items.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>
            No open Open Questions.
          </p>
        ) : (
          <div className="card" style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  {showProject && <th scope="col">Project</th>}
                  <th scope="col">Priority</th>
                  <th scope="col">Status</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Due</th>
                  <th scope="col">Days open</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} data-overdue={item.is_overdue || undefined}>
                    <td>
                      <Link to={`/projects/${item.project_id}/modules/context_strategy/open-questions/${item.id}`}>{item.question}</Link>
                    </td>
                    {showProject && <td>{item.project_name}</td>}
                    <td>{OPEN_QUESTION_PRIORITY_LABEL[item.priority]}</td>
                    <td>
                      <span className={`badge badge--${OPEN_QUESTION_STATUS_TONE[item.status]}`}>{OPEN_QUESTION_STATUS_LABEL[item.status]}</span>
                    </td>
                    <td>{item.owner ?? <span className="badge badge--warning">Unowned</span>}</td>
                    <td>
                      {item.due_date ?? "–"}
                      {item.is_overdue && (
                        <span className="badge badge--danger" style={{ marginLeft: "0.5rem" }}>
                          Overdue
                        </span>
                      )}
                    </td>
                    <td>{item.days_open}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {result.sections
        .filter((s) => !REPLACED_SECTIONS.has(s.key))
        .map((section) => (
          <ReportSectionTable key={section.key} section={section} />
        ))}
    </div>
  );
}
