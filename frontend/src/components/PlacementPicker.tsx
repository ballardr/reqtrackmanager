/**
 * Module: components/PlacementPicker
 *
 * The control that chooses where a record sits in the project's component/category tree: a collapsible tree (each
 * component with its categories beneath it, searchable), so a record can hold any number of places. Shared by the
 * create form's `ComponentField` and the record header's `RecordPlacements`, so the two cannot drift.
 *
 * It renders nothing while the project has no components, since there is nothing to choose.
 */
import { type PlacementPair, type PlacementTree } from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { placeNodeId, placementNodes, placesOfNodeIds } from "./placementTree";
import { TreeSelect } from "./TreeSelect";

/**
 * @param tree The project's components and categories.
 * @param value The places chosen so far.
 * @param onChange Called with the new list (a component alone and the same component with a category are different places).
 * @param id `id` of the trigger, so a caption can point at it.
 */
export function PlacementPicker({
  tree, value, onChange, id,
}: { tree: PlacementTree; value: PlacementPair[]; onChange: (next: PlacementPair[]) => void; id?: string }) {
  const strings = useStrings();
  if (tree.components.length === 0) return null;
  return (
    <TreeSelect
      id={id}
      triggerLabel={strings.placements.pickerLabel}
      emptyLabel={strings.placements.choose}
      nodes={placementNodes(tree)}
      selectedIds={value.map(placeNodeId)}
      onChange={(ids) => onChange(placesOfNodeIds(ids, tree))}
      searchable
    />
  );
}
