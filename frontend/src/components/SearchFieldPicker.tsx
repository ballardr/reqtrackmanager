/**
 * Module: components/SearchFieldPicker
 *
 * The "Search in" control: a filterable multi-select over the fields the global search can match
 * (`GET /search/fields`). Used by the search page (this search only) and by Preferences (the viewer's
 * default), so the two cannot drift.
 *
 * ID and Title are always searched and cannot be unchecked: a search that cannot match a record's
 * code or title would surprise people. A selected key that is no longer offered (a module switched
 * off, a renamed field) is shown as "no longer available" so it can be removed rather than failing the search.
 */
import { useStrings } from "../context/TerminologyContext";
import { COMMENTS_SEARCH_FIELD, LOCKED_SEARCH_FIELDS, type SearchField } from "../api/search";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

/** A hint listing the record types that carry a field is shown only when it is short. */
const MAX_HINT_TYPES = 3;

/**
 * @param label The visible caption of the control (also names the trigger).
 * @param fields The fields on offer.
 * @param value The selected field keys.
 * @param onChange Called with the new selection (locked fields always included).
 * @param id `id` of the trigger, for a field caption to point at.
 */
export function SearchFieldPicker({
  label, fields, value, onChange, id,
}: { label: string; fields: SearchField[]; value: string[]; onChange: (keys: string[]) => void; id?: string }) {
  const strings = useStrings();
  const offered = new Set(fields.map((f) => f.key));
  const selected = new Set([...LOCKED_SEARCH_FIELDS, ...value]);
  // Until the offered fields have loaded nothing can be called unavailable.
  const unavailable = fields.length === 0 ? [] : value.filter((key) => !offered.has(key));

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    // Keep the order the server offers them in, with locked fields first and anything unavailable last.
    const ordered = [...LOCKED_SEARCH_FIELDS, ...fields.map((f) => f.key).filter((k) => !LOCKED_SEARCH_FIELDS.includes(k)), ...unavailable];
    onChange(ordered.filter((k) => next.has(k)));
  }

  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <MultiSelectDropdown
        id={id}
        triggerLabel={label}
        filterable
        summaryLimit={strings.search.fieldPickerSummaryLimit}
        emptyLabel={strings.search.fieldsEmpty}
        options={fields.map((f) => ({
          value: f.key,
          label: f.label,
          checked: selected.has(f.key),
          disabled: LOCKED_SEARCH_FIELDS.includes(f.key),
          optionLabel: f.label,
          hint:
            f.key === COMMENTS_SEARCH_FIELD
              ? strings.search.slowFieldHint
              : f.types.length > 0 && f.types.length <= MAX_HINT_TYPES
                ? strings.search.fieldCarriedBy(f.types.join(", "))
                : undefined,
          onToggle: () => toggle(f.key),
        }))}
      />
      {unavailable.length > 0 && (
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>
          {strings.search.fieldsUnavailable(unavailable.join(", "))}{" "}
          <button type="button" className="btn btn-sm" onClick={() => onChange(value.filter((k) => offered.has(k)))}>
            {strings.common.remove}
          </button>
        </span>
      )}
    </div>
  );
}
