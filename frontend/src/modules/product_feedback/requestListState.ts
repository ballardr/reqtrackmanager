/**
 * Module: modules/product_feedback/requestListState
 *
 * The state both request lists share, so the project list and the organisation inbox cannot drift: the filters (kept
 * in the URL), the client-side match, the filters' server parameters, the sort and the demand text. The filter fields
 * are `RequestFilterFields` and the table columns `requestColumns`.
 *
 * - **Unscored filter.** A request is unscored when the primary model has no score for it (a manual axis it needs has
 *   no level). The list holds every row and filters here, so the count beside the filter stays right whatever is
 *   chosen; the same filter goes to the server (`filterParams`) so Export and the grid narrow identically.
 * - **Models.** Scores are derived on every read, so the list shows a column per chosen model (default: the scheme's
 *   enabled ones). The first is the primary: it drives the Unscored filter and the Score sort.
 * - **Demand** is shown beside the score and never mixed into it.
 */
import type { ScoringScheme } from "../../api/scoring";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useUrlChoice, useUrlFlag, useUrlList, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { isDerivedAxis } from "./requestLevels";
import { REQUEST_OPEN_STATUSES, REQUEST_STATUS_LABEL } from "./types";
import type { EnhancementRequest, RequestStatus } from "./types";

const STATUSES = Object.keys(REQUEST_STATUS_LABEL) as RequestStatus[];
const SCORED_FILTERS = ["unscored", "scored"] as const;
export const REQUEST_SORT_KEYS = ["demand", "score"] as const;

/** The models the list shows: the viewer's choice, else the scheme's enabled models, else its default. */
export function shownModels(scheme: ScoringScheme | null, chosen: string[]): string[] {
  if (!scheme) return [];
  const known = new Set(scheme.models.map((m) => m.key));
  const picked = chosen.filter((key) => known.has(key));
  if (picked.length > 0) return picked;
  return scheme.enabled_model_keys?.length ? scheme.enabled_model_keys : [scheme.default_model_key];
}

/** The list's filters, held in the URL so the list comes back as it was left after a visit to a record. */
export function useRequestListFilters(scheme: ScoringScheme | null) {
  const initial = useInitialSearchParams();
  const [search, setSearch] = useUrlText("q");
  const [status, setStatus] = useUrlChoice("status", STATUSES);
  const [scored, setScored] = useUrlChoice("scored", SCORED_FILTERS);
  const [missingAxis, setMissingAxis] = useUrlText("missing");
  const [chosenModels, setChosenModels] = useUrlList("model");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [sort, setSort] = useUrlSort<string>(REQUEST_SORT_KEYS);
  const models = shownModels(scheme, chosenModels);
  const primary = models[0] ?? null;

  const isUnscored = (r: EnhancementRequest) => primary !== null && !r.scores[primary];
  const missesAxis = (r: EnhancementRequest, axisKey: string) => {
    const axis = scheme?.axes.find((a) => a.key === axisKey);
    return axis !== undefined && !isDerivedAxis(axis) && !r.levels[axisKey];
  };

  /** Whether `r` passes every filter except the ones named in `skip` (so a count can ignore its own filter). */
  function matches(r: EnhancementRequest, skip: "scored" | "open" | null = null): boolean {
    if (skip !== "open" && openOnly && !REQUEST_OPEN_STATUSES.includes(r.status)) return false;
    if (status && r.status !== status) return false;
    if (skip !== "scored" && scored && isUnscored(r) !== (scored === "unscored")) return false;
    if (missingAxis && !missesAxis(r, missingAxis)) return false;
    if (search && !`${r.unique_code} ${r.title} ${r.description}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }

  /** The filters by the names the server's list, Export and grid take. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    if (scored) params.set("scored", scored);
    if (missingAxis) params.set("missing_axis", missingAxis);
    if (chosenModels.length > 0) params.set("scoring_model", chosenModels.join(","));
    return params;
  }

  return {
    search, setSearch, status, setStatus, scored, setScored, missingAxis, setMissingAxis, chosenModels, setChosenModels,
    includeArchived, setIncludeArchived, openOnly, setOpenOnly, sort, setSort, models, primary,
    isUnscored, matches, filterParams,
  };
}

export type RequestListFilters = ReturnType<typeof useRequestListFilters>;

/** The score a request sorts by: the primary model's normalised score; unscored sorts last either way. */
export function sortRequests(rows: EnhancementRequest[], filters: RequestListFilters): EnhancementRequest[] {
  const { sort, primary } = filters;
  if (!sort) return rows;
  const value = (r: EnhancementRequest): number | null =>
    sort.key === "demand" ? r.weighted_demand : primary ? r.scores[primary]?.normalised ?? null : null;
  return [...rows].sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return sort.direction === "asc" ? x - y : y - x;
  });
}

/** `3 requesters · 7.5` (the weighted figure is dropped when it equals the count). */
export function demandText(r: Pick<EnhancementRequest, "requester_count" | "weighted_demand">): string {
  const weighted = Number.isInteger(r.weighted_demand) ? String(r.weighted_demand) : r.weighted_demand.toFixed(1);
  const people = `${r.requester_count} ${r.requester_count === 1 ? "requester" : "requesters"}`;
  return r.requester_count === r.weighted_demand ? people : `${people} · ${weighted}`;
}
