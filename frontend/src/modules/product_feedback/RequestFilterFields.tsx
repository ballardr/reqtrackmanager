/**
 * Module: modules/product_feedback/RequestFilterFields
 *
 * The filter fields the project list and the organisation inbox both show in their `FilterPanel` (a page adds its own
 * after them: project scope, tags). State and matching are `useRequestListFilters`.
 */
import type { ScoringScheme } from "../../api/scoring";
import { FilterCheckbox } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { isDerivedAxis } from "./requestLevels";
import { ANY_CRITERION, type RequestListFilters, type StatusChoice } from "./requestListState";
import { REQUEST_STATUS_LABEL } from "./types";
import type { EnhancementRequest, RequestStatus } from "./types";
import { useStrings } from "../../context/TerminologyContext";

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
  const strings = useStrings();
  const unscoredCount = requests.filter((r) => filters.matches(r, "scored") && filters.isUnscored(r)).length;
  const manualAxes = (scheme?.axes ?? []).filter((a) => !isDerivedAxis(a));
  return (
    <>
      <FilterSelect<StatusChoice>
        label={strings.filters.status}
        help={PRODUCT_FEEDBACK_HELP.requestStatusFilter}
        value={filters.statusChoice}
        onChange={filters.setStatusChoice}
        options={[
          { value: "open", label: "Open statuses" },
          { value: "all", label: "All statuses" },
          ...STATUSES.map((value) => ({ value, label: REQUEST_STATUS_LABEL[value] })),
        ]}
      />
      {scheme && (
        <>
          <FilterSelect
            label={strings.filters.scoring}
            value={filters.scored}
            onChange={filters.setScored}
            allLabel="Any scoring"
            options={[{ value: "unscored", label: `Unscored (${unscoredCount})` }, { value: "scored", label: "Scored" }]}
          />
          <FilterSelect
            label="Criteria not rated"
            value={filters.missingAxis}
            onChange={filters.setMissingAxis}
            allLabel="No filter"
            options={[{ value: ANY_CRITERION, label: "Any criterion" }, ...manualAxes.map((axis) => ({ value: axis.key, label: axis.label }))]}
          />
        </>
      )}
      {filters.painPointsAvailable && (
        <FilterSelect
          label="Pain Points"
          help={PRODUCT_FEEDBACK_HELP.requestPainPointFilter}
          value={filters.painPoints}
          onChange={filters.setPainPoints}
          allLabel="Any"
          options={[{ value: "none", label: "None linked" }, { value: "some", label: "At least one linked" }]}
        />
      )}
      <FilterCheckbox label="Show archived" checked={filters.includeArchived} onChange={filters.setIncludeArchived} />
    </>
  );
}
