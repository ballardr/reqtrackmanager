/**
 * Module: components/ProjectScopeSelect
 *
 * The bare scope select: "This project", "+ parents", "+ children" or both. It is the control only, with
 * no label row or hint under it, so it fits where a filter panel's field would not: a page's title row
 * (the project overview, `compact`) as well as inside `ProjectScopeFilter`'s `FilterField`.
 *
 * Design decisions: the explanation lives in a `Tooltip` that opens on hover and on keyboard focus, and
 * the same text is always in the page for assistive technology (`aria-describedby`), because hover-only
 * text is invisible on touch. A widened scope is also drawn with an accent outline, so the state shows
 * without hovering. The visible text of the control is its chosen option, which names the scope.
 *
 * Renders nothing for a project with no openable relatives, so a flat project has no gap.
 */
import { useId } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { ProjectScope } from "../api/projectScope";
import type { ProjectScopeState } from "../hooks/useProjectScope";
import { Tooltip } from "./Tooltip";

/**
 * @param scope The page's scope state (`useProjectScope`).
 * @param compact For a title row: sized to its option, outlined while widened, with its explanation in a tooltip.
 *   Off (default) the select fills its container and the caller (a `FilterField`) shows the explanation itself.
 * @param coveredProjects When compact and widened, how many projects the page's counts cover; added to the explanation.
 */
export function ProjectScopeSelect({
  scope, compact = false, coveredProjects,
}: { scope: ProjectScopeState; compact?: boolean; coveredProjects?: number }) {
  const strings = useStrings();
  const descriptionId = useId();
  if (scope.available.length < 2) return null;
  const description = scope.widened
    ? [strings.projectScope.widenedHint, coveredProjects !== undefined && strings.projectScope.coversProjects(coveredProjects)]
        .filter(Boolean).join(" ")
    : strings.projectScope.selectHint;
  const select = (
    <select
      className={`input${compact ? " project-scope-select" : ""}${compact && scope.widened ? " project-scope-select-widened" : ""}`}
      aria-label={strings.projectScope.label}
      aria-describedby={compact ? descriptionId : undefined}
      value={scope.scope}
      onChange={(e) => scope.setScope(e.target.value as ProjectScope)}
    >
      {scope.available.map((option) => (
        <option key={option} value={option}>
          {strings.projectScope.options[option]}
        </option>
      ))}
    </select>
  );
  if (!compact) return select;
  return (
    <>
      <Tooltip label={description}>{select}</Tooltip>
      <span id={descriptionId} className="sr-only">{description}</span>
    </>
  );
}
