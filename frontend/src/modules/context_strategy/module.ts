import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import {
  FUTURE_STATE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, OPEN_QUESTION_STATUS_LABEL, PAIN_POINT_STATUS_LABEL,
  STRATEGY_STATUS_LABEL,
} from "./types";
import { FutureStateDetailPage } from "./FutureStateDetailPage";
import { GuidingPrincipleDetailPage } from "./GuidingPrincipleDetailPage";
import { OpenQuestionDetailPage } from "./OpenQuestionDetailPage";
import { OpenQuestionRegisterReportView } from "./OpenQuestionRegisterReportView";
import { OrgFutureStatesPanel } from "./OrgFutureStatesPanel";
import { OrgGuidingPrinciplesPanel } from "./OrgGuidingPrinciplesPanel";
import { OrgPainPointTypesPanel } from "./OrgPainPointTypesPanel";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import { PainPointDetailPage } from "./PainPointDetailPage";
import { PainPointPrioritisationReportView } from "./PainPointPrioritisationReportView";
import { ProjectFutureStatesPage } from "./ProjectFutureStatesPage";
import { ProjectGuidingPrinciplesPage } from "./ProjectGuidingPrinciplesPage";
import { ProjectOpenQuestionsPage } from "./ProjectOpenQuestionsPage";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import { ProjectPainPointTypesPanel } from "./ProjectPainPointTypesPanel";
import { ProjectStrategiesPage } from "./ProjectStrategiesPage";
import { StrategyDetailPage } from "./StrategyDetailPage";

/**
 * Module: modules/context_strategy/module
 *
 * The Context & Strategy module's frontend registration — the frontend mirror
 * of `backend/app/modules/context_strategy/module.py`'s `MODULE_DEFINITION`,
 * same single-`moduleDefinition`-export convention every other Tier A
 * module uses. `frontend/src/modules/registry.ts` auto-discovers this file
 * via `import.meta.glob('./*\/module.ts', { eager: true })`; no hand-edit
 * to that file is needed (confirmed by reading `registry.ts`'s own
 * docstring before adding this file).
 *
 * Five artefact types (Strategy, Future State, Pain Point, Guiding Principle,
 * Open Question) each get **their own top-level nav-rail entry**, not one
 * grouped entry with tabs — diverging from `docs/ux-style-guide.md`'s usual
 * grouping preference by the user's own deliberate call. Each type adds its
 * `routes`/`globalRoutes` entries here and its own `additional_nav_entries`
 * row on the backend's `MODULE_DEFINITION.frontend_manifest`
 * (`app.modules.registry.ModuleFrontendManifest`; see `docs/decisions.md`).
 *
 * `routes` (project-scoped, gated on this project's own enabled-modules
 * list, `buildModuleRoutes.tsx`): the list and detail pages of each artefact
 * type — `path` matches the corresponding `nav_path` `module.py`'s own
 * `frontend_manifest`/`additional_nav_entries` declares.
 *
 * `globalRoutes` (always-mounted, the precedent set in
 * `modules/compliance/module.ts`): `StrategyDetailPage`, `FutureStateDetailPage`
 * and `GuidingPrincipleDetailPage`, each at an **org**-scoped path
 * (`/orgs/:organizationId/modules/context_strategy/{strategies,
 * future-states,guiding-principles}/:id`). **Decided by: Agent** — an
 * org-scoped record has no single *project* whose enabled-modules list
 * `routes` above could gate a detail route against; each detail page is one
 * shared, scope-aware component reading whichever of `projectId`/
 * `organizationId` its current route supplies, not two near-identical page
 * components.
 *
 * `orgOverviewSections`: `OrgStrategiesPanel`, `OrgFutureStatesPanel` and
 * `OrgGuidingPrinciplesPanel` — see `OrgStrategiesPanel.tsx`'s docstring for
 * the full reasoning on why `orgOverviewSections` (Org Dashboard) rather than
 * `orgAdminSections` (Org Management) was chosen.
 *
 * Pain Point and Open Question are **project-scoped only** (§6 and §9): `routes` has their list/detail pages, but there is no
 * `globalRoutes` entry and no `orgOverviewSections` contribution for them,
 * since there is no org-scoped artefact to reach via either mechanism.
 *
 * Pain Point also has a **two-tier type vocabulary** with its own admin
 * surfaces: `orgAdminSections` has `OrgPainPointTypesPanel` (the org-scoped
 * shared base tier) and `projectAdminSections` has
 * `ProjectPainPointTypesPanel` (the project-scoped override/local-type tier)
 * — see each panel's docstring for the full placement reasoning, including
 * why the type vocabulary lands on the admin sections while the artefacts'
 * own org-scoped siblings landed on `orgOverviewSections`. Guiding Principle
 * and Open Question have no configurable type vocabulary, so they need none
 * of that admin-section wiring.
 *
 * No `globalNavItems`/`standaloneWorkspaces`/`projectOverviewTiles`/
 * `requirementDetailSections`/`entityAccentColor`: none of the artefacts has
 * a cross-org standalone entity, a project-overview summary tile, or a
 * place in a mixed list of entity kinds yet.
 *
 * Pain Point scoring configuration — the backend's `pain_point` scoring
 * scheme — is edited through core's shared `ScoringSchemeEditor` (org) and
 * `ProjectScoringSettings` (project) under a "Pain Point Scoring" admin
 * section beside Pain Point Types (Decided by: User — scoring config sits
 * with the feature it scores, core stays generic).
 */
/** Backend scoring-scheme key registered by `modules/context_strategy/scoring.py`. */
const PAIN_POINT_SCORING_SCHEME = "pain_point";

