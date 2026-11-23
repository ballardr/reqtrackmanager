import { Link } from "react-router-dom";

import type { ProjectHierarchySummary } from "../api/types";
import { useStrings } from "../context/TerminologyContext";

const MAX_INLINE_CHILDREN = 3;

/**
 * "Child of: <link>" / "Parent of: <link>, <link>, ..." labels for a project list or tile row, shared by
 * `ProjectListPage`/`FavouritesPage` (a full `ProjectListItem`, which satisfies `ProjectHierarchySummary`) and
 * `ProjectOverviewPage` (which builds a `ProjectHierarchySummary` from its `Project` response and
 * `GET /{id}/children`).
 *
 * Both fields are filtered at the visibility boundary on the server (docs/decisions.md): `parent_project_name` is
 * present only when the caller can view that parent, and `children` lists only viewable children, with no count of
 * hidden ones. This component renders what it is given and filters nothing.
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
