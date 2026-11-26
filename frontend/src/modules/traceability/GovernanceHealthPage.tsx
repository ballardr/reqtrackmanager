/**
 * Module: modules/traceability/GovernanceHealthPage
 *
 * The project's governance health, mounted at `/projects/:projectId/modules/traceability/health` (the "Governance Health"
 * nav-rail entry): progress per record category, the reviews that are due and the results of the baseline checks, served
 * live or from a stored snapshot.
 *
 * Responsibilities:
 * - Read the health (`projectGovernanceApi.health`) and draw its three sections, each with a heading and an empty state.
 * - State the source (live, or the time a snapshot was taken) and flag a snapshot that is stale.
 * - Offer Refresh now only where the server allows it (a snapshot mode and the right to manage governance).
 * - Show a not-found message when the project's governance health is not available, and Retry for any other failed read.
 *
 * Design decisions: the figures arrive already restricted to the record types the viewer may read, so an empty section
 * means nothing is available to this viewer. A table's sort is local to the page because the three tables cannot share
 * the address's single sort parameter. A completion category's progress orders by its percentage and an outstanding
 * category, which has no percentage, orders last.
 *
 * Dependencies: `projectGovernanceApi`, `DirectoryTable`, `ProgressMeter`.
 */
import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { CollapsibleSection } from "../../components/CollapsibleSection";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { LoadFailed } from "../../components/LoadFailed";
import { ProgressMeter } from "../../components/ProgressMeter";
import { Spinner } from "../../components/Spinner";
import { cycleSort, type SortState } from "../../components/sortState";
import { useStrings } from "../../context/TerminologyContext";
import { useCurrentNavLabelOverride } from "../../context/NavLabelValue";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useMutation } from "../../hooks/useMutation";
import { humanise } from "../../utils/humanise";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { projectGovernanceApi } from "./api";
import {
  HEALTH_CHECKS_STATUS_LABEL,
  HEALTH_MODE_LABEL,
  type Health,
  type HealthCategory,
  type HealthReview,
} from "./types";

const EMPTY_FIGURES = "No governance figures are available for the record types you can view.";

/** One baseline check's result for one record type, flattened for the table. */
interface CheckRow {
  key: string;
  check: string;
  typeLabel: string;
  checked: number;
  failing: number;
  passing: number | null;
}

/**
 * A table's local sort and its header-click handler.
 *
 * @returns The sort, and a function that cycles it for a header click.
 */
function useLocalSort(): [SortState | null, (key: string) => void] {
  const [sort, setSort] = useState<SortState | null>(null);
  return [sort, (key) => setSort((current) => cycleSort(current, key))];
}

/**
 * @param category A health category.
 * @returns How far the category has got in words: a percentage with the counts, or the number still outstanding.
 */
function progressText(category: HealthCategory): string {
  return category.kind === "completion" && category.percent !== null
    ? `${category.percent}% (${category.done} of ${category.total})`
    : `${category.outstanding} outstanding`;
}

/**
 * The categories table.
 *
 * @param categories The categories the viewer may read.
 */
function CategoriesTable({ categories }: { categories: HealthCategory[] }) {
  const [sort, onSort] = useLocalSort();
  const values: Record<string, (row: HealthCategory) => SortValue> = {
    category: (row) => row.label,
    progress: (row) => (row.kind === "completion" ? row.percent : null),
    total: (row) => row.total,
  };
  const columns: DirectoryColumn<HealthCategory>[] = [
    { key: "category", label: "Category", sortable: true, minWidth: "10rem", render: (row) => <CellText lines={2}>{row.label}</CellText> },
    {
      key: "progress", label: "Progress", sortable: true,
      render: (row) => row.kind === "completion" && row.percent !== null
        ? <ProgressMeter value={row.percent} max={100} label={progressText(row)} />
        : progressText(row),
    },
    { key: "total", label: "Records", sortable: true, width: "7rem", render: (row) => row.total.toLocaleString() },
  ];
  return (
    <DirectoryTable
      ariaLabel="Progress by record category" columns={columns} rows={sortRows(categories, sort, values)}
      rowKey={(row) => row.key} sort={sort} onSort={onSort} emptyState={<p className="text-muted">{EMPTY_FIGURES}</p>}
    />
  );
}

/**
 * The reviews-due table.
 *
 * @param reviews The record types with a review schedule that the viewer may read.
 */
function ReviewsTable({ reviews }: { reviews: HealthReview[] }) {
  const [sort, onSort] = useLocalSort();
  const values: Record<string, (row: HealthReview) => SortValue> = { type: (row) => row.label, due: (row) => row.due };
  const columns: DirectoryColumn<HealthReview>[] = [
    { key: "type", label: "Record type", sortable: true, minWidth: "10rem", render: (row) => <CellText lines={2}>{row.label}</CellText> },
    { key: "due", label: "Reviews due", sortable: true, width: "9rem", render: (row) => row.due.toLocaleString() },
  ];
  return (
    <DirectoryTable
      ariaLabel="Reviews due by record type" columns={columns} rows={sortRows(reviews, sort, values)}
      rowKey={(row) => row.artefact_type} sort={sort} onSort={onSort} emptyState={<p className="text-muted">{EMPTY_FIGURES}</p>}
    />
  );
}

