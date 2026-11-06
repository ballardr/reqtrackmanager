/**
 * Module: modules/product_feedback/RequestFilterFields
 *
 * The filter fields the project list and the organisation inbox both show in their `FilterPanel` (a page adds its own
 * after them: project scope, tags). State and matching are `useRequestListFilters`.
 */
import type { ScoringScheme } from "../../api/scoring";
import { FilterCheckbox, FilterField } from "../../components/FilterPanel";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { isDerivedAxis } from "./requestLevels";
import { ANY_CRITERION, type RequestListFilters, type StatusChoice } from "./requestListState";
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
      <FilterField label="Status" help={PRODUCT_FEEDBACK_HELP.requestStatusFilter}>
        <select className="input" aria-label="Status" value={filters.statusChoice} onChange={(e) => filters.setStatusChoice(e.target.value as StatusChoice)}>
          <option value="open">Open statuses</option>
          <option value="all">All statuses</option>
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
          <FilterField label="Criteria not rated">
            <select className="input" value={filters.missingAxis} onChange={(e) => filters.setMissingAxis(e.target.value)}>
              <option value="">No filter</option>
              <option value={ANY_CRITERION}>Any criterion</option>
              {manualAxes.map((axis) => <option key={axis.key} value={axis.key}>{axis.label}</option>)}
            </select>
          </FilterField>
        </>
      )}
      {filters.painPointsAvailable && (
        <FilterField label="Pain Points" help={PRODUCT_FEEDBACK_HELP.requestPainPointFilter}>
          <select
            className="input" aria-label="Pain Points" value={filters.painPoints}
            onChange={(e) => filters.setPainPoints(e.target.value as "" | "none" | "some")}
          >
            <option value="">Any</option>
            <option value="none">None linked</option>
            <option value="some">At least one linked</option>
          </select>
        </FilterField>
      )}
      <FilterCheckbox label="Show archived" checked={filters.includeArchived} onChange={filters.setIncludeArchived} />
    </>
  );
}
