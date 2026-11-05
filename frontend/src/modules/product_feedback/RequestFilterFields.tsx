/**
 * Module: modules/product_feedback/RequestFilterFields
 *
 * The filter fields the project list and the organisation inbox both show in their `FilterPanel` (a page adds its own
 * after them: project scope, tags). State and matching are `useRequestListFilters`.
 */
import type { ScoringScheme } from "../../api/scoring";
import { FilterCheckbox, FilterField } from "../../components/FilterPanel";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { isDerivedAxis } from "./requestLevels";
import type { RequestListFilters } from "./requestListState";
import { REQUEST_STATUS_LABEL } from "./types";
import type { EnhancementRequest, RequestStatus } from "./types";

const STATUSES = Object.keys(REQUEST_STATUS_LABEL) as RequestStatus[];

/**
 *
 * @param filters The state from `useRequestListFilters`.
 * @param scheme The scoring scheme in effect (the scoring fields are left out without it).
 * @param requests Every request held, for the unscored count.
 */
export function RequestFilterFields({
  filters, scheme, requests,
}: { filters: RequestListFilters; scheme: ScoringScheme | null; requests: EnhancementRequest[] }) {
  const unscoredCount = requests.filter((r) => filters.matches(r, "scored") && filters.isUnscored(r)).length;
  const manualAxes = (scheme?.axes ?? []).filter((a) => !isDerivedAxis(a));
  return (
    <>
      <FilterField label="Status">
        <select className="input" value={filters.status} onChange={(e) => filters.setStatus(e.target.value as RequestStatus | "")}>
          <option value="">All statuses</option>
          {STATUSES.map((value) => <option key={value} value={value}>{REQUEST_STATUS_LABEL[value]}</option>)}
        </select>
      </FilterField>
      {scheme && (
        <>
          <FilterField label="Scoring">
            <select
              className="input" value={filters.scored}
              onChange={(e) => filters.setScored(e.target.value as "" | "unscored" | "scored")}
            >
              <option value="">Any scoring</option>
              <option value="unscored">{`Unscored (${unscoredCount})`}</option>
              <option value="scored">Scored</option>
            </select>
          </FilterField>
          <FilterField label="Missing a level for">
            <select className="input" value={filters.missingAxis} onChange={(e) => filters.setMissingAxis(e.target.value)}>
              <option value="">Any criterion</option>
              {manualAxes.map((axis) => <option key={axis.key} value={axis.key}>{axis.label}</option>)}
            </select>
          </FilterField>
          <FilterField label="Scores shown">
            <MultiSelectDropdown
              triggerLabel="Scoring models shown" emptyLabel="Default models"
              options={scheme.models.map((m) => ({
                value: m.key, label: m.label, optionLabel: `Show ${m.label}`, checked: filters.models.includes(m.key),
                onToggle: () => filters.setChosenModels(
                  filters.models.includes(m.key) ? filters.models.filter((k) => k !== m.key) : [...filters.models, m.key],
                ),
              }))}
            />
          </FilterField>
        </>
      )}
      <FilterCheckbox label="Open only" checked={filters.openOnly} onChange={filters.setOpenOnly} />
      <FilterCheckbox label="Show archived" checked={filters.includeArchived} onChange={filters.setIncludeArchived} />
    </>
  );
}
