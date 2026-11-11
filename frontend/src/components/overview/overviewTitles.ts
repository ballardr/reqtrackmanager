/**
 * Module: components/overview/overviewTitles
 *
 * The names the overview gives a widget and the rows of its charts: the default title of each core metric through the
 * project's terminology, and the label maps for requirement statuses, change request outcomes and record types.
 * Shared by the grid (what a viewer reads) and the editor (what the buttons are called), so both name a widget alike.
 */
import type { OverviewMetricResult, OverviewWidget, RequirementStatus } from "../../api/types";
import { REQUIREMENT_STATUS_LABEL } from "../../api/types";
import type { useStrings } from "../../context/TerminologyContext";

type Strings = ReturnType<typeof useStrings>;

/** The default titles of the core metrics, through the project's terminology. */
function coreTitle(metric: string, strings: Strings): string | undefined {
  const titles: Record<string, string> = {
    requirement_count: strings.requirements.title,
    requirement_completed_percent: strings.overview.percentComplete,
    file_count: strings.overview.fileCount,
    change_requests_proposed: strings.overview.crProposed,
    change_requests_approved: strings.overview.crApproved,
    change_requests_rejected: strings.overview.crRejected,
    requirements_by_status: strings.overview.requirementsByStatus,
    change_requests_by_outcome: strings.overview.changeRequestsChart,
    stage_progress: strings.overview.stageProgress,
    records_by_type: strings.overview.totalRecords,
  };
  return titles[metric];
}

/** The widget's title: its own, else the metric's default. */
export function titleOf(widget: OverviewWidget, result: OverviewMetricResult | undefined, strings: Strings): string {
  if (widget.title) return widget.title;
  const metric = typeof widget.config.metric === "string" ? widget.config.metric : null;
  if (widget.type === "stage_progress") return strings.overview.stageProgress;
  if (widget.type === "record_totals") return strings.overview.totalRecords;
  if (widget.type === "activity") return strings.overview.projectActivity;
  if (widget.type === "text") return "";
  const known = metric ? coreTitle(metric, strings) : undefined;
  return known ?? result?.label ?? strings.overviewWidgets.typeLabel[widget.type] ?? "";
}

/** A chart row's name: the requirement status, change request outcome or record type, through the label maps. */
export function rowLabel(metric: string, key: string, serverLabel: string, strings: Strings): string {
  if (metric === "requirements_by_status") return REQUIREMENT_STATUS_LABEL[key as RequirementStatus] ?? serverLabel;
  if (metric === "change_requests_by_outcome") {
    return ({ active: strings.overview.crProposed, approved: strings.overview.crApproved, rejected: strings.overview.crRejected } as Record<string, string>)[key]
      ?? serverLabel;
  }
  if (metric === "records_by_type") {
    if (key === "requirement") return strings.requirements.title;
    if (key === "change_request") return strings.overview.changeRequestsChart;
  }
  return serverLabel;
}

