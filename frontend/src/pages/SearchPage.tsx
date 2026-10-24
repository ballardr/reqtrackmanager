/**
 * Module: pages/SearchPage
 *
 * The global search results page (`/search`). Everything the viewer sets (text, scope, filters, the
 * fields searched, sort) lives in the URL, so a search can be shared, bookmarked and reached with Back;
 * the API call itself is a POST so the text never reaches an access log.
 *
 * - Scope is the first filter: every scope that matched where the search started (they travel with the
 *   navigation from the header box) plus All projects; changing it re-runs the search.
 * - The Organisation filter appears only for a viewer who belongs to more than one organisation.
 * - "Search in" is a filterable multi-select over the fields the viewer's record types declare; the
 *   viewer's default (Preferences) applies until they choose here, and a choice here is this search only.
 * - Results are one `ItemRow` link per hit (`SearchHitSummary`), most relevant first, loaded 25 at a time
 *   up to the server's depth limit.
 * - Types the selected fields cannot search are named, never silently left out.
 *
 * A late response never overwrites a newer one (an `AbortController` per request), and the previous
 * results stay on screen, dimmed, while a new search runs.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import {
  isAbort, parseSearchState, queryTerms, searchApi, searchRequestFor, searchStateToParams, SEARCH_MAX_DEPTH, SEARCH_MIN_QUERY,
  type SearchApi, type SearchField, type SearchHit, type SearchPageState, type SearchProjectOption, type SearchResponse,
} from "../api/search";
import { ApiError } from "../api/client";
import { CheckboxField, DateField } from "../components/FormFields";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { ItemRow } from "../components/ItemRow";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { MultiSelectDropdown } from "../components/MultiSelectDropdown";
import { SearchFieldPicker } from "../components/SearchFieldPicker";
import { SearchHitSummary } from "../components/SearchHitSummary";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { useLatest } from "../hooks/useLatest";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useUiPreference } from "../hooks/useUiPreference";
import { getSearchHitPath } from "../modules/artefactPaths";
import { SEARCH_BUILT_IN_FIELDS, SEARCH_DEFAULT_FIELDS_PREFERENCE, SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE } from "../api/search";
import { ALL_SCOPE, PROJECT_SCOPE, scopeLabel } from "../modules/searchScopes";

const PAGE_SIZE = 25;
const QUERY_DEBOUNCE_MS = 400;

interface ScopeChoice {
  value: string;
  label: string;
  projectId?: string;
}

/** Add `item` to `list` or take it out. */
function toggled(list: string[], item: string): string[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

/**
 * @param api Injectable calls (stories pass a fake).
 */
export function SearchPage({ api = searchApi }: { api?: SearchApi }) {
  const strings = useStrings();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const state = parseSearchState(searchParams);
  const [queryText, setQueryText] = useState(state.q);
  const [storedDefault] = useUiPreference<string[]>(SEARCH_DEFAULT_FIELDS_PREFERENCE, []);
  const [preferredOrgRecords] = useUiPreference<boolean>(SEARCH_INCLUDE_ORG_RECORDS_PREFERENCE, true);
  const [fieldChoices, setFieldChoices] = useState<SearchField[]>([]);
  const [projects, setProjects] = useState<SearchProjectOption[]>([]);
  // The newest answered search (kept, dimmed, while the next runs) and the newest failure, each tagged with
  // the request it belongs to; whether a request is pending is derived from them, so no effect resets state.
  const [answer, setAnswer] = useState<{ key: string; response: SearchResponse; hits: SearchHit[] } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadMoreSignal = useRef<AbortController | null>(null);
  const labels = { project: strings.search.scopeThisProject, all: strings.search.scopeAllProjects };

  const terms = queryTerms(state.q, state.match);
  const ready = state.q.trim().length >= SEARCH_MIN_QUERY;
  const requestKey = JSON.stringify(searchRequestFor(state, PAGE_SIZE, 0));
  // Back from a result asks for the results that were loaded ("Show more") in one request.
  const limitFor = useLatest(useRestoredRowCount(PAGE_SIZE));

  function update(patch: Partial<SearchPageState>, options: { replace?: boolean } = { replace: true }) {
    setSearchParams(searchStateToParams({ ...state, ...patch }), options);
  }
  const latestUpdate = useLatest(update);

  // The URL's query leads; the field follows Back/Forward.
  useResetOnChange([state.q], () => setQueryText(state.q));
  // Typing in the page's own box updates the URL after a pause.
  useEffect(() => {
    if (queryText === state.q) return;
    const timer = setTimeout(() => latestUpdate.current({ q: queryText }), QUERY_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [queryText, state.q, latestUpdate]);

  // The choosable fields and projects are fetched once the first results are on screen, not alongside the
  // search: the field list authorises every project the viewer can open (as the search does) and the project
  // list resolves every role, so asking together would slow the results the person is waiting for.
  const firstResultsShown = answer !== null;
  useEffect(() => {
    if (!firstResultsShown) return;
    let active = true;
    api.fields().then((fields) => active && setFieldChoices(fields)).catch(() => undefined);
    api.projects().then((found) => active && setProjects(found)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [api, firstResultsShown]);

  // Run the search whenever anything but the page of results changes.
  useEffect(() => {
    loadMoreSignal.current?.abort();
    if (!ready) return;
    const controller = new AbortController();
    api
      .search({ ...JSON.parse(requestKey), limit: limitFor.current(0) }, controller.signal)
      .then((found) => {
        if (controller.signal.aborted) return;
        setAnswer({ key: requestKey, response: found, hits: found.hits });
        setFailure(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbort(err)) return;
        setFailure({ key: requestKey, message: err instanceof ApiError ? err.message : strings.search.failed });
      });
    return () => controller.abort();
  }, [requestKey, ready, api, strings.search.failed, limitFor]);

  const response = ready ? (answer?.response ?? null) : null;
  const hits = ready && answer ? answer.hits : [];
  const error = ready && failure && failure.key === requestKey ? failure.message : null;
  const pending = ready && !error && answer?.key !== requestKey;

  async function loadMore() {
    loadMoreSignal.current?.abort();
    const controller = new AbortController();
    loadMoreSignal.current = controller;
    setLoadingMore(true);
    try {
      const found = await api.search(searchRequestFor(state, PAGE_SIZE, hits.length), controller.signal);
      if (controller.signal.aborted) return;
      setAnswer((current) => {
        if (!current || current.key !== requestKey) return current;
        const seen = new Set(current.hits.map((h) => `${h.type}:${h.id}`));
        return { ...current, hits: [...current.hits, ...found.hits.filter((h) => !seen.has(`${h.type}:${h.id}`))] };
      });
    } catch (err) {
      if (!isAbort(err)) setFailure({ key: requestKey, message: err instanceof ApiError ? err.message : strings.search.failed });
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  // The scopes offered: those that matched where the search started (carried by the navigation), the one in use, and All projects.
  const carried = (location.state as { scopes?: ScopeChoice[] } | null)?.scopes ?? [];
  const scopeChoices: ScopeChoice[] = [];
  const addScope = (choice: ScopeChoice) => {
    const key = choice.value === PROJECT_SCOPE ? `${PROJECT_SCOPE}:${choice.projectId ?? ""}` : choice.value;
    if (!scopeChoices.some((c) => (c.value === PROJECT_SCOPE ? `${PROJECT_SCOPE}:${c.projectId ?? ""}` : c.value) === key)) scopeChoices.push(choice);
  };
  carried.forEach(addScope);
  const currentLabel = scopeLabel(state.scope, labels);
  if (currentLabel) addScope({ value: state.scope, label: currentLabel, projectId: state.projectId ?? undefined });
  addScope({ value: ALL_SCOPE, label: strings.search.scopeAllProjects });
  const scopeKey = (c: ScopeChoice) => (c.value === PROJECT_SCOPE ? `${PROJECT_SCOPE}:${c.projectId ?? ""}` : c.value);
  const selectedScopeKey = scopeKey({ value: state.scope, label: "", projectId: state.projectId ?? undefined });

  const organizations = response?.organizations ?? [];
  const typeCounts = response?.type_counts ?? [];
  const typeOptions = [
    ...typeCounts.map((c) => ({ value: c.type, label: strings.search.typeCount(c.label, c.count, c.capped) })),
    ...state.types.filter((t) => !typeCounts.some((c) => c.type === t)).map((t) => ({ value: t, label: t })),
  ];
  const statusOptions = [
    ...(response?.statuses ?? []).map((s) => ({ value: s.key, label: s.label })),
    ...state.statuses.filter((v) => !(response?.statuses ?? []).some((s) => s.key === v)).map((v) => ({ value: v, label: v })),
  ];
  const projectChoices = state.scope === PROJECT_SCOPE && state.projectId ? projects.filter((p) => p.id === state.projectId) : projects;

  const effectiveFields = state.fields ?? response?.fields_used ?? (storedDefault.length ? storedDefault : SEARCH_BUILT_IN_FIELDS);
  const total = response?.total ?? 0;
  const capped = response?.total_capped ?? false;
  const filterCount =
    state.types.length + state.statuses.length + state.projectIds.length + (state.organizationId ? 1 : 0) +
    (state.includeArchived ? 1 : 0) + (state.updatedFrom ? 1 : 0) + (state.updatedTo ? 1 : 0) + (state.orgRecords !== null ? 1 : 0);

  function clearFilters() {
    update({ types: [], statuses: [], projectIds: [], organizationId: null, includeArchived: false, orgRecords: null, updatedFrom: "", updatedTo: "" });
  }

  function chooseScope(key: string) {
    const choice = scopeChoices.find((c) => scopeKey(c) === key);
    if (!choice) return;
    update({ scope: choice.value, projectId: choice.value === PROJECT_SCOPE ? (choice.projectId ?? null) : null, projectIds: [] });
  }

  return (
    <div className="stack">
      <ListPageLayout
        ready={!ready || (answer !== null && !pending)}
        loadedRows={hits.length}
        title={ready ? strings.search.pageHeading(state.q.trim()) : strings.search.pageTitle}
        filter={
          <FilterPanel
            sectionKey="searchFilters"
            search={queryText}
            onSearchChange={setQueryText}
            searchPlaceholder={strings.search.placeholder}
            searchAriaLabel={strings.search.queryLabel}
          >
            <FilterField label={strings.search.scope}>
              <select className="input" aria-label={strings.search.scope} value={selectedScopeKey} onChange={(e) => chooseScope(e.target.value)}>
                {scopeChoices.map((c) => (
                  <option key={scopeKey(c)} value={scopeKey(c)}>
                    {c.label}
                  </option>
                ))}
              </select>
            </FilterField>
            {organizations.length > 1 && (
              <FilterField label={strings.search.organisation}>
                <select
                  className="input"
                  aria-label={strings.search.organisation}
                  value={state.organizationId ?? ""}
                  onChange={(e) => update({ organizationId: e.target.value || null })}
                >
                  <option value="">{strings.search.allOrganisations}</option>
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </FilterField>
            )}
            <FilterField label={strings.search.recordType}>
              <MultiSelectDropdown
                triggerLabel={strings.search.recordType}
                emptyLabel={strings.search.allTypes}
                summaryLimit={2}
                options={typeOptions.map((o) => ({
                  ...o, checked: state.types.includes(o.value), optionLabel: o.label, onToggle: () => update({ types: toggled(state.types, o.value) }),
                }))}
              />
            </FilterField>
            {state.scope !== PROJECT_SCOPE && projectChoices.length > 1 && (
              <FilterField label={strings.search.project}>
                <MultiSelectDropdown
                  triggerLabel={strings.search.project}
                  emptyLabel={strings.search.allProjects}
                  filterable
                  summaryLimit={2}
                  options={projectChoices.map((p) => ({
                    value: p.id,
                    label: p.name,
                    hint: p.parent_name ? strings.search.inProject(p.parent_name) : undefined,
                    checked: state.projectIds.includes(p.id),
                    optionLabel: p.name,
                    onToggle: () => update({ projectIds: toggled(state.projectIds, p.id) }),
                  }))}
                />
              </FilterField>
            )}
            {statusOptions.length > 0 && (
              <FilterField label={strings.search.status}>
                <MultiSelectDropdown
                  triggerLabel={strings.search.status}
                  emptyLabel={strings.search.anyStatus}
                  filterable
                  summaryLimit={2}
                  options={statusOptions.map((o) => ({
                    ...o, checked: state.statuses.includes(o.value), optionLabel: o.label, onToggle: () => update({ statuses: toggled(state.statuses, o.value) }),
                  }))}
                />
              </FilterField>
            )}
            {state.scope === PROJECT_SCOPE && (
              <CheckboxField
                help={strings.help.searchIncludeOrgRecords}
                label={strings.search.includeOrgRecords}
                checked={state.orgRecords ?? preferredOrgRecords}
                onChange={(v) => update({ orgRecords: v })}
              />
            )}
            <CheckboxField helpNotNeeded label={strings.search.includeArchived} checked={state.includeArchived} onChange={(v) => update({ includeArchived: v })} />
            <DateField helpNotNeeded label={strings.search.updatedFrom} value={state.updatedFrom} onChange={(v) => update({ updatedFrom: v })} />
            <DateField helpNotNeeded label={strings.search.updatedTo} value={state.updatedTo} onChange={(v) => update({ updatedTo: v })} />
            <FilterField label={strings.search.searchIn}>
              <SearchFieldPicker
                label={strings.search.fieldsFilterLabel}
                fields={fieldChoices}
                value={effectiveFields}
                onChange={(keys) => update({ fields: keys })}
              />
            </FilterField>
            <FilterField label={strings.search.match}>
              <select className="input" aria-label={strings.search.match} value={state.match} onChange={(e) => update({ match: e.target.value as SearchPageState["match"] })}>
                <option value="contains">{strings.search.matchContains}</option>
                <option value="phrase">{strings.search.matchPhrase}</option>
              </select>
            </FilterField>
            <FilterField label={strings.search.sort}>
              <select className="input" aria-label={strings.search.sort} value={state.sort} onChange={(e) => update({ sort: e.target.value as SearchPageState["sort"] })}>
                <option value="relevance">{strings.search.sortRelevance}</option>
                <option value="updated">{strings.search.sortUpdated}</option>
              </select>
            </FilterField>
            {filterCount > 0 && (
              <button type="button" className="btn" onClick={clearFilters}>
                {strings.search.clearFilters}
              </button>
            )}
          </FilterPanel>
        }
      >
        <div className="stack" aria-busy={pending}>
          {!ready && <p className="text-muted">{strings.search.startHint}</p>}
          {ready && !response && pending && <Spinner />}
          {ready && error && <p style={{ color: "var(--color-danger)" }} role="alert">{error}</p>}
          {ready && response && (
            <>
              <div className="row text-muted" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
                <span>{strings.search.total(total, capped)}</span>
                {response.not_searched.length > 0 && (
                  <span>{strings.search.notSearched(response.not_searched.map((n) => n.label).join(", "))}</span>
                )}
              </div>
              {response.projects_truncated && <p className="text-muted" style={{ margin: 0 }}>{strings.search.projectsTruncated}</p>}
              {hits.length === 0 && !pending && !error && (
                <div className="card stack">
                  <strong>{strings.search.emptyTitle}</strong>
                  <span className="text-muted">{strings.search.emptyHint}</span>
                </div>
              )}
              <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, opacity: pending ? 0.55 : 1, transition: "opacity 120ms" }}>
                {hits.map((hit) => {
                  const path = getSearchHitPath(hit);
                  const summary = <SearchHitSummary hit={hit} terms={terms} showSnippet />;
                  return (
                    <ItemRow as="li" key={`${hit.type}:${hit.id}`} className="card" align="start">
                      {path ? (
                        <Link to={path} style={{ color: "inherit", textDecoration: "none" }}>
                          {summary}
                        </Link>
                      ) : (
                        summary
                      )}
                    </ItemRow>
                  );
                })}
              </ul>
              <LoadMoreButton loaded={loadingMore ? total : hits.length} total={Math.min(total, SEARCH_MAX_DEPTH)} onClick={loadMore} />
              {capped && hits.length >= SEARCH_MAX_DEPTH && <p className="text-muted">{strings.search.depthLimit}</p>}
            </>
          )}
        </div>
      </ListPageLayout>
    </div>
  );
}
