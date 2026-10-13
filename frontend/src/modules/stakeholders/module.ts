import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import { NEED_STATUS_LABEL, PERSONA_STATUS_LABEL, STAKEHOLDER_STATUS_LABEL } from "./types";
import { EngagementDetailPage } from "./EngagementDetailPage";
import { NeedDetailPage } from "./NeedDetailPage";
import { OrgPersonasPanel } from "./OrgPersonasPanel";
import { OrgPersonaTypesPanel } from "./OrgPersonaTypesPanel";
import { OrgStakeholdersPanel } from "./OrgStakeholdersPanel";
import { OrgStakeholderTypesPanel } from "./OrgStakeholderTypesPanel";
import { PersonaDetailPage } from "./PersonaDetailPage";
import { ProjectEngagementsPage } from "./ProjectEngagementsPage";
import { ProjectNeedsPage } from "./ProjectNeedsPage";
import { ProjectPersonasPage } from "./ProjectPersonasPage";
import { ProjectPersonaTypesPanel } from "./ProjectPersonaTypesPanel";
import { ProjectStakeholdersPage } from "./ProjectStakeholdersPage";
import { ProjectStakeholderTypesPanel } from "./ProjectStakeholderTypesPanel";
import { ProjectStakeholderGroupsPage } from "./ProjectStakeholderGroupsPage";
import { StakeholderDetailPage } from "./StakeholderDetailPage";
import { StakeholderGroupsPanel } from "./StakeholderGroupsPanel";
import { STAKEHOLDER_SCORING_SCHEME } from "./useStakeholderScheme";

/**
 * Module: modules/stakeholders/module
 *
 * The Stakeholders & Personas module's frontend registration (docs/plans/
 * module-02-stakeholders-and-personas-plan.md Phase 1.1 — Persona, Phase 1.2 —
 * Stakeholder, Phase 2 — Stakeholder Need, Phase 5 — Engagements), the mirror of `backend/app/modules/stakeholders/module.py`.
 * Auto-discovered by `modules/registry.ts` (`import.meta.glob('./*\/module.ts')`),
 * so no core file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled-modules list):
 *   the Persona, Stakeholder, Need and Engagement list and detail pages (a Need and an
 *   Engagement are project-scoped only, so they have no global route or org panel). A detail route is also
 *   used for an org record opened from a project, so a persona's weight
 *   override stays reachable.
 * - `globalRoutes`: the org-scoped detail pages, for an org record opened from
 *   the org dashboard (no single project's enabled list could gate them).
 * - `orgOverviewSections`: the org Persona and Stakeholder lists and the
 *   Stakeholder group manager (org-level content); the project's own group
 *   manager is the `groups` route.
 * - `orgAdminSections`/`projectAdminSections`: the Persona and Stakeholder
 *   type vocabulary tiers, and Stakeholder scoring configuration (Influence/
 *   Interest levels, default model, rating bands) through core's shared
 *   `ScoringSchemeEditor` (org) and `ProjectScoringSettings` (project), the
 *   same way Context & Strategy configures Pain Point scoring (configuration).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "stakeholders",
  artefactPaths: {
    persona: (projectId, id) => `/projects/${projectId}/modules/stakeholders/personas/${id}`,
    stakeholder: (projectId, id) => `/projects/${projectId}/modules/stakeholders/stakeholders/${id}`,
    stakeholder_need: (projectId, id) => `/projects/${projectId}/modules/stakeholders/needs/${id}`,
    stakeholder_group: (projectId, id) => `/projects/${projectId}/modules/stakeholders/groups?group=${id}`,
    // A finding opens its engagement: the list route redirects `?finding=<id>`.
    engagement: (projectId, id) => `/projects/${projectId}/modules/stakeholders/engagements/${id}`,
    research_finding: (projectId, id) => `/projects/${projectId}/modules/stakeholders/engagements?finding=${id}`,
  },
  artefactStatusLabels: {
    persona: PERSONA_STATUS_LABEL,
    stakeholder: STAKEHOLDER_STATUS_LABEL,
    stakeholder_need: NEED_STATUS_LABEL,
  },
  artefactInactiveStatuses: { persona: ["retired"], stakeholder: ["retired"], stakeholder_need: ["retired"] },
  routes: [
    { path: "/projects/:projectId/modules/stakeholders/personas", element: createElement(ProjectPersonasPage) },
    { path: "/projects/:projectId/modules/stakeholders/personas/:personaId", element: createElement(PersonaDetailPage) },
    { path: "/projects/:projectId/modules/stakeholders/stakeholders", element: createElement(ProjectStakeholdersPage) },
    {
      path: "/projects/:projectId/modules/stakeholders/stakeholders/:stakeholderId",
      element: createElement(StakeholderDetailPage),
    },
    { path: "/projects/:projectId/modules/stakeholders/groups", element: createElement(ProjectStakeholderGroupsPage) },
    { path: "/projects/:projectId/modules/stakeholders/needs", element: createElement(ProjectNeedsPage) },
    { path: "/projects/:projectId/modules/stakeholders/needs/:needId", element: createElement(NeedDetailPage) },
    { path: "/projects/:projectId/modules/stakeholders/engagements", element: createElement(ProjectEngagementsPage) },
    {
      path: "/projects/:projectId/modules/stakeholders/engagements/:engagementId",
      element: createElement(EngagementDetailPage),
    },
  ],
  globalRoutes: [
    { path: "/orgs/:organizationId/modules/stakeholders/personas/:personaId", element: createElement(PersonaDetailPage) },
    {
      path: "/orgs/:organizationId/modules/stakeholders/stakeholders/:stakeholderId",
      element: createElement(StakeholderDetailPage),
    },
  ],
  orgOverviewSections: [
    {
      key: "stakeholders-org-personas",
      label: "Personas",
      render: ({ orgId }) => createElement(OrgPersonasPanel, { orgId }),
    },
    {
      key: "stakeholders-org-stakeholders",
      label: "Stakeholders",
      render: ({ orgId }) => createElement(OrgStakeholdersPanel, { orgId }),
    },
    {
      key: "stakeholders-org-groups",
      label: "Stakeholder Groups",
      render: ({ orgId }) => createElement(StakeholderGroupsPanel, { organizationId: orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "stakeholders-persona-types",
      label: "Persona Types",
      render: ({ orgId }) => createElement(OrgPersonaTypesPanel, { orgId }),
    },
    {
      key: "stakeholders-stakeholder-types",
      label: "Stakeholder Types",
      render: ({ orgId }) => createElement(OrgStakeholderTypesPanel, { orgId }),
    },
    {
      key: "stakeholders-stakeholder-scoring",
      label: "Stakeholder Scoring",
      render: ({ orgId }) => createElement(ScoringSchemeEditor, { orgId, schemeKey: STAKEHOLDER_SCORING_SCHEME }),
    },
  ],
  projectAdminSections: [
    {
      key: "stakeholders-persona-types",
      label: "Persona Types",
      render: ({ projectId }) => createElement(ProjectPersonaTypesPanel, { projectId }),
    },
    {
      key: "stakeholders-stakeholder-types",
      label: "Stakeholder Types",
      render: ({ projectId }) => createElement(ProjectStakeholderTypesPanel, { projectId }),
    },
    {
      key: "stakeholders-stakeholder-scoring",
      label: "Stakeholder Scoring",
      render: ({ projectId }) =>
        createElement(ProjectScoringSettings, { projectId, schemeKey: STAKEHOLDER_SCORING_SCHEME }),
    },
  ],
};
