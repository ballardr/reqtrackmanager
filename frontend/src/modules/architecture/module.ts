import { createElement } from "react";

import type { TierAModuleDefinition } from "../types";
import { ArchitectureTypesPanel } from "./ArchitectureTypesPanel";
import { ConnectionDetailPage } from "./ConnectionDetailPage";
import { CreateElementDialog } from "./CreateElementDialog";
import { ElementDetailPage } from "./ElementDetailPage";
import { OrgElementsPanel } from "./OrgElementsPanel";
import { ProjectConnectionsPage } from "./ProjectConnectionsPage";
import { ProjectElementsPage } from "./ProjectElementsPage";
import { ProjectSharingPage } from "./ProjectSharingPage";
import { SymbolLibraryPanel } from "./SymbolLibraryPanel";
import { ARCHITECTURE_STATUS_LABEL } from "./types";

/**
 * Module: modules/architecture/module
 *
 * The System Architecture module's frontend registration, the mirror of `backend/app/modules/architecture/
 * module.py`'s `MODULE_DEFINITION`. `frontend/src/modules/registry.ts` auto-discovers this file.
 *
 * `artefactPaths` / `artefactListPaths`: where an element, a connection, a diagram and their lists live, so links,
 * notifications and search hits resolve without core naming this module.
 * `artefactStatusLabels` / `artefactInactiveStatuses`: a retired record is greyed out in shared lists.
 *
 * `routes`: the Elements and Connections lists and their detail pages, and the Sharing page (collections). The diagram
 * screens are added with the diagram editor.
 * `linkedRecordCreators`: "Create new" element in another record's Links panel. A connection needs two elements, so it
 * is created from the Connections list or an element's page.
 * `projectAdminSections` / `orgAdminSections`: the two type vocabularies and the symbol library at each level, and the
 * organisation's own elements and collections, under one "System Architecture" group.
 */

/** The architecture settings share one expandable entry in the project and organisation admin menus. */
const ARCHITECTURE_ADMIN_GROUP = { key: "architecture", label: "System Architecture" };

export const moduleDefinition: TierAModuleDefinition = {
  key: "architecture",
  linkedRecordCreators: {
    architecture_element: { label: "Element", render: (props) => createElement(CreateElementDialog, props) },
  },
  artefactPaths: {
    architecture_element: (projectId, id) => `/projects/${projectId}/modules/architecture/elements/${id}`,
    architecture_connection: (projectId, id) => `/projects/${projectId}/modules/architecture/connections/${id}`,
    architecture_diagram: (projectId, id) => `/projects/${projectId}/modules/architecture/diagrams/${id}`,
  },
  artefactListPaths: {
    architecture_element: (projectId) => `/projects/${projectId}/modules/architecture/elements`,
    architecture_connection: (projectId) => `/projects/${projectId}/modules/architecture/connections`,
    architecture_diagram: (projectId) => `/projects/${projectId}/modules/architecture/diagrams`,
  },
  artefactStatusLabels: {
    architecture_element: ARCHITECTURE_STATUS_LABEL,
    architecture_connection: ARCHITECTURE_STATUS_LABEL,
    architecture_diagram: ARCHITECTURE_STATUS_LABEL,
  },
  artefactInactiveStatuses: {
    architecture_element: ["retired"],
    architecture_connection: ["retired"],
    architecture_diagram: ["retired"],
  },
  routes: [
    { path: "/projects/:projectId/modules/architecture/elements", element: createElement(ProjectElementsPage) },
    { path: "/projects/:projectId/modules/architecture/elements/:elementId", element: createElement(ElementDetailPage) },
    { path: "/projects/:projectId/modules/architecture/connections", element: createElement(ProjectConnectionsPage) },
    { path: "/projects/:projectId/modules/architecture/connections/:connectionId", element: createElement(ConnectionDetailPage) },
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
      key: "architecture-symbols", label: "Symbols", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(SymbolLibraryPanel, { scope: { kind: "org", organizationId: orgId } }),
    },
    {
      key: "architecture-elements", label: "Elements and Collections", group: ARCHITECTURE_ADMIN_GROUP,
      render: ({ orgId }) => createElement(OrgElementsPanel, { orgId }),
    },
  ],
};
