/**
 * Module: components/ProjectScopeFilter
 *
 * The scope filter of a list's `FilterPanel`: "This project", "+ parents", "+ children" or both,
 * for a project that has a parent or child the viewer can open. The list page owns the state
 * (`useProjectScope`) and sends it to the server.
 *
 * Renders nothing for a project with no openable relatives, so a flat project sees no new
 * control. When the list is widened it states so beside the select, which is also what tells a
 * reader that the list's counts cover more than this project.
 */
import type { ProjectScopeState } from "../hooks/useProjectScope";
import { useStrings } from "../context/TerminologyContext";
import { FilterField } from "./FilterPanel";
import { ProjectScopeSelect } from "./ProjectScopeSelect";

/**
 * @param scope The list's scope state (`useProjectScope`).
 */
export function ProjectScopeFilter({ scope }: { scope: ProjectScopeState }) {
  const strings = useStrings();
  if (scope.available.length < 2) return null;
  return (
    <FilterField label={strings.projectScope.label}>
      <ProjectScopeSelect scope={scope} />
      {scope.widened && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.projectScope.widenedHint}</span>}
    </FilterField>
  );
}
