import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { OrgPersonasPanel } from "./OrgPersonasPanel";
import { OrgPersonaTypesPanel } from "./OrgPersonaTypesPanel";
import { PersonaDetailPage } from "./PersonaDetailPage";
import { ProjectPersonasPage } from "./ProjectPersonasPage";
import { ProjectPersonaTypesPanel } from "./ProjectPersonaTypesPanel";

/**
 * Module: modules/stakeholders/module
 *
 * The Stakeholders & Personas module's frontend registration (docs/plans/
 * module-02-stakeholders-and-personas-plan.md Phase 1.1 — Persona), the
 * mirror of `backend/app/modules/stakeholders/module.py`. Auto-discovered by
 * `modules/registry.ts` (`import.meta.glob('./*\/module.ts')`), so no core
 * file is edited to add it.
 *
 * - `routes` (project-scoped, gated on the project's enabled-modules list):
 *   the Persona list and detail pages. The detail route is also used for an
 *   org persona opened from a project, so the weight override stays reachable.
 * - `globalRoutes`: the org-scoped detail page, for an org persona opened
 *   from the org dashboard (no single project's enabled list could gate it).
 * - `orgOverviewSections`: the org persona list (org-level content).
 * - `orgAdminSections`/`projectAdminSections`: the Persona type vocabulary
 *   tiers (configuration).
 */
export const moduleDefinition: TierAModuleDefinition = {
  key: "stakeholders",
  routes: [
    { path: "/projects/:projectId/modules/stakeholders/personas", element: createElement(ProjectPersonasPage) },
    { path: "/projects/:projectId/modules/stakeholders/personas/:personaId", element: createElement(PersonaDetailPage) },
  ],
  globalRoutes: [
    { path: "/orgs/:organizationId/modules/stakeholders/personas/:personaId", element: createElement(PersonaDetailPage) },
  ],
  orgOverviewSections: [
    {
      key: "stakeholders-org-personas",
      label: "Personas",
      render: ({ orgId }) => createElement(OrgPersonasPanel, { orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "stakeholders-persona-types",
      label: "Persona Types",
      render: ({ orgId }) => createElement(OrgPersonaTypesPanel, { orgId }),
    },
  ],
  projectAdminSections: [
    {
      key: "stakeholders-persona-types",
      label: "Persona Types",
      render: ({ projectId }) => createElement(ProjectPersonaTypesPanel, { projectId }),
    },
  ],
};
