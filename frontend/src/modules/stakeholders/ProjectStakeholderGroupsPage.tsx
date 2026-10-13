/**
 * Module: modules/stakeholders/ProjectStakeholderGroupsPage
 *
 * The project-scoped Stakeholder group manager route, mounted at
 * `/projects/:projectId/modules/stakeholders/groups` (`module.ts`, reached via the
 * "Groups" nav-rail entry). A thin page around `StakeholderGroupsPanel`; the
 * `?group=<id>` query selects a group on load, which is where a relationship to a
 * group (`artefactPaths.stakeholder_group`) lands.
 */
import { useParams, useSearchParams } from "react-router-dom";

import { StakeholderGroupsPanel } from "./StakeholderGroupsPanel";

export function ProjectStakeholderGroupsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [params] = useSearchParams();
  if (!projectId) return null;
  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Stakeholder groups</h1>
      <StakeholderGroupsPanel projectId={projectId} initialGroupId={params.get("group")} />
    </div>
  );
}
