/**
 * Module: components/QuickLinkField
 *
 * The "Link to" field of a create form: one search box that finds records to link the new
 * record to, so the relationship is made in the same trip as the record instead of through the
 * Links panel afterwards. Chosen records appear as rows with the relationship preselected and
 * changeable, and a remove control.
 *
 * Responsibilities:
 * - Search with the Links panel's finder (`api.candidates` / `api.options`), asked about the
 *   record being created through `DRAFT_ARTEFACT_ID`, so the server applies the same rules
 *   (visibility, enabled modules, link-type restrictions, the caller's link authority).
 * - Hand the chosen links to the form (`onChange`); the form creates them with
 *   `useCommitQuickLinks` once the record exists. Nothing is written here.
 * - Render nothing when the caller cannot link this type or no link type reaches another record
 *   type, so a form never offers a field that would be refused.
 *
 * Design decisions:
 * - Same-project records only. Linking to an ancestor or descendant project stays in the Links
 *   panel's dialog, which has the project selector this compact field deliberately omits.
 * - `preferredType` lists that type's records as soon as the box is focused and sorts its matches
 *   first (a pain point offers personas), but typing still searches every linkable type.
 *
 * Dependencies: `api/artefactLinks` (finder and `DRAFT_ARTEFACT_ID`), `components/linkOptions`.
 */
import { X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  artefactLinksApi, DRAFT_ARTEFACT_ID,
  type ArtefactLinkCandidate, type ArtefactLinkCandidates, type ArtefactLinksApi, type ArtefactLinkTypeOption,
  type CollectedLink,
} from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { ItemRow } from "./ItemRow";
import { defaultOptionKey, optionKey } from "./linkOptions";

const SEARCH_DEBOUNCE_MS = 250;
const MIN_QUERY = 2;

/** Whether two links point at the same record. */
function sameRecord(a: { other_type: string; other_id: string }, b: { other_type: string; other_id: string }): boolean {
  return a.other_type === b.other_type && a.other_id === b.other_id;
}

/**
 * A search box plus the list of records chosen to be linked to a record that does not exist yet.
 *
 * @param projectId The project the record is being created in.
 * @param artefactType The registered type of the record being created (`pain_point`, `risk`, ...).
 * @param value The links chosen so far; the form owns them.
 * @param onChange Called with the new list when a record is added, a relationship changed or a record removed.
 * @param preferredType A record type to offer first (and to list on focus), for example `persona`.
 * @param api Injectable calls (stories pass a fake); defaults to the live API.
 */
