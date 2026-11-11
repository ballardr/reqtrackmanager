/**
 * Module: components/PlacementPicker
 *
 * The control that chooses where a record sits in the project's component/category tree: a filterable
 * multi-select listing every component and, under each, its categories, so a record can hold any number of
 * places. Shared by the create form's `ComponentField` and the record header's `RecordPlacements`, so the two
 * cannot drift.
 *
 * It renders nothing while the project has no components, since there is nothing to choose.
 */
import { samePlace, type PlacementPair, type PlacementTree } from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { MultiSelectDropdown, type MultiSelectOption } from "./MultiSelectDropdown";

/**
 * @param tree The project's components and categories.
 * @param value The places chosen so far.
 * @param onChange Called with the new list (a component alone and the same component with a category are different places).
 * @param id `id` of the trigger, so a caption can point at it.
 * @param disabled Disables the control while a save is in flight.
 */
export function PlacementPicker({
  tree, value, onChange, id, disabled = false,
}: { tree: PlacementTree; value: PlacementPair[]; onChange: (next: PlacementPair[]) => void; id?: string; disabled?: boolean }) {
  const strings = useStrings();
  if (tree.components.length === 0) return null;
  const options: MultiSelectOption[] = [];
  for (const component of tree.components) {
    const places: Array<{ pair: PlacementPair; label: string }> = [
      { pair: { component_id: component.id, category_id: null }, label: component.name },
      ...tree.categories
        .filter((category) => category.component_id === component.id)
        .map((category) => ({
          pair: { component_id: component.id, category_id: category.id },
          label: `${component.name} / ${category.name}`,
        })),
    ];
    for (const { pair, label } of places) {
      const checked = value.some((p) => samePlace(p, pair));
      options.push({
        value: `${pair.component_id}:${pair.category_id ?? ""}`,
        label,
        checked,
        optionLabel: label,
        onToggle: () => onChange(checked ? value.filter((p) => !samePlace(p, pair)) : [...value, pair]),
      });
    }
  }
  return (
    <MultiSelectDropdown
      id={id}
      triggerLabel={strings.placements.pickerLabel}
      emptyLabel={strings.placements.choose}
      options={options}
      filterable
      summaryLimit={2}
      disabled={disabled}
    />
  );
}
