import { createElement, type ReactNode } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import type { TierAModuleDefinition } from "../types";
import { ExceptionDetailPage } from "./ExceptionDetailPage";
import { GovernanceHealthPage } from "./GovernanceHealthPage";
import { OrgHealthDefaultsPanel } from "./OrgHealthDefaultsPanel";
import { OrgProfilesPanel } from "./OrgProfilesPanel";
import { ProjectApprovalPanel } from "./ProjectApprovalPanel";
import { ProjectBaselinePanel } from "./ProjectBaselinePanel";
import { ProjectExceptionsPage } from "./ProjectExceptionsPage";
import { ProjectHealthSettingsPanel } from "./ProjectHealthSettingsPanel";
import { ProjectProfilesPanel } from "./ProjectProfilesPanel";
import { ProjectReviewPanel } from "./ProjectReviewPanel";
import { EXCEPTION_STATUS_LABEL } from "./types";

/**
 * Module: modules/traceability/module
 *
 * The Traceability & Governance module's frontend registration, the mirror of
 * `backend/app/modules/traceability/module.py`'s `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` discovers this
 * file; no core file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled modules): the Governance health page
 *   (`.../modules/traceability/health`) and the traceability exception list and record
 *   (`.../modules/traceability/exceptions[/:exceptionId]`), the paths the backend `frontend_manifest` nav entries point at.
 * - `artefactPaths`, `artefactListPaths`, `artefactStatusLabels`, `artefactInactiveStatuses`: where a link, search result
 *   or notification about a `traceability_exception` opens and how its status reads.
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

/**
 * Draws a Governance settings panel as a headed card, like every core administration section, so its tables and forms
 * sit on the card surface (docs/ux-style-guide.md, Principle 1) and its sub-headings follow a section heading.
 *
 * @param key The section's key.
 * @param title The section's heading.
 * @param panel The panel to draw inside the card.
 * @returns The card element.
 */
function inCard(key: string, title: string, panel: ReactNode): ReactNode {
  return createElement(CollapsibleSection, { sectionKey: key, title, collapsible: false, children: panel });
}

export const moduleDefinition: TierAModuleDefinition = {
  key: "traceability",
  artefactPaths: {
    traceability_exception: (projectId, id) => `/projects/${projectId}/modules/traceability/exceptions/${id}`,
  },
  artefactListPaths: {
    traceability_exception: (projectId) => `/projects/${projectId}/modules/traceability/exceptions`,
  },
  artefactStatusLabels: { traceability_exception: EXCEPTION_STATUS_LABEL },
  artefactInactiveStatuses: { traceability_exception: ["rejected", "withdrawn", "revoked"] },
  routes: [
    { path: "/projects/:projectId/modules/traceability/health", element: createElement(GovernanceHealthPage) },
    { path: "/projects/:projectId/modules/traceability/exceptions", element: createElement(ProjectExceptionsPage) },
    { path: "/projects/:projectId/modules/traceability/exceptions/:exceptionId", element: createElement(ExceptionDetailPage) },
  ],
  orgAdminSections: [
    {
      key: "governance-profiles",
      label: "Profiles",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ orgId }) => inCard("governance-profiles", "Profiles", createElement(OrgProfilesPanel, { orgId })),
    },
    {
      key: "governance-health",
      label: "Health",
      subComponent: "governance_health",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ orgId }) => inCard("governance-health", "Health", createElement(OrgHealthDefaultsPanel, { orgId })),
    },
  ],
  projectAdminSections: [
    {
      key: "governance-profiles",
      label: "Profiles",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => inCard("governance-profiles", "Profiles", createElement(ProjectProfilesPanel, { projectId })),
    },
    {
      key: "governance-approval",
      label: "Approval policy",
      subComponent: "approval_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => inCard("governance-approval", "Approval policy", createElement(ProjectApprovalPanel, { projectId })),
    },
    {
      key: "governance-review",
      label: "Review policy",
      subComponent: "review_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => inCard("governance-review", "Review policy", createElement(ProjectReviewPanel, { projectId })),
    },
    {
      key: "governance-baseline",
      label: "Baseline policy",
      subComponent: "baseline_policies",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => inCard("governance-baseline", "Baseline policy", createElement(ProjectBaselinePanel, { projectId })),
    },
    {
      key: "governance-health",
      label: "Health",
      subComponent: "governance_health",
      group: GOVERNANCE_ADMIN_GROUP,
      render: ({ projectId }) => inCard("governance-health", "Health", createElement(ProjectHealthSettingsPanel, { projectId })),
    },
  ],
};
