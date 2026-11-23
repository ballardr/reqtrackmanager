/**
 * Module: components/SortField
 *
 * The **Sort by** and **Order** controls of a record list's filter panel, and the reset that returns to the default
 * order (docs/ux-style-guide.md, "Pattern: list sort"). One component for every list, so a person finds the sort in the
 * same place with the same words, and a record they have just created or changed can be put at the top by creation or
 * modification time.
 *
 * Responsibilities:
 * - Draw the two selects over a `ListSortState` (`useListSort`), the same state the table's column headers use.
 * - Offer a choice for each sortable column of the table plus **Created** and **Modified** (`sortChoices`, `sortChoices.ts`).
 * - Describe every choice in the caption's `(?)` tooltip, one line each, so a person can compare before choosing.
 * - Show **Reset to default order** only while a sort is chosen; there is nothing to reset otherwise.
 *
 * Dependencies: `FilterSelect`, `useListSort`, `strings.sort`.
 */
import { useStrings } from "../context/TerminologyContext";
import type { ListSortState } from "../hooks/useListSort";
import { FilterSelect } from "./FilterSelect";
import { sortChoices, type SortableColumn, type SortChoice } from "./sortChoices";
import type { SortDirection } from "./sortState";

/**
 * @param list The list's sort state (`useListSort`).
 * @param columns The table's columns, for the choices.
 * @param codeKey The key of the code column (`code`, `unique_code`), which the help describes as numeric.
 * @param titleKey The key of the title or name column, which the help describes as alphabetical.
 * @param fixedOrder The keys of a choice that has one order only (the requirements' component and category order), for which
 *   the Order select is unavailable.
 * @param describe The help line of a choice of the list's own that the common keys do not describe (keyed by the choice).
 */
export function SortField({
  list,
  columns,
  codeKey = "code",
  titleKey = "title",
  fixedOrder = [],
  describe = {},
}: {
  list: ListSortState;
  columns: readonly SortableColumn[];
  codeKey?: string;
  titleKey?: string;
  fixedOrder?: readonly string[];
  describe?: Record<string, string>;
}) {
  const strings = useStrings();
  const text = strings.sort;
  const offered = sortChoices(columns, text.created, text.modified);
  // A sort in force that the table no longer shows a column for (a hidden score column) stays visible, by its key.
  const choices = offered.some((c) => c.value === list.sort.key) ? offered : [...offered, { value: list.sort.key, label: list.sort.key }];
  const labelOf = (choice: SortChoice) => choice.label;
  const lineFor = (choice: SortChoice): string => {
    const label = labelOf(choice);
    if (describe[choice.value]) return describe[choice.value];
    if (choice.value === codeKey) return text.code.replace("{label}", label);
    if (choice.value === titleKey) return text.text.replace("{label}", label);
    if (choice.value === "created") return text.createdHelp.replace("{label}", label);
    if (choice.value === "modified") return text.modifiedHelp.replace("{label}", label);
    return text.column.replace("{label}", label);
  };
  const codeChoice = choices.find((c) => c.value === codeKey);
  const help = [
    text.sortByIntro,
    ...choices.map(lineFor),
    ...(codeChoice ? [text.defaultNote.replace("{label}", codeChoice.label)] : []),
  ].join("\n");
  return (
    <>
      <FilterSelect
        label={text.sortBy}
        help={help}
        value={list.sort.key}
        onChange={(key) => list.set({ key, direction: list.sort.direction })}
        options={choices}
      />
      <FilterSelect<SortDirection>
        label={text.order}
        help={text.orderHelp}
        disabled={fixedOrder.includes(list.sort.key)}
        value={list.sort.direction}
        onChange={(direction) => list.set({ key: list.sort.key, direction })}
        options={[
          { value: "asc", label: text.ascending },
          { value: "desc", label: text.descending },
        ]}
      />
      {!list.isDefault && (
        <button type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }} onClick={list.reset}>
          {text.reset}
        </button>
      )}
    </>
  );
}
