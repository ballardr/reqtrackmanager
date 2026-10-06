/**
 * Module: components/ReportCatalogue
 *
 * The one Reports destination (Module 1 Phase 13): a "Report" picker over
 * every report the backend catalogue lists for a project or organisation,
 * and the selected report below it, run by `ReportRunner`. Used by the
 * project Reports page and the Organisation Overview "Reports" group, so a
 * module adds a report with a backend declaration only: no list of reports
 * exists in the frontend.
 *
 * `extraEntries` lets a host add reports that are not in the catalogue
 * because they have their own request model (the project page's requirement
 * report); they appear in the same picker, first, and render the host's own
 * content. The selection is the `report` search parameter (the entry's slug
 * or extra key) so a report is linkable and survives a reload; absent or
 * unknown it falls back to the first entry. With a single entry the picker
 * is omitted. A pure presentation component over already-loaded `entries`
 * (hosts load them with `useReportCatalogue`).
 */
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import type { ReportCatalogueEntry } from "../api/reports";
import { LabeledSelect } from "./LabeledSelect";
import { ReportRunner } from "./ReportRunner";

/** A report offered in the picker that is not a catalogue entry. */
export interface ExtraReportEntry {
  key: string;
  title: string;
  description: string;
  render: () => ReactNode;
}

/**
 * @param entries Catalogue entries the caller can run.
 * @param scope What the catalogue is for: a project or an organisation, by id.
 * @param organizationId The owning organisation (branding templates).
 * @param extraEntries Host-provided entries listed before the catalogue's.
 */
export function ReportCatalogue({
  entries, scope, organizationId, extraEntries = [],
}: {
  entries: ReportCatalogueEntry[];
  scope: { kind: "project" | "organization"; id: string };
  organizationId: string;
  extraEntries?: ExtraReportEntry[];
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const multipleModules = new Set(entries.map((e) => e.module_key)).size > 1;
  const options = [
    ...extraEntries.map((e) => ({ id: e.key, label: e.title, description: e.description })),
    ...entries.map((e) => ({
      id: e.slug,
      label: multipleModules ? `${e.module_name}: ${e.title}` : e.title,
      description: e.description,
    })),
  ];
  if (options.length === 0) return <p className="text-muted">No reports are available.</p>;

  const selected = options.find((o) => o.id === searchParams.get("report")) ?? options[0];
  const extra = extraEntries.find((e) => e.key === selected.id);
  const entry = extra ? undefined : entries.find((e) => e.slug === selected.id);

  return (
    <div className="stack">
      {options.length > 1 && (
        <div className="stack" style={{ gap: "0.25rem" }}>
          <LabeledSelect
            label="Report"
            value={selected.id}
            onChange={(id) => {
              const next = new URLSearchParams(searchParams);
              next.set("report", id);
              setSearchParams(next, { replace: true });
            }}
            options={options.map((o) => ({ value: o.id, label: o.label }))}
            placeholder={null}
          />
          <span className="text-muted" style={{ fontSize: "0.9rem" }}>
            {selected.description}
          </span>
        </div>
      )}
      {extra ? extra.render() : entry && <ReportRunner
          key={entry.path} entry={entry} scope={scope} organizationId={organizationId}
          focusSection={searchParams.get("section") ?? undefined}
        />}
    </div>
  );
}