export const moduleDefinition: TierAModuleDefinition = {
  key: "context_strategy",
  artefactPaths: {
    strategy: (projectId, id) => `/projects/${projectId}/modules/context_strategy/strategies/${id}`,
    future_state: (projectId, id) => `/projects/${projectId}/modules/context_strategy/future-states/${id}`,
    pain_point: (projectId, id) => `/projects/${projectId}/modules/context_strategy/pain-points/${id}`,
    guiding_principle: (projectId, id) => `/projects/${projectId}/modules/context_strategy/guiding-principles/${id}`,
    open_question: (projectId, id) => `/projects/${projectId}/modules/context_strategy/open-questions/${id}`,
  },
  artefactListPaths: {
    strategy: (projectId) => `/projects/${projectId}/modules/context_strategy/strategies`,
    future_state: (projectId) => `/projects/${projectId}/modules/context_strategy/future-states`,
    pain_point: (projectId) => `/projects/${projectId}/modules/context_strategy/pain-points`,
    guiding_principle: (projectId) => `/projects/${projectId}/modules/context_strategy/guiding-principles`,
    open_question: (projectId) => `/projects/${projectId}/modules/context_strategy/open-questions`,
  },
  orgArtefactPaths: {
    strategy: (orgId, id) => `/orgs/${orgId}/modules/context_strategy/strategies/${id}`,
    future_state: (orgId, id) => `/orgs/${orgId}/modules/context_strategy/future-states/${id}`,
    guiding_principle: (orgId, id) => `/orgs/${orgId}/modules/context_strategy/guiding-principles/${id}`,
  },
  artefactStatusLabels: {
    strategy: STRATEGY_STATUS_LABEL,
    future_state: FUTURE_STATE_STATUS_LABEL,
    pain_point: PAIN_POINT_STATUS_LABEL,
    guiding_principle: GUIDING_PRINCIPLE_STATUS_LABEL,
    open_question: OPEN_QUESTION_STATUS_LABEL,
  },
  artefactInactiveStatuses: {
    strategy: ["superseded", "retired"],
    future_state: ["superseded", "retired"],
    guiding_principle: ["superseded", "retired"],
    pain_point: ["rejected", "duplicate", "closed"],
    open_question: ["withdrawn"],
  },
  routes: [
    { path: "/projects/:projectId/modules/context_strategy/strategies", element: createElement(ProjectStrategiesPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
    { path: "/projects/:projectId/modules/context_strategy/future-states", element: createElement(ProjectFutureStatesPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/future-states/:futureStateId",
      element: createElement(FutureStateDetailPage),
    },
    { path: "/projects/:projectId/modules/context_strategy/pain-points", element: createElement(ProjectPainPointsPage) },
    {
      path: "/projects/:projectId/modules/context_strategy/pain-points/:painPointId",
      element: createElement(PainPointDetailPage),
    },
    {
      path: "/projects/:projectId/modules/context_strategy/guiding-principles",
      element: createElement(ProjectGuidingPrinciplesPage),
    },
    {
      path: "/projects/:projectId/modules/context_strategy/guiding-principles/:guidingPrincipleId",
      element: createElement(GuidingPrincipleDetailPage),
    },
    {
      path: "/projects/:projectId/modules/context_strategy/open-questions",
      element: createElement(ProjectOpenQuestionsPage),
    },
    {
      path: "/projects/:projectId/modules/context_strategy/open-questions/:openQuestionId",
      element: createElement(OpenQuestionDetailPage),
    },
  ],
  globalRoutes: [
    {
      path: "/orgs/:organizationId/modules/context_strategy/strategies/:strategyId",
      element: createElement(StrategyDetailPage),
    },
    {
      path: "/orgs/:organizationId/modules/context_strategy/future-states/:futureStateId",
      element: createElement(FutureStateDetailPage),
    },
    {
      path: "/orgs/:organizationId/modules/context_strategy/guiding-principles/:guidingPrincipleId",
      element: createElement(GuidingPrincipleDetailPage),
    },
  ],
  reportViews: {
    r1: { component: PainPointPrioritisationReportView, ownedParams: ["model_key", "rollup"] },
    r4: { component: OpenQuestionRegisterReportView },
  },
  orgOverviewSections: [
    {
      key: "context-strategy-org-strategies",
      label: "Strategy",
      render: ({ orgId }) => createElement(OrgStrategiesPanel, { orgId }),
    },
    {
      key: "context-strategy-org-future-states",
      label: "Future State",
      render: ({ orgId }) => createElement(OrgFutureStatesPanel, { orgId }),
    },
    {
      key: "context-strategy-org-guiding-principles",
      label: "Guiding Principle",
      render: ({ orgId }) => createElement(OrgGuidingPrinciplesPanel, { orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      render: ({ orgId }) => createElement(OrgPainPointTypesPanel, { orgId }),
    },
    {
      key: "context-strategy-pain-point-scoring",
      label: "Pain Point Scoring",
      render: ({ orgId }) => createElement(ScoringSchemeEditor, { orgId, schemeKey: PAIN_POINT_SCORING_SCHEME }),
    },
  ],
  projectAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      render: ({ projectId }) => createElement(ProjectPainPointTypesPanel, { projectId }),
    },
    {
      key: "context-strategy-pain-point-scoring",
      label: "Pain Point Scoring",
      render: ({ projectId }) =>
        createElement(ProjectScoringSettings, { projectId, schemeKey: PAIN_POINT_SCORING_SCHEME }),
    },
  ],
};
