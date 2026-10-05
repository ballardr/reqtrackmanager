import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import { OrgPersonasPanel } from "./OrgPersonasPanel";
import { OrgPersonaTypesPanel } from "./OrgPersonaTypesPanel";
import { OrgStakeholdersPanel } from "./OrgStakeholdersPanel";
import { OrgStakeholderTypesPanel } from "./OrgStakeholderTypesPanel";
import { PersonaDetailPage } from "./PersonaDetailPage";
import { ProjectPersonasPage } from "./ProjectPersonasPage";
import { ProjectPersonaTypesPanel } from "./ProjectPersonaTypesPanel";
import { ProjectStakeholdersPage } from "./ProjectStakeholdersPage";
import { ProjectStakeholderTypesPanel } from "./ProjectStakeholderTypesPanel";
import { StakeholderDetailPage } from "./StakeholderDetailPage";
import { STAKEHOLDER_SCORING_SCHEME } from "./useStakeholderScheme";

/**
 * Module: modules/stakeholders/module
 *
 * The Stakeholders & Personas module's frontend registration (docs/plans/
 * module-02-stakeholders-and-personas-plan.md Phase 1.1 — Persona, Phase 1.2 —
 * Stakeholder), the mirror of `backend/app/modules/stakeholders/module.py`.
 * Auto-discovered by `modules/registry.ts` (`import.meta.glob('./*\/module.ts')`),
 * so no core file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled-modules list):
 *   the Persona and Stakeholder list and detail pages. A detail route is also
 *   used for an org record opened from a project, so a persona's weight
 *   override stays reachable.
 * - `globalRoutes`: the org-scoped detail pages, for an org record opened from
 *   the org dashboard (no single project's enabled list could gate them).
 * - `orgOverviewSections`: the org Persona and Stakeholder lists (org-level
 *   content).
 * - `orgAdminSections`/`projectAdminSections`: the Persona and Stakeholder
 *   type vocabulary tiers, and Stakeholder scoring configuration (Influence/
 *   Interest levels, default model, rating bands) through core's shared
 *   `ScoringSchemeEditor` (org) and `ProjectScoringSettings` (project), the
 *   same way Context & Strategy configures Pain Point scoring (configuration).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "stakeholders",
  routes: [
    { path: "/projects/:projectId/modules/stakeholders/personas", element: createElement(ProjectPersonasPage) },
    { path: "/projects/:projectId/modules/stakeholders/personas/:personaId", element: createElement(PersonaDetailPage) },
    { path: "/projects/:projectId/modules/stakeholders/stakeholders", element: createElement(ProjectStakeholdersPage) },
    {
      path: "/projects/:projectId/modules/stakeholders/stakeholders/:stakeholderId",
      element: createElement(StakeholderDetailPage),
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
