import { createElement } from "react";

import { t } from "../../i18n/strings";
import type { TierAModuleDefinition } from "../types";
import {
  COMPLIANCE_ACTION_ASSESSMENT_STATUS_LABEL, COMPLIANCE_STANDARD_VERSION_STATUS_LABEL, COMPLIANCE_STATUS_LABEL,
} from "./types";
import { ComplianceGlobalNavLink } from "./ComplianceGlobalNavLink";
import { ComplianceStatusPage } from "./ComplianceStatusPage";
import { ComplianceProjectOverviewTiles } from "./ComplianceProjectOverviewTiles";
import { ComplianceSettingsPage } from "./ComplianceSettingsPage";
import { CreateEvidenceDialog } from "./CreateEvidenceDialog";
import { EvidenceDetailPage } from "./EvidenceDetailPage";
import { evidencePath, projectCompliancePath, STANDARD_WORKSPACE_PATH } from "./paths";
import { OrgComplianceAttentionWidget, OrgComplianceSummaryWidget } from "./OrgComplianceWidgets";
import { ProjectCompliancePage } from "./ProjectCompliancePage";
import { StandardListPage } from "./StandardListPage";
import { StandardNavSection } from "./StandardNavSection";
import { StandardWorkspacePage } from "./StandardWorkspacePage";

/**
 * Module: modules/compliance/module
 *
 * The Compliance module's frontend registration, the mirror of `backend/app/modules/compliance/module.py`'s `MODULE_DEFINITION`
 * (a `module.ts` exporting a single `moduleDefinition`). `frontend/src/modules/registry.ts` auto-discovers it through
 * `import.meta.glob('./*\/module.ts', { eager: true })` (docs/decisions.md, "Module system follow-up: frontend module
 * auto-discovery"), so no shared file is edited by hand.
 * - `routes`: `ProjectCompliancePage` and `EvidenceDetailPage`; `path` uses React Router's `:projectId` and must match the
 *   `nav_path` of the backend's `ModuleFrontendManifest` once `"{project_id}"` is interpolated
 *   (`routers/projects.py::list_project_enabled_modules`).
 * - `orgAdminSections` is empty: standards, action types and mapping types are managed on the `/standards` tab
 *   (`StandardListPage.tsx`, `StandardWorkspacePage.tsx`, `ComplianceSettingsPage.tsx`); the cross-project views are its By
 *   standard and Outstanding tabs (`ComplianceStatusPage.tsx`) and the `orgOverviewWidgets`. Labels come from `i18n/strings.ts`'s
 *   `t()`: none contains a `{term}` token and this file cannot call `useStrings()`, so the plain call returns the same string.
 * - `orgOverviewWidgets` (`modules/types.ts`): two organisation overview widgets (headline tiles and an attention card,
 *   `OrgComplianceWidgets.tsx`) that an administrator places like any other widget.
 * - `globalNavItems` / `standaloneWorkspaces`: the "Compliance Standards" nav-rail tab and the "Standard" left-nav section, thin
 *   `createElement` wrappers around `ComplianceGlobalNavLink.tsx` and `StandardNavSection.tsx`; `Layout.tsx` imports neither.
 * - `globalRoutes`: `StandardListPage.tsx` (`/standards`), `ComplianceStatusPage.tsx` (`/standards/by-standard`,
 *   `/standards/outstanding`), `StandardWorkspacePage.tsx` (`/standards/:standardId/:section?/:versionId?`, the trailing param
 *   deep-linking a version from `StandardNavSection.tsx`) and `ComplianceSettingsPage.tsx` (`/standards/settings/:orgId/:group?`).
 *   They are registered here so `App.tsx` imports none of them (see `docs/decisions.md`).
 * - `projectOverviewTiles`: the per-standard compliance-status tiles on the project overview; `ComplianceProjectOverviewTiles.tsx`
 *   owns the fetch and `ProjectOverviewPage.tsx` renders it without knowing compliance exists (docs/decisions.md, "Module system
 *   follow-up: on_org_created / project_nav_visible hooks").
 * - A core requirement's links to a standard's clauses are ordinary links (artefact type `compliance_requirement`) shown by the
 *   shared Links panel, so no requirement-page section exists; a clause belongs to an organisation-level standard, so its path
 *   is the Standards page.
 */

