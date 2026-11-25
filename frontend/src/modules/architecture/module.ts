import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { AllocationPanel } from "./AllocationPanel";
import { AllocationCoverageTiles } from "./AllocationCoverageTiles";
import { ArchitectureTypesPanel } from "./ArchitectureTypesPanel";
import { ConnectionDetailPage } from "./ConnectionDetailPage";
import { BaselineDetailPage } from "./BaselineDetailPage";
import { CreateDiagramDialog } from "./CreateDiagramDialog";
import { CreateElementDialog } from "./CreateElementDialog";
import { DiagramEditorPage } from "./DiagramEditorPage";
import { ElementDetailPage } from "./ElementDetailPage";
import { OrgElementsPanel } from "./OrgElementsPanel";
import { StateMachineEditorPage } from "./StateMachineEditorPage";
import { StateRedirect } from "./StateRedirect";
import { ProjectSharingPage } from "./ProjectSharingPage";
import { SymbolLibraryPanel } from "./SymbolLibraryPanel";
import { ArchitectureListRedirect, SystemArchitecturePage } from "./SystemArchitecturePage";
import { architectureTabPath } from "./architectureTabs";
import { ARCHITECTURE_INACTIVE_STATUSES, ARCHITECTURE_STATUS_LABEL } from "./types";

/**
 * Module: modules/architecture/module
 *
 * The System Architecture module's frontend registration, the mirror of `backend/app/modules/architecture/module.py`'s
 * `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` auto-discovers this file.
 * - `artefactPaths` / `artefactListPaths`: where each record type and its list live, so links, notifications and search hits
 *   resolve without core naming this module. `artefactStatusLabels` / `artefactInactiveStatuses`: a retired record is
 *   shown as inactive in shared lists.
 * - `routes`: the System Architecture page (tabs), the redirects from the list paths to its tabs, the detail pages (a state
 *   redirects to its state machine diagram) and the Sharing page (collections). `overviewWidgets`: the allocation coverage tiles.
 * - `requirementDetailSections`: the "Architecture" allocation card on a requirement, shown only when it has something to list.
 * - `linkedRecordCreators`: "Create new" element or diagram in another record's Links panel (a connection needs two elements).
 * - `projectAdminSections` / `orgAdminSections`: types, domains and the project's symbol library under one "System
 *   Architecture" group. `orgResourceSections`: the organisation's elements, collections and symbol library on Org Resources.
 */

/** The architecture settings share one expandable entry in the project and organisation admin menus. */
const ARCHITECTURE_ADMIN_GROUP = { key: "architecture", label: "System Architecture" };

