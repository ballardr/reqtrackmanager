import { createElement } from "react";

import { ProjectScoringSettings } from "../../components/ProjectScoringSettings";
import { ScoringSchemeEditor } from "../../components/ScoringSchemeEditor";
import type { TierAModuleDefinition } from "../types";
import {
  OrgExternalSystemsPanel, OrgRequestChannelsPanel, ProjectExternalSystemsPanel, ProjectRequestChannelsPanel,
} from "./FeedbackListPanels";
import { CreateRequestDialog } from "./CreateRequestDialog";
import { OrgRequestsPanel } from "./OrgRequestsPanel";
import { ProjectRequestsPage } from "./ProjectRequestsPage";
import { RequestDetailPage } from "./RequestDetailPage";
import { EXTERNAL_REFERENCES_KEY } from "./useExternalReferences";
import { SubmissionPolicyPanel } from "./SubmissionPolicyPanel";
import { REQUEST_STATUS_LABEL } from "./types";

/**
 * Module: modules/product_feedback/module
 *
 * The Product Feedback module's frontend registration — the frontend mirror of `backend/app/modules/
 * product_feedback/module.py`'s `MODULE_DEFINITION`, same single-`moduleDefinition`-export convention every other
 * Tier A module uses. `frontend/src/modules/registry.ts` auto-discovers this file.
 *
 * `artefactPaths` / `orgArtefactPaths` / `artefactListPaths`: where a request, an inbox request and the project's
 * request list live, so links, notifications and search hits resolve without core naming this module.
 *
 * `routes`: the project list and detail pages, gated on the project's enabled modules like every Tier A route.
 * `globalRoutes`: the detail page of an inbox request at its organisation path. An organisation-owned record has no
 * single project whose enabled-modules list could gate the route (the same reasoning as an organisation Strategy),
 * and `RequestDetailPage` is one scope-aware component serving both paths.
 *
 * `orgOverviewSections`: the inbox, as day-to-day content on the Organisation Overview rather than configuration.
 * `orgAdminSections` / `projectAdminSections`: the scoring configuration, through core's shared scoring editors (the
 * module only names its scheme key), the project's submission setting, and the two classified lists (external systems,
 * request channels) through the shared type vocabulary panels.
 *
 * `artefactInactiveStatuses`: a declined or duplicate request is greyed out in shared lists.
 */
const REQUEST_SCORING_SCHEME = "enhancement_request";

/** The Product Feedback settings share one expandable entry in the project and organisation admin menus. */
const PRODUCT_FEEDBACK_ADMIN_GROUP = { key: "product-feedback", label: "Product Feedback" };

export const moduleDefinition: TierAModuleDefinition = {
  key: "product_feedback",
  linkedRecordCreators: {
    enhancement_request: { label: "Enhancement Request", render: (props) => createElement(CreateRequestDialog, props) },
  },
  artefactPaths: {
    enhancement_request: (projectId, id) => `/projects/${projectId}/modules/product_feedback/requests/${id}`,
  },
  artefactListPaths: {
    enhancement_request: (projectId) => `/projects/${projectId}/modules/product_feedback/requests`,
  },
  orgArtefactPaths: {
    enhancement_request: (orgId, id) => `/orgs/${orgId}/modules/product_feedback/requests/${id}`,
  },
  // Creating a Pain Point (or Requirement) from a request's Links panel links it with the relationship the request means.
  preferredLinkPhrases: { enhancement_request: { pain_point: "Addresses", requirement: "Realised by" } },
  artefactStatusLabels: { enhancement_request: REQUEST_STATUS_LABEL },
  artefactInactiveStatuses: { enhancement_request: ["declined", "duplicate"] },
  routes: [
    { path: "/projects/:projectId/modules/product_feedback/requests", element: createElement(ProjectRequestsPage) },
    { path: "/projects/:projectId/modules/product_feedback/requests/:requestId", element: createElement(RequestDetailPage) },
  ],
  globalRoutes: [
    { path: "/orgs/:organizationId/modules/product_feedback/requests/:requestId", element: createElement(RequestDetailPage) },
  ],
  orgOverviewSections: [
    {
      key: "product-feedback-inbox",
      label: "Request inbox",
      render: ({ orgId }) => createElement(OrgRequestsPanel, { orgId }),
    },
  ],
  orgAdminSections: [
    {
      key: "product-feedback-scoring",
      label: "Request Scoring",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      render: ({ orgId }) => createElement(ScoringSchemeEditor, { orgId, schemeKey: REQUEST_SCORING_SCHEME }),
    },
    {
      key: "product-feedback-external-systems",
      label: "External Systems",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      subComponent: EXTERNAL_REFERENCES_KEY,
      render: ({ orgId }) => createElement(OrgExternalSystemsPanel, { orgId }),
    },
    {
      key: "product-feedback-request-channels",
      label: "Request Channels",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgRequestChannelsPanel, { orgId }),
    },
  ],
  projectAdminSections: [
    {
      key: "product-feedback-settings",
      label: "Submission policy",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      render: ({ projectId }) => createElement(SubmissionPolicyPanel, { projectId }),
    },
    {
      key: "product-feedback-scoring",
      label: "Request Scoring",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectScoringSettings, { projectId, schemeKey: REQUEST_SCORING_SCHEME }),
    },
    {
      key: "product-feedback-external-systems",
      label: "External Systems",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      subComponent: EXTERNAL_REFERENCES_KEY,
      render: ({ projectId }) => createElement(ProjectExternalSystemsPanel, { projectId }),
    },
    {
      key: "product-feedback-request-channels",
      label: "Request Channels",
      group: PRODUCT_FEEDBACK_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ProjectRequestChannelsPanel, { projectId }),
    },
  ],
};
