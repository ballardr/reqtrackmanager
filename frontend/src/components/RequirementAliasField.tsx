/**
 * Module: components/RequirementAliasField
 *
 * The "Additional components" field of the requirement create form: choose the further components and categories the
 * new requirement also sits in. Each gets a code of its own once the requirement is saved; nothing is written here,
 * the choice is returned through `onChange` for the form to send with the requirement.
 *
 * It renders nothing when the project's setting disallows new aliases, the project has no category besides the
 * requirement's own, or the read fails: a form never offers a field that would be refused. The record page's own
 * control for an existing requirement is `RequirementPlaces`.
 */
import { useId } from "react";

import { recordPlacementsApi, type PlacementPair, type RecordPlacementsApi } from "../api/placements";
import { requirementAliasesApi, type RequirementAliasesApi } from "../api/requirementAliases";
import { useStrings } from "../context/TerminologyContext";
import { treeWithout, useRequirementAliasSetup } from "../hooks/useRequirementAliasSetup";
import { FieldCaption } from "./FieldHelp";
import { PlacementPicker } from "./PlacementPicker";

/**
 * @param projectId The project the requirement is created in.
 * @param ownCategoryId The category chosen as the requirement's own place, which is left out of the choices.
 * @param value The further places chosen so far.
 * @param onChange Called with the new list.
 * @param api Injectable calls (stories pass a fake).
 * @param placementsApi Reads the project's tree (stories pass a fake).
 */
export function RequirementAliasField({
  projectId, ownCategoryId, value, onChange, api = requirementAliasesApi, placementsApi = recordPlacementsApi,
}: {
  projectId: string;
  ownCategoryId: string;
  value: PlacementPair[];
  onChange: (next: PlacementPair[]) => void;
  api?: RequirementAliasesApi;
  placementsApi?: RecordPlacementsApi;
}) {
  const strings = useStrings();
  const controlId = useId();
  const { settings, tree } = useRequirementAliasSetup(projectId, api, placementsApi);
  if (!settings || settings.mode !== "allowed" || !tree) return null;
  const choices = treeWithout(tree, [ownCategoryId]);
  if (choices.categories.length === 0) return null;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption htmlFor={controlId} label={strings.requirementAliases.label} help={strings.help.requirementAliases} />
      <PlacementPicker
        id={controlId} tree={choices} categoryOnly
        value={value.filter((place) => place.category_id !== ownCategoryId)}
        onChange={onChange}
      />
    </div>
  );
}
