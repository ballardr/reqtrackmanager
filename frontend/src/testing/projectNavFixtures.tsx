/**
 * Module: testing/projectNavFixtures
 *
 * Shared fixture for the `ProjectNavSection` and `ProjectNavEditor` stories: a product-default
 * item list shaped like `Layout.tsx`'s, including one module-style entry (`<module>:<path>`).
 */
import { CheckSquare, FileText, LayoutDashboard, ListChecks, Settings } from "lucide-react";

import type { ProjectNavItem } from "../navigation/projectNav";

export const NAV_PROJECT_ID = "project-1";

/** Items in product-default order: Overview, Requirements, Actions, Reports, Admin, then a module entry. */
export function buildProjectNavItems(projectId: string = NAV_PROJECT_ID): ProjectNavItem[] {
  return [
    { key: "overview", to: `/projects/${projectId}`, exact: true, label: "Overview", icon: <LayoutDashboard size={16} /> },
    { key: "requirements", to: `/projects/${projectId}/requirements`, label: "Requirements", icon: <ListChecks size={16} /> },
    { key: "actions", to: `/projects/${projectId}/actions`, label: "Actions", icon: <CheckSquare size={16} /> },
    { key: "reports", to: `/projects/${projectId}/reports`, label: "Reports", icon: <FileText size={16} /> },
    { key: "admin", to: `/projects/${projectId}/admin`, label: "Project admin", icon: <Settings size={16} /> },
    { key: "decisions:/projects/project-1/decisions", to: `/projects/${projectId}/decisions`, label: "Decisions", icon: <FileText size={16} /> },
  ];
}
