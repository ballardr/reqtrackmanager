import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import {
  FUTURE_STATE_STATUS_LABEL, GUIDING_PRINCIPLE_STATUS_LABEL, OPEN_QUESTION_STATUS_LABEL, PAIN_POINT_STATUS_LABEL,
  STRATEGY_STATUS_LABEL,
} from "./types";
import { CreateFutureStateDialog, CreateGuidingPrincipleDialog, CreateOpenQuestionDialog, CreateStrategyDialog } from "./CreateLinkedRecordDialogs";
import { CreatePainPointDialog } from "./CreatePainPointDialog";
import { FutureStateDetailPage } from "./FutureStateDetailPage";
import { GuidingPrincipleDetailPage } from "./GuidingPrincipleDetailPage";
import { OpenQuestionDetailPage } from "./OpenQuestionDetailPage";
import { OpenQuestionRegisterReportView } from "./OpenQuestionRegisterReportView";
import { OrgFutureStatesPanel } from "./OrgFutureStatesPanel";
import { OrgGuidingPrinciplesPanel } from "./OrgGuidingPrinciplesPanel";
import { OrgPainPointTypesPanel } from "./OrgPainPointTypesPanel";
import { OrgPainPointSubmissionPanel, ProjectPainPointSubmissionPanel } from "./PainPointSubmissionPanel";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import { PainPointDetailPage } from "./PainPointDetailPage";
import { PainPointPrioritisationReportView } from "./PainPointPrioritisationReportView";
import { ProjectFutureStatesPage } from "./ProjectFutureStatesPage";
import { ProjectGuidingPrinciplesPage } from "./ProjectGuidingPrinciplesPage";
import { ProjectOpenQuestionsPage } from "./ProjectOpenQuestionsPage";
import { ProjectPainPointsPage } from "./ProjectPainPointsPage";
import { ORG_FUTURE_STATES_SECTION_KEY, ORG_GUIDING_PRINCIPLES_SECTION_KEY, ORG_STRATEGIES_SECTION_KEY } from "./orgResourceKeys";
import { ProjectPainPointTypesPanel } from "./ProjectPainPointTypesPanel";
import { ProjectStrategiesPage } from "./ProjectStrategiesPage";
import { StrategyDetailPage } from "./StrategyDetailPage";

/**
 * Module: modules/context_strategy/module
 *
 * The Context & Strategy module's frontend registration, the mirror of `backend/app/modules/context_strategy/module.py`'s
 * `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` discovers this file through
 * `import.meta.glob('./*\/module.ts', { eager: true })`.
 *
 * Five artefact types (Strategy, Future State, Pain Point, Guiding Principle, Open Question) each have their own
 * top-level nav-rail entry, not one grouped entry with tabs. Each type adds its `routes` / `globalRoutes` entries here
 * and an `additional_nav_entries` row on the backend's `MODULE_DEFINITION.frontend_manifest`
 * (`app.modules.registry.ModuleFrontendManifest`; see `docs/decisions.md`).
 *
 * `routes` (project-scoped, gated on the project's enabled modules, `buildModuleRoutes.tsx`): the list and detail
 * pages of each type; `path` matches the `nav_path` declared in `module.py`.
 *
 * `globalRoutes` (always mounted, as in `modules/compliance/module.ts`): `StrategyDetailPage`, `FutureStateDetailPage`
 * and `GuidingPrincipleDetailPage` at organisation-scoped paths
 * (`/orgs/:organizationId/modules/context_strategy/{strategies,future-states,guiding-principles}/:id`). An
 * organisation-scoped record has no single project whose enabled modules could gate a route, and each detail page is
 * one scope-aware component reading whichever of `projectId`/`organizationId` the route supplies.
 *
 * `orgResourceSections`: `OrgStrategiesPanel`, `OrgFutureStatesPanel` and `OrgGuidingPrinciplesPanel` (placement
 * reasoning in `OrgStrategiesPanel.tsx`).
 *
 * Pain Point and Open Question are project-scoped only: `routes` has their pages, with no `globalRoutes` or
 * `orgResourceSections` entry. Pain Point has a two-tier type vocabulary: `orgAdminSections` has
 * `OrgPainPointTypesPanel` and `projectAdminSections` has `ProjectPainPointTypesPanel`. Guiding Principle and Open
 * Question have no type vocabulary.
 *
 * There is no `globalNavItems`, `standaloneWorkspaces`, `overviewWidgets`, `requirementDetailSections` or
 * `entityAccentColor`: none of the types is a cross-organisation standalone entity, a project-overview tile or a row
 * in a mixed list of entity kinds.
 *
 * Pain Point scoring configuration (the backend's `pain_point` scoring scheme) is edited through core's
 * `ScoringSchemeEditor` (organisation) and `ProjectScoringSettings` (project) under a "Pain Point Scoring" admin
 * section beside Pain Point Types: scoring configuration sits with the feature it scores and core stays generic.
 */
