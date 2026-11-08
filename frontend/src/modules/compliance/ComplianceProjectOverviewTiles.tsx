/**
 * Module: modules/compliance/ComplianceProjectOverviewTiles
 *
 * This module's overview widget (`standards_status`) — one tile per
 * compliance standard assigned to the project, clicking through to the
 * project's own Compliance page, matching every other tile on that page's
 * "click through to what was clicked" convention. The module's registration wraps the tiles in a
 * `.grid-metrics` grid, so the widget is as wide as the person makes it and the page hides it when it
 * has no tile to show.
 *
 * Extracted from a direct `getProjectComplianceStatus`/
 * `ProjectComplianceStatus` import that used to live inline in
 * `ProjectOverviewPage.tsx` (module boundary cleanup, 2026-09-08 — a core
 * page importing this module's own `api.ts`/`types.ts` directly, the same
 * "core file reaches into a specific module" mistake caught and fixed
 * elsewhere — see `docs/decisions.md`'s
 * "Module system follow-up: on_org_created / project_nav_visible hooks"
 * entry). Registered as an `overviewWidgets` entry in `./module.ts`;
 * the overview renders whatever this returns without knowing
 * anything about compliance status or standards.
 *
 * Renders nothing at all while loading or once loaded with zero assigned
 * standards — a project with neither gets no tile, rather than an empty/
 * zero-value one nobody asked to see (the same rule the pre-cleanup inline
 * version already followed).
 */
import { useEffect, useState } from "react";

import type { ProjectScope } from "../../api/projectScope";
import { MetricTile } from "../../components/MetricTile";
import { getProjectComplianceStatus } from "./api";
import type { ProjectComplianceStatus } from "./types";

/**
 * @param projectId The project whose overview this is.
 * @param projectScope The overview's list scope; a widened overview adds the related projects' assignments,
 *   each tile naming its project.
 */
export function ComplianceProjectOverviewTiles({ projectId, projectScope = "this" }: { projectId: string; projectScope?: ProjectScope }) {
  const [status, setStatus] = useState<ProjectComplianceStatus[]>([]);

  useEffect(() => {
    getProjectComplianceStatus(projectId, projectScope)
      .then(setStatus)
      .catch(() => setStatus([]));
  }, [projectId, projectScope]);

  return (
    <>
      {status.map((s) => (
        <MetricTile
          key={s.project_compliance_id}
          label={s.from_project_id ? `${s.standard_name} · ${s.project_name}` : s.standard_name}
          value={`${Math.round(s.compliance_percentage)}%`}
          to={`/projects/${s.from_project_id ?? projectId}/modules/compliance`}
        />
      ))}
    </>
  );
}