export const moduleDefinition: TierAModuleDefinition = {
  key: "architecture",
  overviewWidgets: [
    {
      key: "allocation_coverage",
      render: ({ projectId }) => createElement(AllocationCoverageTiles, { projectId }),
    },
  ],
  requirementDetailSections: [
    {
      key: "allocation",
      render: ({ projectId, requirementId, refreshToken }) =>
        createElement(AllocationPanel, { projectId, perspective: { kind: "requirement", requirementId }, refreshToken }),
    },
  ],
  linkedRecordCreators: {
    architecture_element: { label: "Element", render: (props) => createElement(CreateElementDialog, props) },
    architecture_diagram: { label: "Diagram", render: (props) => createElement(CreateDiagramDialog, props) },
  },
  artefactPaths: {
    architecture_element: (projectId, id) => `/projects/${projectId}/modules/architecture/elements/${id}`,
    architecture_connection: (projectId, id) => `/projects/${projectId}/modules/architecture/connections/${id}`,
    architecture_diagram: (projectId, id) => `/projects/${projectId}/modules/architecture/diagrams/${id}`,
    architecture_state_machine_diagram: (projectId, id) => `/projects/${projectId}/modules/architecture/state-machine-diagrams/${id}`,
    architecture_state: (projectId, id) => `/projects/${projectId}/modules/architecture/states/${id}`,
  },
  artefactListPaths: {
    architecture_element: (projectId) => architectureTabPath(projectId, "elements"),
    architecture_connection: (projectId) => architectureTabPath(projectId, "connections"),
    architecture_diagram: (projectId) => architectureTabPath(projectId, "diagrams"),
    architecture_state_machine_diagram: (projectId) => architectureTabPath(projectId, "diagrams"),
    architecture_state: (projectId) => architectureTabPath(projectId, "diagrams"),
  },
  artefactStatusLabels: {
    architecture_element: ARCHITECTURE_STATUS_LABEL,
    architecture_connection: ARCHITECTURE_STATUS_LABEL,
    architecture_diagram: ARCHITECTURE_STATUS_LABEL,
    architecture_state_machine_diagram: ARCHITECTURE_STATUS_LABEL,
    architecture_state: ARCHITECTURE_STATUS_LABEL,
  },
  artefactInactiveStatuses: {
    architecture_element: ARCHITECTURE_INACTIVE_STATUSES,
    architecture_connection: ARCHITECTURE_INACTIVE_STATUSES,
    architecture_diagram: ARCHITECTURE_INACTIVE_STATUSES,
    architecture_state_machine_diagram: ARCHITECTURE_INACTIVE_STATUSES,
    architecture_state: ARCHITECTURE_INACTIVE_STATUSES,
  },
  routes: [
    { path: "/projects/:projectId/modules/architecture", element: createElement(SystemArchitecturePage) },
    { path: "/projects/:projectId/modules/architecture/elements", element: createElement(ArchitectureListRedirect, { tab: "elements" }) },
    { path: "/projects/:projectId/modules/architecture/elements/:elementId", element: createElement(ElementDetailPage) },
    { path: "/projects/:projectId/modules/architecture/connections", element: createElement(ArchitectureListRedirect, { tab: "connections" }) },
    { path: "/projects/:projectId/modules/architecture/connections/:connectionId", element: createElement(ConnectionDetailPage) },
    { path: "/projects/:projectId/modules/architecture/diagrams", element: createElement(ArchitectureListRedirect, { tab: "diagrams" }) },
    { path: "/projects/:projectId/modules/architecture/diagrams/:diagramId", element: createElement(DiagramEditorPage) },
    { path: "/projects/:projectId/modules/architecture/state-machine-diagrams/:diagramId", element: createElement(StateMachineEditorPage) },
    { path: "/projects/:projectId/modules/architecture/states/:stateId", element: createElement(StateRedirect) },
    { path: "/projects/:projectId/modules/architecture/baselines", element: createElement(ArchitectureListRedirect, { tab: "baselines" }) },
    { path: "/projects/:projectId/modules/architecture/baselines/:baselineId", element: createElement(BaselineDetailPage) },
    { path: "/projects/:projectId/modules/architecture/sharing", element: createElement(ProjectSharingPage) },
  ],
  projectAdminSections: [
    {
      key: "architecture-element-types", label: "Element Types", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "project", projectId }, kind: "element" }),
    },
    {
      key: "architecture-connection-types", label: "Connection Types", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "project", projectId }, kind: "connection" }),
    },
    {
      key: "architecture-domains", label: "Domains", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "project", projectId }, kind: "domain" }),
    },
    {
      key: "architecture-symbols", label: "Symbols", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ projectId }) => createElement(SymbolLibraryPanel, { scope: { kind: "project", projectId } }),
    },
  ],
  orgAdminSections: [
    {
      key: "architecture-element-types", label: "Element Types", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "org", organizationId: orgId }, kind: "element" }),
    },
    {
      key: "architecture-connection-types", label: "Connection Types", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "org", organizationId: orgId }, kind: "connection" }),
    },
    {
      key: "architecture-domains", label: "Domains", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(ArchitectureTypesPanel, { scope: { kind: "org", organizationId: orgId }, kind: "domain" }),
    },
  ],
  orgResourceSections: [
    {
      key: "architecture-elements", label: "Architecture Elements and Collections",
      render: ({ orgId }) => createElement(OrgElementsPanel, { orgId }),
    },
    {
      key: "architecture-symbols", label: "Architecture Symbols", subComponent: "architecture_type",
      render: ({ orgId }) => createElement(SymbolLibraryPanel, { scope: { kind: "org", organizationId: orgId } }),
    },
  ],
};