/** Backend scoring-scheme key registered by `modules/context_strategy/scoring.py`. */
const PAIN_POINT_SCORING_SCHEME = "pain_point";

/** The Pain Point settings share one expandable entry in the project and organisation admin menus. */
const PAIN_POINT_ADMIN_GROUP = { key: "pain-points", label: "Pain Points" };

export const moduleDefinition: TierAModuleDefinition = {
  key: "context_strategy",
  artefactPaths: {
    strategy: (projectId, id) => `/projects/${projectId}/modules/context_strategy/strategies/${id}`,
    future_state: (projectId, id) => `/projects/${projectId}/modules/context_strategy/future-states/${id}`,
    pain_point: (projectId, id) => `/projects/${projectId}/modules/context_strategy/pain-points/${id}`,
    guiding_principle: (projectId, id) => `/projects/${projectId}/modules/context_strategy/guiding-principles/${id}`,
    open_question: (projectId, id) => `/projects/${projectId}/modules/context_strategy/open-questions/${id}`,
  },
  // A request (or any record a link type reaches Pain Points from) can create and link one from its Links panel.
  linkedRecordCreators: {
    pain_point: { label: "Pain Point", render: (props) => createElement(CreatePainPointDialog, props) },
    strategy: { label: "Strategy", render: (props) => createElement(CreateStrategyDialog, props) },
    future_state: { label: "Future State", render: (props) => createElement(CreateFutureStateDialog, props) },
    guiding_principle: { label: "Guiding Principle", render: (props) => createElement(CreateGuidingPrincipleDialog, props) },
    open_question: { label: "Open Question", render: (props) => createElement(CreateOpenQuestionDialog, props) },
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
  orgResourceSections: [
    {
      key: ORG_STRATEGIES_SECTION_KEY,
      label: "Strategy",
      render: ({ orgId }) => createElement(OrgStrategiesPanel, { orgId }),
    },
    {
      key: ORG_FUTURE_STATES_SECTION_KEY,
      label: "Future State",
      render: ({ orgId }) => createElement(OrgFutureStatesPanel, { orgId }),
    },
    {
      key: ORG_GUIDING_PRINCIPLES_SECTION_KEY,
      label: "Guiding Principle",
      render: ({ orgId }) => createElement(OrgGuidingPrinciplesPanel, { orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgPainPointTypesPanel, { orgId }),
    },
    {
      key: "context-strategy-pain-point-submission",
      label: "Pain Point Submission",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgPainPointSubmissionPanel, { orgId }),
    },
    {
      key: "context-strategy-pain-point-scoring",
      label: "Pain Point Scoring",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ orgId }) => createElement(ScoringSchemeEditor, { orgId, schemeKey: PAIN_POINT_SCORING_SCHEME }),
    },
  ],
  projectAdminSections: [
    {
      key: "context-strategy-pain-point-types",
      label: "Pain Point Types",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectPainPointTypesPanel, { projectId }),
    },
    {
      key: "context-strategy-pain-point-submission",
      label: "Pain Point Submission",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectPainPointSubmissionPanel, { projectId }),
    },
    {
      key: "context-strategy-pain-point-scoring",
      label: "Pain Point Scoring",
      group: PAIN_POINT_ADMIN_GROUP,
      render: ({ projectId }) =>
        createElement(ProjectScoringSettings, { projectId, schemeKey: PAIN_POINT_SCORING_SCHEME }),
    },
  ],
};
