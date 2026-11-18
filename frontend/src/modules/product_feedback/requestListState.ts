/**
 * Module: modules/product_feedback/requestListState
 *
 * The state both request lists share, so the project list and the organisation inbox cannot drift: the filters (kept
 * in the URL), the client-side match, the filters' server parameters, the sort and the demand text. The filter fields
 * are `RequestFilterFields` and the table columns `requestColumns`.
 *
 * - **Status.** One dropdown: "Open statuses" (New, Under review, Accepted; the default), "All statuses" or a single
 *   status. It is held as the URL's `status` (a single status) and `open=1|0` (open statuses, or all); a link that
 *   names a status or `open=0` starts on that choice, so a link never lands on an empty list.
 * - **Pain Points.** Where Pain Points are on for the project (`painPointsAvailable`), an optional Pain Points column
 *   (a count, sortable) and a filter, `pain_points=none|some` (requests addressing none, or at least one), which is
 *   also sent to the server so Export narrows the same way. Where they are off, neither is offered and a stale
 *   `pain_points` in the link is ignored.
 * - **Criteria not rated.** `missing=<axis key>` keeps requests with no level on that criterion, and `missing=any` those not
 *   rated on every criterion (any one missing); no value is no filter.
 * - **Unscored filter.** A request is unscored when the primary model has no score for it (a manual axis it needs has
 *   no level). The list holds every row and filters here, so the count beside the filter stays right whatever is
 *   chosen; the same filter goes to the server (`filterParams`) so Export and the grid narrow identically.
 * - **Columns.** The optional columns (status, demand, owner and a score column per scoring model) are chosen with the
 *   shared `ColumnChooser`, kept per person (`useColumnChoice`) and per list. Demand and owner start hidden; the status
 *   and the scheme's enabled models start shown. Title and code are always on.
 * - **Models.** Scores are derived on every read, so the list shows a column per ticked model. The first ticked is the
 *   primary: it drives the Unscored filter and the Score sort. The server is asked for exactly the ticked models once
 *   the person has chosen, and for its default (the scheme's enabled models) until then.
 * - **Demand** is shown beside the score and never mixed into it.
 */
import { useMemo } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { useColumnChoice } from "../../hooks/useColumnChoice";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { isDerivedAxis } from "./requestLevels";
import { REQUEST_OPEN_STATUSES, REQUEST_STATUS_LABEL } from "./types";
import type { EnhancementRequest, RequestStatus } from "./types";

const STATUSES = Object.keys(REQUEST_STATUS_LABEL) as RequestStatus[];
const SCORED_FILTERS = ["unscored", "scored"] as const;
/** The "Criteria not rated" filter value meaning any criterion, as the server's `missing_axis` takes it. */
export const ANY_CRITERION = "any";
/** The Status dropdown's two non-status choices. */
export type StatusChoice = RequestStatus | "open" | "all";
export const REQUEST_SORT_KEYS = ["code", "title", "status", "owner", "demand", "score", "created", "updated", "pain_points"] as const;
const PAIN_POINT_FILTERS = ["none", "some"] as const;

/** The models a list shows until the person chooses: the scheme's enabled models, else its default. */
export function defaultModels(scheme: ScoringScheme | null): string[] {
  if (!scheme) return [];
  return scheme.enabled_model_keys?.length ? scheme.enabled_model_keys : [scheme.default_model_key];
}

/** The id of a model's score column in the column chooser. */
export const scoreColumnId = (modelKey: string) => `score:${modelKey}`;

/**
 * The list's filters, held in the URL so the list comes back as it was left after a visit to a record, and its column
 * choice (per person).
 *
 * @param scheme The scoring scheme in effect (its models are the score columns on offer).
 * @param list Names the list for the remembered column choice (`project` or `inbox`).
 * @param withDemand True on the project tier, where a request has requesters and so a Demand column.
 * @param painPointsAvailable True where Pain Points are on for the project (the column and filter are offered).
 */
