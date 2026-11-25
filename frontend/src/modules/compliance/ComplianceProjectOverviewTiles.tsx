/**
 * Module: modules/compliance/ComplianceProjectOverviewTiles
 *
 * This module's overview widget (`standards_status`): one tile per compliance standard assigned to the project, each linking
 * to the project's Compliance page. The module's registration wraps the tiles in a `.grid-metrics` grid, so the widget is as
 * wide as the person makes it and the page hides it when it has no tile. It is registered as an `overviewWidgets` entry in
 * `./module.ts`; the overview renders what it returns without knowing about compliance status (docs/decisions.md, "Module
 * system follow-up: on_org_created / project_nav_visible hooks"). It renders nothing while loading or with zero assigned
 * standards, rather than an empty tile.
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
