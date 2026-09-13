/**
 * Module: modules/compliance/ComplianceProjectOverviewTiles
 *
 * This module's contribution to `ProjectOverviewPage.tsx`'s summary-tile
 * grid (Phase 17d, `docs/compliance-module-plan.md`) — one tile per
 * compliance standard assigned to the project, clicking through to the
 * project's own Compliance page, matching every other tile on that page's
 * "click through to what was clicked" convention.
 *
 * Extracted from a direct `getProjectComplianceStatus`/
 * `ProjectComplianceStatus` import that used to live inline in
 * `ProjectOverviewPage.tsx` (module boundary cleanup, 2026-09-08 — a core
 * page importing this module's own `api.ts`/`types.ts` directly, the same
 * "core file reaches into a specific module" mistake caught and fixed
 * elsewhere during Phase 18's own review — see `docs/decisions.md`'s
 * "Module system follow-up: on_org_created / project_nav_visible hooks"
 * entry). Registered as a `projectOverviewTiles` entry in `./module.ts`;
 * `ProjectOverviewPage.tsx` renders whatever this returns without knowing
 * anything about compliance status or standards.
 *
 * Renders nothing at all while loading or once loaded with zero assigned
 * standards — a project with neither gets no tile, rather than an empty/
 * zero-value one nobody asked to see (the same rule the pre-cleanup inline
 * version already followed).
 */
import { useEffect, useState } from "react";

import { MetricTile } from "../../components/MetricTile";
import { getProjectComplianceStatus } from "./api";
import type { ProjectComplianceStatus } from "./types";

export function ComplianceProjectOverviewTiles({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<ProjectComplianceStatus[]>([]);

  useEffect(() => {
    getProjectComplianceStatus(projectId)
      .then(setStatus)
      .catch(() => setStatus([]));
  }, [projectId]);

  return (
    <>
      {status.map((s) => (
        <MetricTile
          key={s.standard_id}
          label={s.standard_name}
          value={`${Math.round(s.compliance_percentage)}%`}
          to={`/projects/${projectId}/modules/compliance`}
        />
      ))}
    </>
  );
}
