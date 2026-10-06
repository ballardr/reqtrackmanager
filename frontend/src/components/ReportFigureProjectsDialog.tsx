/**
 * Module: components/ReportFigureProjectsDialog
 *
 * The "which projects?" list behind an organisation-wide report figure
 * (Module 1, report figure links). A project page can show only one project's
 * items, so clicking an organisation figure (say "Blockers: 3") opens this
 * dialog: every in-scope project with its own number for that figure, biggest
 * first, each a link to that project's page (the filtered list the figure
 * counts, or the gap table). The numbers come from the report's per-project
 * breakdown endpoint, i.e. the same collector run per project, so they equal
 * each project's own report and add up to the figure clicked.
 *
 * Loads on open, shows a spinner then the list or an error; projects with a
 * zero for the figure are listed last and muted (not links worth following).
 * Pure presentation plus one read: it never changes data.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { reportsApi, type ReportBreakdown, type ReportCatalogueEntry, type ReportMetric, type ReportRunValues } from "../api/reports";
import { toErrorMessage } from "../context/ToastContext";
import { reportLinkResolver } from "../utils/reportLinks";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/**
 * @param entry The organisation report's catalogue entry.
 * @param values The run values currently on screen (so the breakdown uses the same options).
 * @param metric The figure that was clicked (matched in each project by group and label).
 * @param onClose Closes the dialog (also called when a project link is followed).
 */
export function ReportFigureProjectsDialog({
  entry, values, metric, onClose,
}: {
  entry: ReportCatalogueEntry;
  values: ReportRunValues;
  metric: ReportMetric;
  onClose: () => void;
}) {
  const [breakdown, setBreakdown] = useState<ReportBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    reportsApi
      .breakdown(entry, values)
      .then((loaded) => !cancelled && setBreakdown(loaded))
      .catch((err) => !cancelled && setError(toErrorMessage(err, "Could not load the projects for this figure.")));
    return () => {
      cancelled = true;
    };
    // The values are the ones on screen when the figure was clicked; the dialog is remounted per click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = (breakdown?.projects ?? [])
    .map((p) => {
      const found = p.metrics.find((m) => m.label === metric.label && (m.group ?? null) === (metric.group ?? null));
      return { id: p.project_id, name: p.project_name, value: Number(found?.value ?? 0), link: found?.link ?? metric.link };
    })
    .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));

  return (
    <Modal title={`${metric.label} by project`} onClose={onClose}>
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          {metric.group ? `${metric.group} · ` : ""}
          {metric.value} across the organisation. Choose a project to open it.
        </p>
        {error && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{error}</p>}
        {!breakdown && !error && <Spinner label="Loading projects…" />}
        {breakdown && rows.length === 0 && <p className="text-muted" style={{ margin: 0 }}>No projects are covered by this figure.</p>}
        {breakdown && rows.length > 0 && (
          <ul className="stack figure-projects" style={{ listStyle: "none", margin: 0, padding: 0, gap: 0 }}>
            {rows.map((row) => {
              const to = row.link ? reportLinkResolver({ kind: "project", id: row.id }, entry.module_key)?.(row.link) : undefined;
              return (
                <li key={row.id} className="figure-projects-row">
                  {to && row.value > 0 ? (
                    <Link to={to} onClick={onClose} className="figure-projects-link">
                      <span>{row.name}</span>
                      <strong>{row.value}</strong>
                    </Link>
                  ) : (
                    <span className="figure-projects-link text-muted">
                      <span>{row.name}</span>
                      <strong>{row.value}</strong>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {breakdown?.truncated && (
          <p className="text-muted" style={{ margin: 0 }}>Only the first projects are listed; narrow the report to a single project for the rest.</p>
        )}
      </div>
    </Modal>
  );
}
