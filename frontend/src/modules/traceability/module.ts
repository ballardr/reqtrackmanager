import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { GovernanceHealthPage } from "./GovernanceHealthPage";
import { OrgHealthDefaultsPanel } from "./OrgHealthDefaultsPanel";
import { OrgProfilesPanel } from "./OrgProfilesPanel";
import { ProjectApprovalPanel } from "./ProjectApprovalPanel";
import { ProjectBaselinePanel } from "./ProjectBaselinePanel";
import { ProjectHealthSettingsPanel } from "./ProjectHealthSettingsPanel";
import { ProjectProfilesPanel } from "./ProjectProfilesPanel";
import { ProjectReviewPanel } from "./ProjectReviewPanel";

/**
 * Module: modules/traceability/module
 *
 * The Traceability & Governance module's frontend registration, the mirror of
 * `backend/app/modules/traceability/module.py`'s `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` discovers this
 * file; no core file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled modules): the Governance health page
 *   (`.../modules/traceability/health`, the path the backend `frontend_manifest` nav entry points at).
 * - `orgAdminSections`: the organisation's governance profiles (with each profile's lifecycle, approval, review and
 *   baseline policy) and its default way of keeping governance health.
 * - `projectAdminSections`: the profiles that reach the project with its choices, the project's approval, review and
 *   baseline policy, and its health settings. Each policy section appears only while its sub-component is in effect.
 *
 * A project's lifecycle policy stays in the core Lifecycles group, which already names the profiles that require a state.
 * The sub-components of the Traceability half add their own sections to this definition.
 */

/** The Governance settings share one expandable entry in the project and organisation admin menus. */
const GOVERNANCE_ADMIN_GROUP = { key: "governance", label: "Governance" };

export const moduleDefinition: TierAModuleDefinition = {
  key: "traceability",
  routes: [
    { path: "/projects/:projectId/modules/traceability/health", element: createElement(GovernanceHealthPage) },
  ],
  orgAdminSections: [
    {
      key: "governance-profiles",
      label: "Profiles",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgProfilesPanel, { orgId }),
    },
    {
      key: "governance-health",
      label: "Health",
      subComponent: "governance_health",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgHealthDefaultsPanel, { orgId }),
    },
  ],
  projectAdminSections: [
    {
      key: "governance-profiles",
      label: "Profiles",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectProfilesPanel, { projectId }),
    },
    {
      key: "governance-approval",
      label: "Approval policy",
      subComponent: "approval_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectApprovalPanel, { projectId }),
    },
    {
      key: "governance-review",
      label: "Review policy",
      subComponent: "review_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectReviewPanel, { projectId }),
    },
    {
      key: "governance-baseline",
      label: "Baseline policy",
      subComponent: "baseline_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectBaselinePanel, { projectId }),
    },
    {
      key: "governance-health",
      label: "Health",
      subComponent: "governance_health",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectHealthSettingsPanel, { projectId }),
    },
  ],
};
