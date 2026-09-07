import { createElement } from "react";

import { t } from "../../i18n/strings";
import type { TierAModuleDefinition } from "../types";
import { ComplianceAdminPanel } from "./ComplianceAdminPanel";
import { OrgCompliancePanel } from "./OrgCompliancePanel";
import { ProjectCompliancePage } from "./ProjectCompliancePage";

/**
 * Module: modules/compliance/module
 *
 * The Compliance module's frontend registration — the frontend mirror of
 * `backend/app/modules/compliance/module.py`'s `MODULE_DEFINITION`, same
 * naming/shape convention (a `module.ts` file exporting a single
 * `moduleDefinition`, the way the backend file exports a single
 * `MODULE_DEFINITION`). `frontend/src/modules/registry.ts` auto-discovers
 * this file via `import.meta.glob('./*\/module.ts', { eager: true })`
 * (module system follow-up, 2026-09-07 — see `docs/decisions.md`'s "Module
 * system follow-up: frontend module auto-discovery" entry) rather than this
 * module hand-editing that shared file, the same "don't hand-maintain a
 * touch point every module has to remember" motivation the backend's own
 * `INSTALLED_MODULES`/registry-driven `Base.metadata` auto-import follow-ups
 * already established.
 *
 * `routes` (Phase 13, compliance-module-plan.md): this module's single
 * project-scoped route, `ProjectCompliancePage` — `path` uses React
 * Router's own `:projectId` param syntax and must match, once the router
 * segment is substituted for a real id, the `nav_path` the backend's
 * `ModuleFrontendManifest` declares (`backend/app/modules/compliance/
 * module.py`), which uses a literal `"{project_id}"` placeholder the
 * backend interpolates with a concrete id before sending it to the frontend
 * (`routers/projects.py::list_project_enabled_modules`).
 *
 * `orgAdminSections` (module system follow-up, 2026-09-07): the two
 * org-scoped panels Phase 12/14 each mounted by hand into
 * `OrgAdminPage.tsx` — `ComplianceAdminPanel` (Phase 12, standards/action
 * types/mapping types management) and `OrgCompliancePanel` (Phase 14, the
 * cross-project dashboard/table/outstanding view) — now declared here
 * instead, so `OrgAdminPage.tsx` no longer needs a hardcoded `"compliance"`/
 * `"compliance-overview"` group entry, static import, or render block per
 * module. Labels are read from `i18n/strings.ts`'s own `t()` (the same
 * static English table `useStrings()` layers terminology substitution on
 * top of) rather than duplicated as literals here — `groupCompliance`/
 * `groupComplianceOverview` contain no `{term}` tokens, so the plain,
 * unsubstituted `t()` call (this file isn't a component and can't call the
 * `useStrings()` hook) already returns the exact same string `OrgAdminPage`
 * itself would resolve for every other group's label.
 */
const strings = t();

export const moduleDefinition: TierAModuleDefinition = {
  key: "compliance",
  routes: [
    { path: "/projects/:projectId/modules/compliance", element: createElement(ProjectCompliancePage) },
  ],
  orgAdminSections: [
    {
      key: "compliance",
      label: strings.orgAdmin.groupCompliance,
      render: ({ orgId }) => createElement(ComplianceAdminPanel, { orgId }),
    },
    {
      key: "compliance-overview",
      label: strings.orgAdmin.groupComplianceOverview,
      render: ({ orgId }) => createElement(OrgCompliancePanel, { orgId }),
    },
  ],
};