export function useRequestListFilters(
  scheme: ScoringScheme | null, list: "project" | "inbox", withDemand: boolean, painPointsAvailable = false,
) {
  const initial = useInitialSearchParams();
  const [search, setSearch] = useUrlText("q");
  const [status, setStatus] = useUrlChoice("status", STATUSES);
  const [scored, setScored] = useUrlChoice("scored", SCORED_FILTERS);
  const [painPointsChoice, setPainPoints] = useUrlChoice("pain_points", PAIN_POINT_FILTERS);
  const painPoints = painPointsAvailable ? painPointsChoice : "";
  const [missingAxis, setMissingAxis] = useUrlText("missing");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const [openOnly, setOpenOnly] = useOpenOnly(initial, STATUSES);
  const [sort, setSort] = useUrlSort<string>(REQUEST_SORT_KEYS);
  const statusChoice: StatusChoice = status || (openOnly ? "open" : "all");
  /** Picks a Status dropdown entry: a single status turns the open-statuses default off, as it would hide it. */
  const setStatusChoice = (choice: StatusChoice) => {
    setStatus(choice === "open" || choice === "all" ? "" : choice);
    setOpenOnly(choice === "open");
  };
  const columnIds = useMemo(
    () => [
      "status", ...(withDemand ? ["demand"] : []), ...(painPointsAvailable ? ["pain_points"] : []), "owner", "created", "updated",
      ...(scheme?.models.map((m) => scoreColumnId(m.key)) ?? []),
    ],
    [scheme, withDemand, painPointsAvailable],
  );
  const columnDefaults = useMemo(() => ["status", ...defaultModels(scheme).map(scoreColumnId)], [scheme]);
  const columns = useColumnChoice(`product_feedback_requests_${list}`, columnIds, columnDefaults);
  const models = (scheme?.models ?? []).map((m) => m.key).filter((key) => columns.visible.includes(scoreColumnId(key)));
  // Until the person chooses, the server's own default applies (no parameter), so a first load never repeats.
  const requestedModels = columns.isDefault ? [] : models;
  const primary = models[0] ?? null;

  const isUnscored = (r: EnhancementRequest) => primary !== null && !r.scores[primary];
  const missesAxis = (r: EnhancementRequest, axisKey: string) => {
    // `any` is "not rated on every criterion": a manual criterion with no level (a derived one is never missing).
    if (axisKey === ANY_CRITERION) return (scheme?.axes ?? []).some((a) => !isDerivedAxis(a) && !r.levels[a.key]);
    const axis = scheme?.axes.find((a) => a.key === axisKey);
    return axis !== undefined && !isDerivedAxis(axis) && !r.levels[axisKey];
  };

  /** Whether `r` passes every filter except the ones named in `skip` (so a count can ignore its own filter). */
  function matches(r: EnhancementRequest, skip: "scored" | "open" | null = null): boolean {
    if (skip !== "open" && openOnly && !REQUEST_OPEN_STATUSES.includes(r.status)) return false;
    if (status && r.status !== status) return false;
    if (skip !== "scored" && scored && isUnscored(r) !== (scored === "unscored")) return false;
    if (missingAxis && !missesAxis(r, missingAxis)) return false;
    if (painPoints && (r.pain_point_count > 0) !== (painPoints === "some")) return false;
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
    if (painPoints) params.set("pain_points", painPoints);
    if (requestedModels.length > 0) params.set("scoring_model", requestedModels.join(","));
    return params;
  }

  return {
    search, setSearch, status, statusChoice, setStatusChoice, scored, setScored, painPoints, setPainPoints, painPointsAvailable, missingAxis, setMissingAxis,
    includeArchived, setIncludeArchived, openOnly, sort, setSort, models, requestedModels, primary, columns, columnIds,
    isUnscored, matches, filterParams,
  };
}

export type RequestListFilters = ReturnType<typeof useRequestListFilters>;

/** The score a request sorts by: the primary model's normalised score; a request with no value (unscored, no owner) sorts last either way. */
export function sortRequests(rows: EnhancementRequest[], filters: RequestListFilters): EnhancementRequest[] {
  const { sort, primary } = filters;
  if (!sort) return rows;
  const value = (r: EnhancementRequest): number | string | null => {
    if (sort.key === "code") return r.unique_code;
    if (sort.key === "title") return r.title;
    if (sort.key === "status") return REQUEST_STATUS_LABEL[r.status];
    if (sort.key === "owner") return r.owner?.label ?? null;
    if (sort.key === "demand") return r.weighted_demand;
    if (sort.key === "created") return Date.parse(r.created_at);
    if (sort.key === "updated") return Date.parse(r.updated_at);
    if (sort.key === "pain_points") return r.pain_point_count;
    return primary ? r.scores[primary]?.normalised ?? null : null;
  };
  return [...rows].sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    const order = typeof x === "number" && typeof y === "number"
      ? x - y
      : String(x).localeCompare(String(y), undefined, { sensitivity: "base", numeric: true });
    return sort.direction === "asc" ? order : -order;
  });
}

/** `3 requesters · 7.5` (the weighted figure is dropped when it equals the count). */
export function demandText(r: Pick<EnhancementRequest, "requester_count" | "weighted_demand">): string {
  const weighted = Number.isInteger(r.weighted_demand) ? String(r.weighted_demand) : r.weighted_demand.toFixed(1);
  const people = `${r.requester_count} ${r.requester_count === 1 ? "requester" : "requesters"}`;
  return r.requester_count === r.weighted_demand ? people : `${people} · ${weighted}`;
}