/**
 * The baseline check results, one row per check and record type.
 *
 * @param health The health whose checks are shown.
 * @param labels The display name of each record type the page knows by key.
 */
function ChecksSection({ health, labels }: { health: Health; labels: Map<string, string> }) {
  const [sort, onSort] = useLocalSort();
  const { checks } = health;
  const rows: CheckRow[] = checks.checks.flatMap((check) =>
    check.types.map((type) => ({
      key: `${check.key}:${type.artefact_type}`, check: check.name,
      typeLabel: labels.get(type.artefact_type) ?? humanise(type.artefact_type),
      checked: type.checked, failing: type.failing, passing: type.percent_passing,
    })),
  );
  const values: Record<string, (row: CheckRow) => SortValue> = {
    check: (row) => row.check, type: (row) => row.typeLabel, failing: (row) => row.failing, passing: (row) => row.passing,
  };
  const columns: DirectoryColumn<CheckRow>[] = [
    { key: "check", label: "Check", sortable: true, minWidth: "10rem", render: (row) => <CellText lines={2}>{row.check}</CellText> },
    { key: "type", label: "Record type", sortable: true, render: (row) => <CellText lines={2}>{row.typeLabel}</CellText> },
    { key: "failing", label: "Records failing", sortable: true, render: (row) => `${row.failing.toLocaleString()} of ${row.checked.toLocaleString()}` },
    { key: "passing", label: "Passing", sortable: true, width: "7rem", render: (row) => (row.passing === null ? "No records" : `${row.passing}%`) },
  ];
  const ran = checks.run_at !== null
    ? `Run${checks.run_by ? ` by ${checks.run_by.name}` : ""} on ${new Date(checks.run_at).toLocaleString()}.`
    : null;
  return (
    <>
      <p className="text-muted" style={{ margin: 0 }}>
        {checks.status === "not_enabled" ? HEALTH_CHECKS_STATUS_LABEL.not_enabled : `Status: ${HEALTH_CHECKS_STATUS_LABEL[checks.status]}.`}
        {ran ? ` ${ran}` : ""}
      </p>
      {checks.status !== "not_enabled" && (
        <DirectoryTable
          ariaLabel="Baseline check results" columns={columns} rows={sortRows(rows, sort, values)}
          rowKey={(row) => row.key} sort={sort} onSort={onSort}
          emptyState={<p className="text-muted">{EMPTY_FIGURES}</p>}
        />
      )}
    </>
  );
}

/**
 * The page; the project comes from the route.
 */
export function GovernanceHealthPage() {
  const { projectId = "" } = useParams();
  const strings = useStrings();
  const run = useMutation();
  const navName = useCurrentNavLabelOverride();
  const [health, setHealth] = useState<Health | null>(null);
  const [problem, setProblem] = useState<"failed" | "not_found" | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setHealth(await projectGovernanceApi.health(projectId));
      setProblem(null);
    } catch (err) {
      setProblem(err instanceof ApiError && err.status === 404 ? "not_found" : "failed");
    }
  }, [projectId]);
  useLoadOnChange(load, [projectId]);

  async function refresh() {
    setRefreshing(true);
    let next: Health | null = null;
    const ok = await run(
      async () => { next = await projectGovernanceApi.refreshHealth(projectId); },
      { success: "Governance health refreshed.", failure: "Could not refresh governance health." },
    );
    setRefreshing(false);
    if (ok && next) setHealth(next);
  }

  const title = navName ?? "Governance health";
  let body;
  if (problem === "not_found" && !health) {
    body = <p role="alert">Governance health is not available for this project.</p>;
  } else if (problem === "failed" && !health) {
    body = <LoadFailed message={strings.requestFailure.loadFailed("Governance health")} onRetry={() => { setProblem(null); void load(); }} />;
  } else if (!health) {
    body = <Spinner />;
  } else {
    const labels = new Map<string, string>([
      ...health.categories.map((c): [string, string] => [c.artefact_type, c.label]),
      ...health.reviews.map((r): [string, string] => [r.artefact_type, r.label]),
    ]);
    body = (
      <>
        <div className="row" style={{ alignItems: "center" }}>
          <Badge>{HEALTH_MODE_LABEL[health.mode]}</Badge>
          <span>{health.source === "live" ? "Live figures, read when this page opened." : `Snapshot taken ${new Date(health.computed_at).toLocaleString()}.`}</span>
          {health.stale && <Badge tone="warning">Stale</Badge>}
        </div>
        <CollapsibleSection sectionKey="governance-health-categories" title="Categories" collapsible={false}>
          <CategoriesTable categories={health.categories} />
        </CollapsibleSection>
        <CollapsibleSection sectionKey="governance-health-reviews-due" title="Reviews due" collapsible={false}>
          <ReviewsTable reviews={health.reviews} />
        </CollapsibleSection>
        <CollapsibleSection sectionKey="governance-health-baseline-checks" title="Baseline checks" collapsible={false}>
          <ChecksSection health={health} labels={labels} />
        </CollapsibleSection>
      </>
    );
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{title}</h1>
        {health?.can_refresh && (
          <button type="button" className="btn" disabled={refreshing} onClick={() => void refresh()}>Refresh now</button>
        )}
      </div>
      {body}
    </div>
  );
}
