/**
 * Module: components/HeaderSearch
 *
 * The global search box in the top bar, left of the notification bell, with a live dropdown of the
 * top results. It has no scope control: it searches the narrowest scope that matches the page the
 * viewer is on (`modules/searchScopes.ts`), and the Scope filter on the search page changes it. The
 * dropdown's footer names the place being searched in the scope's own label.
 *
 * Behaviour (docs/ux-style-guide.md, "Pattern: global search"):
 * - Submit by Enter or the visible Search button (`<form role="search">`); the page carries the query,
 *   scope and project in its URL (`/search?q=…`).
 * - `/` focuses the box (not while typing in a field); Esc closes the dropdown, then clears and blurs.
 * - The dropdown is an ARIA combobox: arrows move through results, Enter opens the highlighted one, Enter
 *   with nothing highlighted opens the page. Results are announced once per settled query, by count.
 * - Narrow viewports collapse the box to an icon button that opens it full-width.
 * - While on the search page the box shows that page's query and scope; it never overrides a scope the
 *   viewer changed on the page.
 *
 * The request behaviour (debounce, abort, keep-previous-results, cache) is `useLiveSearch`.
 */
import { Loader2, Search, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { searchApi, SEARCH_MIN_QUERY, queryTerms, type SearchApi, type SearchHit } from "../api/search";
import { useStrings } from "../context/TerminologyContext";
import { useLiveSearch } from "../hooks/useLiveSearch";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { getSearchHitPath } from "../modules/artefactPaths";
import {
  ALL_SCOPE, PROJECT_SCOPE, projectIdFromPath, scopeLabel, scopesForPath, type SearchScopeOption,
} from "../modules/searchScopes";
import { SearchHitSummary } from "./SearchHitSummary";
import { Tooltip } from "./Tooltip";

const MOBILE_BREAKPOINT_PX = 860;
const SEARCH_PATH = "/search";

/** Whether keyboard focus is somewhere text is typed, where `/` must stay a character. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** The state a search page URL carries into the box. */
function scopeFromUrl(params: URLSearchParams): { scope: string; projectId: string | null } {
  return { scope: params.get("scope") ?? ALL_SCOPE, projectId: params.get("project") };
}

/**
 * @param api Injectable calls (stories pass a fake).
 */
export function HeaderSearch({ api = searchApi }: { api?: SearchApi }) {
  const strings = useStrings();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isNarrow = useNarrowViewport(MOBILE_BREAKPOINT_PX);
  const onSearchPage = location.pathname === SEARCH_PATH;
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const labels = { project: strings.search.scopeThisProject, all: strings.search.scopeAllProjects };
  // The scopes that match where the viewer is (narrowest first); on the search page, the one the page is using.
  const matched = scopesForPath(location.pathname, labels);
  const pageScope = onSearchPage ? scopeFromUrl(searchParams) : null;
  const scope: SearchScopeOption = pageScope
    ? {
        value: pageScope.scope,
        label: scopeLabel(pageScope.scope, labels) ?? labels.all,
        narrowness: 0,
        projectId: pageScope.projectId ?? undefined,
      }
    : matched[0];

  const [text, setText] = useState(onSearchPage ? (searchParams.get("q") ?? "") : "");
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [active, setActive] = useState(-1);

  // The box shows the page's query while on the search page, and follows Back/Forward.
  const urlQuery = searchParams.get("q") ?? "";
  useResetOnChange([onSearchPage, urlQuery], () => {
    if (onSearchPage) setText(urlQuery);
  });

  const trimmed = text.trim();
  const request = open && trimmed.length >= SEARCH_MIN_QUERY
    ? { q: trimmed, scope: scope.value, project_id: scope.value === PROJECT_SCOPE ? (scope.projectId ?? projectIdFromPath(location.pathname)) : undefined }
    : null;
  const live = useLiveSearch(request, api);
  // The hits grouped by record type (groups in order of first appearance), so arrow keys move down the screen.
  const groups: { label: string; hits: SearchHit[] }[] = [];
  for (const hit of live.response?.hits ?? []) {
    let group = groups.find((g) => g.label === hit.type_label);
    if (!group) {
      group = { label: hit.type_label, hits: [] };
      groups.push(group);
    }
    group.hits.push(hit);
  }
  const hits = groups.flatMap((g) => g.hits);
  const optionCount = hits.length + 1; // the footer is the last option

  function close() {
    setOpen(false);
    setActive(-1);
  }

  // A new query starts from "nothing highlighted".
  useResetOnChange([trimmed], () => setActive(-1));

  // The count is announced once the query has settled (a polite live region), not per keystroke.
  const announce = live.settled && open && trimmed.length >= SEARCH_MIN_QUERY ? strings.search.resultsAnnouncement(hits.length) : "";

  // `/` focuses the search box from anywhere that is not a text field.
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      e.preventDefault();
      setExpanded(true);
      inputRef.current?.focus();
      setOpen(true);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Navigating away closes the dropdown (it lives outside the routed content).
  useResetOnChange([location.pathname], () => {
    close();
    setExpanded(false);
  });

  function destination(q: string): string {
    const params = new URLSearchParams({ q, scope: scope.value });
    if (scope.value === PROJECT_SCOPE) {
      const project = scope.projectId ?? projectIdFromPath(location.pathname);
      if (project) params.set("project", project);
    }
    return `${SEARCH_PATH}?${params.toString()}`;
  }

  function openPage() {
    if (trimmed.length < SEARCH_MIN_QUERY) return;
    close();
    // The scopes that matched where the search started travel with the navigation so the page can offer them.
    navigate(destination(trimmed), { state: { scopes: matched.map((m) => ({ value: m.value, label: m.label, projectId: m.projectId })) } });
  }

  function openHit(hit: SearchHit) {
    const path = getSearchHitPath(hit);
    if (!path) return;
    close();
    navigate(path);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (active >= 0 && active < hits.length) openHit(hits[active]);
    else openPage();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      if (open) close();
      else {
        setText("");
        inputRef.current?.blur();
        setExpanded(false);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (a + 1) % optionCount);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? optionCount - 1 : a - 1));
    }
  }

  const showPanel = open && trimmed.length > 0;
  const footerLabel = strings.search.seeAll(trimmed, scope.label);
  const optionId = (i: number) => `${listId}-opt-${i}`;
  const terms = queryTerms(trimmed);

  if (isNarrow && !expanded) {
    return (
      <Tooltip label={strings.search.openSearch}>
        <button
          type="button"
          className="btn"
          aria-label={strings.search.openSearch}
          onClick={() => {
            setExpanded(true);
            setOpen(true);
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        >
          <Search />
        </button>
      </Tooltip>
    );
  }

  return (
    <form
      role="search"
      className={`header-search${isNarrow ? " header-search--overlay" : ""}`}
      onSubmit={onSubmit}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) close();
      }}
    >
      <label className="sr-only" htmlFor={`${listId}-input`}>
        {strings.search.boxLabel}
      </label>
      <input
        id={`${listId}-input`}
        ref={inputRef}
        className="header-search__input"
        type="search"
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showPanel && active >= 0 ? optionId(active) : undefined}
        autoComplete="off"
        placeholder={strings.search.placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />
      {live.slow && <Loader2 className="header-search__spinner" size={14} aria-hidden="true" />}
      <button type="submit" className="btn" aria-label={strings.search.submit}>
        <Search />
      </button>
      {isNarrow && (
        <button type="button" className="btn" aria-label={strings.search.closeSearch} onClick={() => { close(); setExpanded(false); }}>
          <X />
        </button>
      )}
      <div className="sr-only" role="status" aria-live="polite">{announce}</div>
      {showPanel && (
        <div className="card stack search-dropdown" id={listId} role="listbox" aria-label={strings.search.dropdownLabel} aria-busy={live.pending}>
          {trimmed.length < SEARCH_MIN_QUERY ? (
            <p className="text-muted" style={{ margin: 0 }}>{strings.search.tooShort}</p>
          ) : (
            <>
              <div style={{ opacity: live.pending ? 0.55 : 1, transition: "opacity 120ms" }} className="stack">
                {live.error && <p style={{ margin: 0, color: "var(--color-danger)" }}>{live.error === "timeout" ? strings.search.timeout : live.error === "rate_limited" ? strings.search.rateLimited : strings.search.failed}</p>}
                {live.settled && hits.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.search.noResults}</p>}
                {groups.map((group) => (
                  <div key={group.label} role="group" aria-label={group.label} className="stack" style={{ gap: "0.1rem" }}>
                    <div className="text-muted" style={{ fontSize: "0.75rem", fontWeight: 600 }}>{group.label}</div>
                    {group.hits.map((hit) => {
                      const position = hits.indexOf(hit);
                      return (
                        <div
                          key={`${hit.type}:${hit.id}`}
                          id={optionId(position)}
                          role="option"
                          aria-selected={position === active}
                          className="search-option"
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => openHit(hit)}
                          onMouseEnter={() => setActive(position)}
                        >
                          <SearchHitSummary hit={hit} terms={terms} />
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
              <div
                id={optionId(hits.length)}
                role="option"
                aria-selected={active === hits.length}
                className="search-option search-option--footer"
                onMouseDown={(e) => e.preventDefault()}
                onClick={openPage}
                onMouseEnter={() => setActive(hits.length)}
              >
                {footerLabel}
              </div>
            </>
          )}
        </div>
      )}
    </form>
  );
}
