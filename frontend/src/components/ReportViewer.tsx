/**
 * Module: components/ReportViewer
 *
 * Renders any collected report (`ReportResult`) generically: its notes,
 * headline metrics and each section as a table, with gap sections (tables
 * that list problems to fix) marked. This is the default on-screen view for
 * every report in the core report framework; a module registers a custom
 * view (`TierAModuleDefinition.reportViews`) only where a table genuinely
 * fails the reader, and composes the exported pieces (`ReportSummary`,
 * `ReportSectionTable`) for the parts the table form already serves. It knows
 * nothing about any one report or module.
 *
 * Pure presentation: the caller (`ReportRunner`) owns loading and error
 * states. A report whose sub-component is on for no in-scope project
 * (`eligible_projects === 0`) shows an explicit empty state rather than a
 * wall of empty tables.
 */
import type { ReportResult, ReportSection } from "../api/reports";
import { StatBar } from "./StatBar";
import { StatGroups, type StatGroup } from "./StatGroups";

/** Explains that no in-scope project has the feature on; shown instead of empty tables. */
export function ReportNothingToReport() {
  return (
    <p className="text-muted" role="status">
      Nothing to report on: none of the projects covered by this report has the feature enabled.
    </p>
  );
}

/**
 * Groups figures that carry a `group` (a pack combining several reports) by
 * that heading, in first-seen order; `undefined` when none do.
 */
function groupMetrics(metrics: ReportResult["metrics"]): StatGroup[] | undefined {
  if (!metrics.some((m) => m.group)) return undefined;
  const groups = new Map<string, StatGroup>();
  for (const m of metrics) {
    const title = m.group ?? "";
    const group = groups.get(title) ?? { key: title, title, items: [] };
    group.items.push({ key: m.label, label: m.label, value: m.value, gap: m.gap });
    groups.set(title, group);
  }
  return [...groups.values()];
}

/**
 * A report's caveat notes and headline metrics: a flat `StatBar`, or a
 * `StatGroups` card per group when the figures come grouped. A figure flagged `gap` is marked
 * when non-zero.
 *
 * @param result The collected report.
 */
export function ReportSummary({ result }: { result: ReportResult }) {
  const groups = groupMetrics(result.metrics);
  return (
    <>
      {result.notes.length > 0 && (
        <ul className="text-muted" style={{ margin: 0, paddingLeft: "1.25rem", fontSize: "0.9rem" }}>
          {result.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {result.metrics.length > 0 &&
        (groups ? (
          <StatGroups groups={groups} />
        ) : (
          <StatBar items={result.metrics.map((m) => ({ key: m.label, label: m.label, value: m.value, gap: m.gap }))} />
        ))}
    </>
  );
}

/**
 * One report section as a headed table (gap sections carry a count badge).
 *
 * @param section The section to render.
 */
export function ReportSectionTable({ section }: { section: ReportSection }) {
  return (
    <section className="stack" style={{ gap: "0.5rem" }} aria-label={section.title}>
      <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
        <h3 style={{ margin: 0 }}>{section.title}</h3>
        {section.gap && (
          <span className={`badge badge--${section.rows.length > 0 ? "warning" : "muted"}`}>
            {section.rows.length > 0 ? `Needs attention · ${section.rows.length}` : "None"}
          </span>
        )}
      </div>
      {section.note && (
        <p className="text-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
          {section.note}
        </p>
      )}
      {section.rows.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>
          No rows.
        </p>
      ) : (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                {section.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
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
 * The generic report view: summary, then every section as a table.
 *
 * @param result The collected report (JSON form).
 */
export function ReportViewer({ result }: { result: ReportResult }) {
  if (result.eligible_projects === 0) return <ReportNothingToReport />;
  return (
    <div className="stack">
      <ReportSummary result={result} />
      {result.sections.filter((section) => section.screen !== false).map((section) => (
        <ReportSectionTable key={section.key} section={section} />
      ))}
    </div>
  );
}