export function QuickLinkField({
  projectId, artefactType, value, onChange, preferredType, api = artefactLinksApi,
}: {
  projectId: string;
  artefactType: string;
  value: CollectedLink[];
  onChange: (links: CollectedLink[]) => void;
  preferredType?: string;
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const listboxId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  // `undefined` while loading, `[]` when the caller cannot link this type (the field then renders nothing).
  const [options, setOptions] = useState<ArtefactLinkTypeOption[] | undefined>(undefined);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  // Tagged with the search it answers so a slow reply for an earlier search is never shown for a later one.
  const [loaded, setLoaded] = useState<{ key: string; result: ArtefactLinkCandidates } | null>(null);

  useEffect(() => {
    let active = true;
    api.options(projectId, artefactType, DRAFT_ARTEFACT_ID)
      .then((result) => {
        if (active) setOptions(result);
      })
      .catch(() => {
        if (active) setOptions([]);
      });
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const trimmed = query.trim();
  const listPreferred = !!preferredType && trimmed.length === 0;
  const searchable = trimmed.length >= MIN_QUERY || listPreferred;
  const searchKey = `${listPreferred ? preferredType : ""}|${trimmed}`;
  useEffect(() => {
    if (!open || !searchable || !options || options.length === 0) return;
    let active = true;
    const timer = window.setTimeout(() => {
      api.candidates(projectId, artefactType, DRAFT_ARTEFACT_ID, {
        otherType: listPreferred ? preferredType : undefined, query: trimmed || undefined,
      })
        .then((result) => {
          if (active) setLoaded({ key: searchKey, result });
        })
        .catch(() => {
          if (active) setLoaded({ key: searchKey, result: { items: [], truncated: false } });
        });
    }, trimmed ? SEARCH_DEBOUNCE_MS : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, projectId, artefactType, open, searchable, options, listPreferred, preferredType, trimmed, searchKey]);

  const matches = useMemo(() => {
    const found = loaded?.key === searchKey ? loaded.result.items : [];
    const fresh = found.filter((c) => !value.some((v) => sameRecord(v, { other_type: c.type, other_id: c.id })));
    // Array.prototype.sort is stable, so the finder's label order is kept inside each group.
    return preferredType ? [...fresh].sort((a, b) => Number(b.type === preferredType) - Number(a.type === preferredType)) : fresh;
  }, [loaded, searchKey, value, preferredType]);

  if (!options || options.length === 0) return null;

  const showList = open && searchable;
  const waiting = showList && loaded?.key !== searchKey;

  function add(candidate: ArtefactLinkCandidate) {
    const chosen = (options ?? []).find((o) => optionKey(o) === defaultOptionKey(options ?? [], candidate.type));
    if (!chosen) return;
    onChange([...value, {
      link_type_id: chosen.link_type_id, direction: chosen.direction, other_type: candidate.type, other_id: candidate.id,
      phrase: chosen.phrase, otherLabel: candidate.label, otherTypeLabel: candidate.type_label,
    }]);
    setQuery("");
    setOpen(false);
    setHighlighted(-1);
  }

  function relationshipsFor(link: CollectedLink): ArtefactLinkTypeOption[] {
    return (options ?? []).filter((o) => o.other_types.some((t) => t.type === link.other_type));
  }

  function changeRelationship(link: CollectedLink, key: string) {
    const next = (options ?? []).find((o) => optionKey(o) === key);
    if (!next) return;
    onChange(value.map((v) => (v === link
      ? { ...v, link_type_id: next.link_type_id, direction: next.direction, phrase: next.phrase }
      : v)));
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else if (matches.length > 0) setHighlighted((i) => (i + 1) % matches.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (matches.length > 0) setHighlighted((i) => (i - 1 + matches.length) % matches.length);
    } else if (e.key === "Enter") {
      // Enter in a text field would otherwise submit the whole create form.
      if (showList && highlighted >= 0 && highlighted < matches.length) {
        e.preventDefault();
        add(matches[highlighted]);
      } else if (open) {
        e.preventDefault();
      }
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setHighlighted(-1);
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <label htmlFor={`${listboxId}-input`}>{strings.artefactLinks.quick.label}</label>
      <div ref={containerRef} style={{ position: "relative" }}>
        <input
          id={`${listboxId}-input`}
          className="input"
          role="combobox"
          aria-expanded={showList && matches.length > 0}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={showList && highlighted >= 0 ? `${listboxId}-option-${highlighted}` : undefined}
          placeholder={strings.artefactLinks.quick.placeholder}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlighted(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {showList && !waiting && (
          <div
            id={listboxId}
            role="listbox"
            aria-label={strings.artefactLinks.quick.listLabel}
            className="card stack"
            style={{
              position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, marginTop: "var(--space-1)",
              padding: "var(--space-1)", gap: "0.15rem", maxHeight: 260, overflowY: "auto",
            }}
          >
            {matches.length === 0 && <span className="text-muted" style={{ padding: "var(--space-2) var(--space-3)" }}>{strings.artefactLinks.quick.noMatches}</span>}
            {matches.map((c, i) => (
              <button
                key={`${c.type}:${c.id}`}
                id={`${listboxId}-option-${i}`}
                role="option"
                aria-selected={highlighted === i}
                type="button"
                className="btn"
                style={{
                  border: "none", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal",
                  background: highlighted === i ? "var(--color-surface-alt)" : undefined,
                }}
                onMouseEnter={() => setHighlighted(i)}
                onClick={() => add(c)}
              >
                {c.label} <span className="text-muted">({c.type_label})</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.artefactLinks.quick.hint}</span>
      {value.length > 0 && (
        <ul className="stack" style={{ gap: "var(--space-1)", listStyle: "none", margin: 0, padding: 0 }} aria-label={strings.artefactLinks.quick.chosenLabel}>
          {value.map((link) => {
            const choices = relationshipsFor(link);
            return (
              <ItemRow
                as="li"
                key={`${link.other_type}:${link.other_id}`}
                actions={(
                  <button
                    type="button"
                    className="btn btn-sm btn-icon"
                    title={strings.artefactLinks.quick.removeLabel(link.otherLabel)}
                    aria-label={strings.artefactLinks.quick.removeLabel(link.otherLabel)}
                    onClick={() => onChange(value.filter((v) => v !== link))}
                  >
                    <X />
                  </button>
                )}
              >
                {choices.length > 1 ? (
                  <select
                    className="input"
                    style={{ width: "auto", marginRight: "var(--space-3)" }}
                    aria-label={strings.artefactLinks.quick.relationshipLabel(link.otherLabel)}
                    value={`${link.link_type_id}:${link.direction}`}
                    onChange={(e) => changeRelationship(link, e.target.value)}
                  >
                    {choices.map((o) => <option key={optionKey(o)} value={optionKey(o)}>{o.phrase}</option>)}
                  </select>
                ) : (
                  <span className="text-muted" style={{ marginRight: "var(--space-3)" }}>{link.phrase}</span>
                )}
                <span>{link.otherLabel}</span> <span className="text-muted">({link.otherTypeLabel})</span>
              </ItemRow>
            );
          })}
        </ul>
      )}
    </div>
  );
}