export const moduleDefinition: TierAModuleDefinition = {
  key: "compliance",
  linkedRecordCreators: {
    compliance_evidence: { label: "Evidence", render: (props) => createElement(CreateEvidenceDialog, props) },
  },
  artefactPaths: {
    compliance_requirement: () => "/standards",
    compliance_evidence: evidencePath,
    // Assessments are managed from the project's Compliance page, which has no page per assessment.
    project_compliance_requirement: (projectId) => projectCompliancePath(projectId),
    compliance_required_action_assessment: (projectId) => projectCompliancePath(projectId),
  },
  // Where a Compliance notification opens (the backend's `notification_target_kinds`): a project assignment, review or
  // target date opens the project's Compliance page; a standard grant or standard-level review opens the standard.
  notificationTargets: {
    project_compliance: (n) => (n.project_id ? projectCompliancePath(n.project_id) : null),
    standard: (n) => (n.entity_type === "compliance_standard" && n.entity_id ? `/standards/${n.entity_id}` : null),
  },
  artefactListPaths: {
    compliance_evidence: (projectId) => projectCompliancePath(projectId, "evidence"),
  },
  artefactStatusLabels: {
    compliance_requirement: COMPLIANCE_STANDARD_VERSION_STATUS_LABEL,
    project_compliance_requirement: COMPLIANCE_STATUS_LABEL,
    compliance_required_action_assessment: COMPLIANCE_ACTION_ASSESSMENT_STATUS_LABEL,
  },
  artefactInactiveStatuses: { compliance_requirement: ["retired"] },
  routes: [
    { path: "/projects/:projectId/modules/compliance", element: createElement(ProjectCompliancePage) },
    { path: "/projects/:projectId/modules/compliance/evidence/:evidenceId", element: createElement(EvidenceDetailPage) },
  ],
  globalRoutes: [
    { path: "/standards", element: createElement(StandardListPage) },
    { path: "/standards/by-standard", element: createElement(ComplianceStatusPage, { view: "by-standard" }) },
    { path: "/standards/outstanding", element: createElement(ComplianceStatusPage, { view: "outstanding" }) },
    { path: "/standards/settings/:orgId/:group?", element: createElement(ComplianceSettingsPage) },
    { path: "/standards/:standardId/:section?/:versionId?", element: createElement(StandardWorkspacePage) },
  ],
  orgOverviewWidgets: [
    { key: "summary", render: ({ orgId }) => createElement(OrgComplianceSummaryWidget, { orgId }) },
    { key: "attention", render: ({ orgId }) => createElement(OrgComplianceAttentionWidget, { orgId }) },
  ],
  globalNavItems: [
    {
      key: "compliance-standards",
      render: ({ railCollapsed }) => createElement(ComplianceGlobalNavLink, { railCollapsed }),
    },
  ],
  standaloneWorkspaces: [
    {
      key: "standard",
      // Excludes `/standards/settings/:orgId` (`ComplianceSettingsPage.tsx`): it names an organisation, not a standard, and is a
      // `ResourceMenu` page with no "Standard" nav section.
      matchPath: STANDARD_WORKSPACE_PATH,
      render: ({ entityId, railCollapsed }) => createElement(StandardNavSection, { entityId, railCollapsed }),
    },
  ],
  // The search page's Scope filter offers "This standard" while the viewer is on one of its pages; the id
  // is the one the backend's `search_scopes["standard"]` resolves. Excludes the org settings route, as above.
  searchScopes: [
    {
      key: "standard",
      label: t().search.scopeThisStandard,
      match: (pathname) => STANDARD_WORKSPACE_PATH.exec(pathname)?.[1] ?? null,
    },
  ],
  // One tile per assigned standard, as an ordinary overview widget (placed, sized, hidden or removed like any other).
  overviewWidgets: [
    {
      key: "standards_status",
      render: ({ projectId, projectScope }) =>
        createElement("div", { className: "grid grid-metrics" }, createElement(ComplianceProjectOverviewTiles, { projectId, projectScope })),
    },
  ],
  // The module registers its own colour (see `modules/entityAccentColor.ts`), not a core map entry or CSS variable;
  // `RequirementTraceabilityLinksSection.tsx` resolves it with `useEntityAccentColor("compliance")`.
  entityAccentColor: { light: "#c2410c", dark: "#fdba74" },
};
