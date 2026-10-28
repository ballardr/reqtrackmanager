/**
 * Module: hooks/useReportPlacements
 *
 * Loads the resolved placements of one project or organisation (the folder a report is filed under and whether a
 * module report is hidden, by report key) for the entries the Reports picker builds itself: the requirements report
 * and packs. Catalogue entries arrive already placed by the server.
 *
 * A failed load is no placements: the picker then uses each entry's default folder.
 */
import { useEffect, useState } from "react";

import type { LayoutScope } from "../api/reportLayouts";
import { reportPlacementApi, type ResolvedPlacement } from "../api/reportPlacements";

interface Loaded {
  key: string;
  byKey: Map<string, ResolvedPlacement>;
}

/**
 * @param scope The project or organisation; `undefined` skips loading.
 * @returns The placements by report key (empty while loading or on a failed load).
 */
export function useReportPlacements(scope: LayoutScope | undefined): Map<string, ResolvedPlacement> {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = scope ? `${scope.kind}:${scope.id}` : null;

  useEffect(() => {
    if (!scope || !key) return undefined;
    let cancelled = false;
    reportPlacementApi(scope)
      .resolved()
      .then((rows) => !cancelled && setLoaded({ key, byKey: new Map(rows.map((r) => [r.report_key, r])) }))
      .catch(() => !cancelled && setLoaded({ key, byKey: new Map() }));
    return () => {
      cancelled = true;
    };
  }, [scope, key]);

  return loaded !== null && loaded.key === key ? loaded.byKey : EMPTY;
}

const EMPTY: Map<string, ResolvedPlacement> = new Map();
