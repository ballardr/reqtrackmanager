/**
 * Module: modules/architecture/AllocationCoverageTiles
 *
 * The System Architecture widget of the project overview: how much of the requirements document is allocated to an element,
 * how many requirements are not, and how many suggested allocations await a decision. The figures are the server's
 * `allocation/coverage` counts, so they equal the overview metrics of the same names. Nothing is drawn while the counts
 * cannot be read (the module is off for the person), so the overview is unchanged for everyone else.
 */
import { useEffect, useState } from "react";

import { MetricTile } from "../../components/MetricTile";
import { projectAllocationApi } from "./api";
import type { AllocationCoverage } from "./types";

/** @param projectId The project whose allocation is summarised. */
export function AllocationCoverageTiles({ projectId }: { projectId: string }) {
  const [coverage, setCoverage] = useState<AllocationCoverage | null>(null);
  useEffect(() => {
    let live = true;
    projectAllocationApi(projectId).coverage()
      .then((next) => { if (live) setCoverage(next); })
      .catch(() => { if (live) setCoverage(null); });
    return () => { live = false; };
  }, [projectId]);

  if (coverage === null) return null;
  const percent = coverage.requirements === 0 ? 0 : Math.round((100 * coverage.allocated_requirements) / coverage.requirements);
  return (
    <div className="grid grid-metrics">
      <MetricTile label="Requirements allocated" value={`${percent}%`} />
      <MetricTile label="Requirements not allocated" value={coverage.requirements - coverage.allocated_requirements} />
      <MetricTile label="Suggested allocations" value={coverage.suggestions} />
    </div>
  );
}
