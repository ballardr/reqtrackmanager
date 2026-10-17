/**
 * Module: modules/stakeholders/EngagementStalenessReportView
 *
 * The on-screen view of report S4 (Engagement staleness), registered as
 * `TierAModuleDefinition.reportViews.s4`. The tables are the
 * generic ones; what the generic view cannot do is pick a Stakeholder group, so
 * this view owns `group_id` and `group_by` (drawn by
 * `StakeholderReportGroupControls`) and renders the summary and sections as the
 * generic viewer does.
 */
import { ReportNothingToReport, ReportSectionTable, ReportSummary } from "../../components/ReportViewer";
import type { ReportViewProps } from "../types";
import { StakeholderReportGroupControls } from "./StakeholderReportGroupControls";

/**
 * @param props The shared report view props (`ReportViewProps`).
 */
export function EngagementStalenessReportView({ result, scope, values, onValueChange, figureAction }: ReportViewProps) {
  if (result.eligible_projects === 0) return <ReportNothingToReport />;
  return (
    <div className="stack">
      <StakeholderReportGroupControls projectId={scope.kind === "project" ? scope.id : null} values={values} onValueChange={onValueChange} />
      <ReportSummary result={result} figureAction={figureAction} />
      {result.sections.map((section) => (
        <ReportSectionTable key={section.key} section={section} />
      ))}
    </div>
  );
}
