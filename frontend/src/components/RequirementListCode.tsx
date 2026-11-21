/**
 * Module: components/RequirementListCode
 *
 * A requirement's code in a list row: its own code and, when the list is narrowed to a component or category the
 * requirement reaches only through an alias, that alias code after it in muted text, so the row names the place the
 * list is showing it under.
 */
import type { Requirement } from "../api/types";
import { RecordCode } from "./RecordCode";

/**
 * @param requirement The listed requirement.
 * @param componentId The component the list is narrowed to, or empty.
 * @param categoryId The category the list is narrowed to, or empty.
 */
export function RequirementListCode({
  requirement, componentId, categoryId,
}: { requirement: Requirement; componentId: string; categoryId: string }) {
  const ownMatches = (!componentId || requirement.component_id === componentId) && (!categoryId || requirement.category_id === categoryId);
  const alias = ownMatches || (!componentId && !categoryId)
    ? undefined
    : (requirement.aliases ?? []).find(
      (a) => !a.is_retired && (!componentId || a.component_id === componentId) && (!categoryId || a.category_id === categoryId),
    );
  return (
    <>
      <RecordCode code={requirement.unique_code} ownerProjectCode={requirement.from_project_code} />
      {alias && <span className="text-muted"> · <RecordCode code={alias.unique_code} ownerProjectCode={requirement.from_project_code} /></span>}
    </>
  );
}
