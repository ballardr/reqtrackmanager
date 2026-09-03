import { Link } from "react-router-dom";

import type { ProjectHierarchySummary } from "../api/types";
import { useStrings } from "../context/TerminologyContext";

const MAX_INLINE_CHILDREN = 3;

/**
 * "Child of: <link>" / "Parent of: <link>, <link>, ..." labels for a
 * project list/tile row — shared between `ProjectListPage`/`FavouritesPage`
 * (each passing a full `ProjectListItem`, which structurally satisfies
 * `ProjectHierarchySummary`) and `ProjectOverviewPage` (which has no
 * `ProjectListItem` of its own and builds a `ProjectHierarchySummary`
 * directly from its `Project` GET response plus a `GET /{id}/children`
 * call) rather than duplicated per page.
 *
 * Both fields are already visibility-boundary-filtered server-side
 * (`parent_project_name`/`children` — see docs/decisions.md):
 * `parent_project_name` is only ever present when the caller can view that
 * parent, and `children` only ever lists children the caller can view, with
 * no count of any hidden ones. This component just renders what it's
 * given — no client-side filtering needed or possible.
 */
export function ProjectHierarchyLabels({ project }: { project: ProjectHierarchySummary }) {
  const strings = useStrings();
  if (!project.parent_project_name && project.children.length === 0) return null;

  const visibleChildren = project.children.slice(0, MAX_INLINE_CHILDREN);
  const hasMoreChildren = project.children.length > MAX_INLINE_CHILDREN;

  return (
    <>
      {project.parent_project_name && (
        <div className="text-muted" style={{ fontSize: "0.8rem" }}>
          {strings.projects.childOf}{" "}
          <Link to={`/projects/${project.parent_project_id}`}>{project.parent_project_name}</Link>
        </div>
      )}
      {project.children.length > 0 && (
        <div className="text-muted" style={{ fontSize: "0.8rem" }}>
          {strings.projects.parentOf}{" "}
          {visibleChildren.map((c, i) => (
            <span key={c.id}>
              <Link to={`/projects/${c.id}`}>{c.name}</Link>
              {i < visibleChildren.length - 1 ? ", " : ""}
            </span>
          ))}
          {hasMoreChildren && (
            <>
              {" "}
              <Link to={`/projects/${project.id}`}>({strings.projects.viewAll})</Link>
            </>
          )}
        </div>
      )}
    </>
  );
}
