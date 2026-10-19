/**
 * Module: components/ProjectScopeLabel
 *
 * The muted "From <project>" label a list row carries when it comes from a related project of a
 * widened list (`from_project_*` on the row). Renders nothing for a row of the viewed project,
 * so a single-project list is unchanged.
 */
import type { ProjectScopedRow } from "../api/projectScope";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param row The list row.
 */
export function ProjectScopeLabel({ row }: { row: ProjectScopedRow }) {
  const strings = useStrings();
  if (!row.from_project_id || !row.from_project_name) return null;
  return (
    <span className="text-muted" style={{ fontSize: "0.8rem" }}>
      {" "}
      {strings.projectScope.fromProject(row.from_project_name)}
    </span>
  );
}
