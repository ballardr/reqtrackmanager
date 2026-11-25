/**
 * Module: components/PrimaryPlaceField
 *
 * The form field that chooses the one component and category a requirement belongs to, as a single choice from the
 * project's tree (`TreeSelectField` in one-choice mode over `placementNodes`): each component is a heading with its
 * categories beneath it, searchable, and the category chosen is the pair. Shared by the requirement create form and
 * the change request form that proposes a requirement.
 *
 * A requirement's pair is its identity (it forms the code), so it is chosen as one unit and a category of another
 * component cannot be selected. The further places a requirement may sit in use `PlacementPicker`, the same tree in
 * several-choice mode.
 */
import type { PlacementPair, PlacementTree } from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { categoryNodeId, placementNodes, placesOfNodeIds } from "./placementTree";
import { TreeSelectField } from "./TreeSelectField";

/**
 * @param tree The project's components and categories.
 * @param categoryId The chosen category, or empty.
 * @param onChange Called with the chosen category and the component it sits under.
 * @param help The field's help text (`strings.help`).
 */
export function PrimaryPlaceField({
  tree, categoryId, onChange, help,
}: {
  tree: PlacementTree;
  categoryId: string;
  onChange: (place: PlacementPair) => void;
  help: string;
}) {
  const strings = useStrings();
  const text = strings.placements;
  const hasCategory = tree.categories.length > 0;
  return (
    <TreeSelectField
      label={text.primaryLabel} help={help} required single searchable
      emptyLabel={hasCategory ? text.primaryChoose : text.primaryNoCategories}
      nodes={placementNodes(tree, true)}
      value={categoryId ? [categoryNodeId(categoryId)] : []}
      onChange={(ids) => {
        const place = placesOfNodeIds(ids, tree)[0];
        if (place?.category_id) onChange(place);
      }}
    />
  );
}
