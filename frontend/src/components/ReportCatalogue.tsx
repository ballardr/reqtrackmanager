/**
 * Module: components/ReportCatalogue
 *
 * The body of the Reports dialog (`ReportsDialog`): a "Report" picker (`ReportPicker`: folders, search, a type filter and favourites) over
 * every report the backend catalogue lists for a project or organisation,
 * and the selected report below it, run by `ReportRunner`. Used for a project and for an organisation, so a
 * module adds a report with a backend declaration only: no list of reports exists in the frontend.
 *
 * `extraEntries` lets a host add reports that are not in the catalogue
 * because they have their own request model (the requirement report); they appear in the same picker, first, and render the host's own
 * content. The selection is the `report` search parameter (the entry's slug
 * or extra key) so a report is linkable and survives a reload; absent or
 * unknown it falls back to the first entry. With a single entry the picker
 * is omitted. A pure presentation component over already-loaded `entries`
 * (hosts load them with `useReportCatalogue`).
 */
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { useMemo } from "react";

import { PLACEMENT_KEY_REQUIREMENTS, type ResolvedPlacement } from "../api/reportPlacements";
import type { ReportCatalogueEntry } from "../api/reports";
import { useReportPlacements } from "../hooks/useReportPlacements";
import { ReportPicker, type ReportPickerItem, type ReportPickerKind } from "./ReportPicker";
import { ReportRunner } from "./ReportRunner";

/** A report offered in the picker that is not a catalogue entry. */
export interface ExtraReportEntry {
  key: string;
  title: string;
  description: string;
  render: () => ReactNode;
  /** What the type filter matches (default `report`). */
  kind?: ReportPickerKind;
  /** Where it files unless a placement moves it (default "Platform"). */
  folder?: string;
  /** The key placements and favourites use (default `report:platform.<key>`). */
  placementKey?: string;
}

/** Where a host's extra report files unless a placement moves it. */
const DEFAULT_EXTRA_FOLDER = "Platform";

/** The picker item of an extra entry, with the scope's placement (a folder, or hidden) applied. */
function extraItem(entry: ReportCatalogueExtra, placements: Map<string, ResolvedPlacement>): ReportPickerItem | null {
  const key = entry.placementKey ?? (entry.key === "requirements" ? PLACEMENT_KEY_REQUIREMENTS : `report:platform.${entry.key}`);
  const placed = placements.get(key);
  if (placed?.hidden && key.startsWith("report:")) return null;
  return {
    id: entry.key, title: entry.title, description: entry.description, kind: entry.kind ?? "report", favouriteKey: key,
    folder: placed?.folder ?? entry.folder ?? DEFAULT_EXTRA_FOLDER,
  };
}

type ReportCatalogueExtra = ExtraReportEntry;

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
  const placementScope = useMemo(() => ({ kind: scope.kind, id: scope.id }), [scope.kind, scope.id]);
  const placements = useReportPlacements(placementScope);
  const options = useMemo<ReportPickerItem[]>(() => [
    ...extraEntries.map((e) => extraItem(e, placements)).filter((item): item is ReportPickerItem => item !== null),
    ...entries.map((e) => ({
      id: e.slug, title: e.title, description: e.description, folder: e.folder, kind: e.kind, favouriteKey: e.placement_key || e.slug,
    })),
  ], [entries, extraEntries, placements]);
  if (options.length === 0) return <p className="text-muted">No reports are available.</p>;

  const selected = options.find((o) => o.id === searchParams.get("report")) ?? options[0];
  const extra = extraEntries.find((e) => e.key === selected.id);
  const entry = extra ? undefined : entries.find((e) => e.slug === selected.id);

  return (
    <div className="stack">
      {options.length > 1 && (
        <ReportPicker
          pickerId={`${scope.kind}-reports`} items={options}
          selectedId={selected.id}
          onSelect={(id) => {
            const next = new URLSearchParams(searchParams);
            next.set("report", id);
            setSearchParams(next, { replace: true });
          }}
        />
      )}
      {extra ? extra.render() : entry && <ReportRunner
          key={entry.path} entry={entry} scope={scope} organizationId={organizationId}
          focusSection={searchParams.get("section") ?? undefined}
        />}
    </div>
  );
}
