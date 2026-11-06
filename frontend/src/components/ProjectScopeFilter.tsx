/**
 * Module: components/ProjectScopeFilter
 *
 * The scope filter of a list's `FilterPanel`: "This project", "+ parents", "+ children" or both,
 * for a project that has a parent or child the viewer can open. The list page owns the state
 * (`useProjectScope`) and sends it to the server.
 *
 * Renders nothing for a project with no openable relatives, so a flat project sees no new
 * control. What each option includes is the caption's `(?)` tooltip (listing every option), never a line under the
 * select: the chosen option names the scope, and the explanation is only needed the first time.
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
    <FilterField label={strings.projectScope.label} help={strings.projectScope.help}>
      <ProjectScopeSelect scope={scope} />
    </FilterField>
  );
}
