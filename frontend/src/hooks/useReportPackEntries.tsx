/**
 * Module: hooks/useReportPackEntries
 *
 * The report packs a project or organisation can run, as entries for the Reports picker (`ReportCatalogue`'s
 * `extraEntries`): one "Pack: <name>" entry per pack the caller may run, each rendering `ReportPackRunner`. A pack
 * is a stored list of reports rather than a catalogue report, so it is offered beside the catalogue's, selectable
 * and linkable through the same `report` search parameter (`pack-<id>`).
 *
 * A failed load is no packs: the Reports surface degrades to what it showed before packs existed.
 */
import { useEffect, useMemo, useState } from "react";

import { packPlacementKey } from "../api/reportPlacements";
import { reportPackApi, reportPackRunApi, type ReportPackSummary } from "../api/reportPacks";
import type { LayoutScope } from "../api/reportLayouts";
import type { ExtraReportEntry } from "../components/ReportCatalogue";
import { ReportPackRunner } from "../components/ReportPackRunner";
import { useStrings } from "../context/TerminologyContext";

/** The picker key of a pack. */
export function packEntryKey(packId: string): string {
  return `pack-${packId}`;
}

interface Loaded {
  key: string;
  packs: ReportPackSummary[];
}

/**
 * @param scope The project or organisation to list packs for; `undefined` skips loading.
 * @param organizationId The owning organisation (branding templates).
 * @returns `entries` for the picker (empty while loading or on a failed load) and whether the first load is under way.
 */
export function useReportPackEntries(
  scope: LayoutScope | undefined, organizationId: string | undefined,
): { entries: ExtraReportEntry[]; loading: boolean } {
  const text = useStrings().reportPacks;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = scope ? `${scope.kind}:${scope.id}` : null;

  useEffect(() => {
    if (!scope || !key) return undefined;
    let cancelled = false;
    reportPackApi(scope)
      .list()
      .then((packs) => !cancelled && setLoaded({ key, packs: packs.filter((p) => !p.hidden) }))
      .catch(() => !cancelled && setLoaded({ key, packs: [] }));
    return () => {
      cancelled = true;
    };
  }, [scope, key]);

  const packs = loaded !== null && loaded.key === key ? loaded.packs : null;
  const entries = useMemo<ExtraReportEntry[]>(() => {
    if (!scope || !organizationId || !packs) return [];
    return packs.map((pack) => {
      const api = reportPackRunApi(scope, pack.id);
      return {
        key: packEntryKey(pack.id),
        title: pack.name,
        kind: "pack" as const,
        folder: pack.folder || text.defaultFolder,
        placementKey: packPlacementKey(pack.id),
        description: pack.description || text.description,
        render: () => <ReportPackRunner key={pack.id} api={api} organizationId={organizationId} name={pack.name} />,
      };
    });
  }, [scope, organizationId, packs, text]);

  return { entries, loading: key !== null && packs === null };
}
