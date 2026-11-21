/**
 * Module: components/RequirementListCode
 *
 * A requirement's code in a list row: its own code and, when the list is narrowed to components or categories the
 * requirement reaches only through an alias, that alias code after it in muted text, so the row names the place the
 * list is showing it under. A row matches a narrowing as the server reads it: in any chosen component or any chosen category.
 */
import type { Requirement } from "../api/types";
import { RecordCode } from "./RecordCode";

/**
 * @param requirement The listed requirement.
 * @param componentIds The components the list is narrowed to, or none.
 * @param categoryIds The categories the list is narrowed to, or none.
 */
export function RequirementListCode({
  requirement, componentIds, categoryIds,
}: { requirement: Requirement; componentIds: readonly string[]; categoryIds: readonly string[] }) {
  const narrowed = componentIds.length > 0 || categoryIds.length > 0;
  const inPlace = (component: string | null, category: string | null) =>
    (component !== null && componentIds.includes(component)) || (category !== null && categoryIds.includes(category));
  const ownMatches = inPlace(requirement.component_id, requirement.category_id);
  const alias = ownMatches || !narrowed
    ? undefined
    : (requirement.aliases ?? []).find((a) => !a.is_retired && inPlace(a.component_id, a.category_id));
  return (
    <>
      <RecordCode code={requirement.unique_code} ownerProjectCode={requirement.from_project_code} />
      {alias && <span className="text-muted"> · <RecordCode code={alias.unique_code} ownerProjectCode={requirement.from_project_code} /></span>}
    </>
  );
}
