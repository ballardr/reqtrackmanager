import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { DECISION_STATUS_LABEL } from "./types";
import { CreateDecisionDialog } from "./CreateDecisionDialog";
import { DecisionDetailPage } from "./DecisionDetailPage";
import { DecisionTemplatesPanel } from "./DecisionTemplatesPanel";
import { DecisionTypesPanel } from "./DecisionTypesPanel";
import { ProjectDecisionsPage } from "./ProjectDecisionsPage";

/**
 * Module: modules/decisions/module
 *
 * The Decision Management module's frontend registration, the mirror of `backend/app/modules/decisions/module.py`'s
 * `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` discovers this file.
 *
 * `routes`: `ProjectDecisionsPage` (the list) and `DecisionDetailPage` (a Decision's full management and context
 * view); `path` matches the `nav_path` in `module.py`'s `frontend_manifest`, with React Router's
 * `:projectId`/`:decisionId` standing in for the backend's `"{project_id}"`/`"{decision_id}"`. The list opens a
 * `DecisionQuickViewPanel` `SidePanel` on row click (rendered inline, not a route), and its "View full details" link
 * reaches `DecisionDetailPage` (`docs/ux-style-guide.md` "Pattern: entity detail panel").
 *
 * `projectAdminSections`: `DecisionTypesPanel`, the project's Decision Type vocabulary, beside the other
 * definition-table settings (Action Types, Custom Fields) on `ProjectAdminPage.tsx`.
 *
 * `orgResourceSections`: `DecisionTemplatesPanel`, the organisation-scoped Decision Template library new decisions
 * start from, on Org Resources (authored content projects share, not configuration).
 *
 * `entityAccentColor` is not set: with no `requirementDetailSections` contribution (a requirement's Decision links are
 * shown by the shared Links panel) there is no cross-module mixed list in which this kind must be told apart, so
 * nothing would read `useEntityAccentColor("decisions")`. Add it with the change that adds such a list.
 *
 * There is no `globalNavItems`, `standaloneWorkspaces`, `globalRoutes` or `overviewWidgets`: a Decision exists only
 * inside a project, and nothing calls for a project-overview tile.
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "decisions",
  linkedRecordCreators: {
    decision: { label: "Decision", render: (props) => createElement(CreateDecisionDialog, props) },
  },
  artefactPaths: {
    decision: (projectId, id) => `/projects/${projectId}/modules/decisions/${id}`,
  },
  artefactListPaths: {
    decision: (projectId) => `/projects/${projectId}/modules/decisions`,
  },
  artefactStatusLabels: { decision: DECISION_STATUS_LABEL },
  artefactInactiveStatuses: { decision: ["rejected", "superseded"] },
  routes: [
    { path: "/projects/:projectId/modules/decisions", element: createElement(ProjectDecisionsPage) },
    { path: "/projects/:projectId/modules/decisions/:decisionId", element: createElement(DecisionDetailPage) },
  ],
  projectAdminSections: [
    {
      key: "decision-types",
      label: "Decision Types",
      render: ({ projectId }) => createElement(DecisionTypesPanel, { projectId }),
    },
  ],
  orgResourceSections: [
    {
      key: "decision-templates",
      label: "Decision Templates",
      render: ({ orgId }) => createElement(DecisionTemplatesPanel, { orgId }),
    },
  ],
};
