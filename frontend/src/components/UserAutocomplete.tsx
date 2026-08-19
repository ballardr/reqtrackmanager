import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { api } from "../api/client";
import type { ExternalUserMatch, OrgUser, OrgUserSearchResult } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

type Option = { kind: "user"; user: OrgUser } | { kind: "external"; match: ExternalUserMatch };

/**
 * Type-to-filter picker over org users — replaces asking the caller to
 * paste a raw user id, which meant looking one up elsewhere first.
 *
 * Two modes:
 * - Default (no `organizationId`): matches by display name/email against
 *   whatever `users` this org/project screen already has loaded (no extra
 *   API call) — unchanged from the original behaviour.
 * - `organizationId` set: debounced server-side search
 *   (`orgs/{id}/users/search`), which can also surface a synthetic
 *   "external" result (an email not yet a member of this org, matching or
 *   not matching an existing account) when `Organization.
 *   external_user_policy` allows it. Selecting an external result calls
 *   `onSelectExternal` instead of `onSelect` — required in this mode.
 *   `projectId`, if also passed, lets the search reveal a match against an
 *   *existing* account elsewhere in the system to a caller who manages
 *   that specific project (not just org admins) — see the backend
 *   endpoint's own docstring for why that fact is gated at all.
 */
export function UserAutocomplete({
  users,
  onSelect,
  onSelectExternal,
  organizationId,
  projectId,
  placeholder,
}: {
  users: OrgUser[];
  onSelect: (userId: string) => void;
  onSelectExternal?: (email: string) => void;
  organizationId?: string;
  projectId?: string;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [serverMatches, setServerMatches] = useState<OrgUser[]>([]);
  const [external, setExternal] = useState<ExternalUserMatch | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const orgLabel = useOrgLabel();
  const listboxId = useId();

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const needle = query.trim().toLowerCase();

  // Debounced server-side search, only in organizationId mode.
  useEffect(() => {
    if (!organizationId || needle.length === 0) {
      setServerMatches([]);
      setExternal(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: needle });
        if (projectId) params.set("project_id", projectId);
        const result = await api.get<OrgUserSearchResult>(
          `/api/v1/orgs/${organizationId}/users/search?${params.toString()}`,
        );
        if (!cancelled) {
          setServerMatches(result.members);
          setExternal(result.external);
        }
      } catch {
        if (!cancelled) {
          setServerMatches([]);
          setExternal(null);
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [organizationId, projectId, needle]);

  const matches = organizationId
    ? serverMatches
    : needle.length === 0
      ? []
      : users
          .filter((u) => u.display_name.toLowerCase().includes(needle) || u.email.toLowerCase().includes(needle))
          .slice(0, 8);

  // Whether this instance is wired up to invite an external user at all
  // (vs. only ever adding an existing member) — drives the persistent hint,
  // shown before a query narrows things down to an actual external match.
  const inviteCapable = !!(organizationId && onSelectExternal);
  const canInvite = !!(external && onSelectExternal);
  const options: Option[] = [
    ...matches.map((user): Option => ({ kind: "user", user })),
    ...(canInvite ? [{ kind: "external", match: external! } as Option] : []),
  ];
  const showDropdown = open && options.length > 0;

  function pick(user: OrgUser) {
    onSelect(user.user_id);
    setQuery("");
    setOpen(false);
    setHighlightedIndex(-1);
  }

  function pickExternal(match: ExternalUserMatch) {
    onSelectExternal?.(match.email);
    setQuery("");
    setOpen(false);
    setExternal(null);
    setHighlightedIndex(-1);
  }

  function selectOption(option: Option) {
    if (option.kind === "user") pick(option.user);
    else pickExternal(option.match);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      if (options.length > 0) setHighlightedIndex((i) => (i + 1) % options.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (options.length > 0) setHighlightedIndex((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === "Enter") {
      if (showDropdown && highlightedIndex >= 0 && highlightedIndex < options.length) {
        e.preventDefault();
        selectOption(options[highlightedIndex]);
      }
    } else if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
        setHighlightedIndex(-1);
      }
    }
  }

  function optionId(index: number): string {
    return `${listboxId}-option-${index}`;
  }

  return (
    <div ref={containerRef} style={{ position: "relative", maxWidth: 280, width: "100%" }}>
      <input
        className="input"
        role="combobox"
        aria-expanded={showDropdown}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={showDropdown && highlightedIndex >= 0 ? optionId(highlightedIndex) : undefined}
        placeholder={placeholder}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlightedIndex(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {inviteCapable && !query && (
        <p className="text-muted" style={{ margin: "0.25rem 0 0", fontSize: "0.75rem" }}>
          {strings.userAutocomplete.canInviteHint}
        </p>
      )}
      {showDropdown && (
        <div
          id={listboxId}
          role="listbox"
          className="card stack"
          style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, marginTop: "0.25rem",
            padding: "0.25rem", gap: "0.15rem", maxHeight: 260, overflowY: "auto",
          }}
        >
          {matches.map((u, i) => (
            <button
              key={u.user_id}
              id={optionId(i)}
              role="option"
              aria-selected={highlightedIndex === i}
              type="button"
              className="btn"
              style={{
                border: "none", justifyContent: "flex-start", textAlign: "left",
                background: highlightedIndex === i ? "var(--color-surface-alt)" : undefined,
              }}
              onMouseEnter={() => setHighlightedIndex(i)}
              onClick={() => pick(u)}
            >
              {u.display_name} <span className="text-muted">({u.email})</span>
            </button>
          ))}
          {canInvite && (
            <button
              id={optionId(matches.length)}
              role="option"
              aria-selected={highlightedIndex === matches.length}
              type="button"
              className="btn"
              style={{
                border: "none", justifyContent: "flex-start", textAlign: "left",
                background: highlightedIndex === matches.length ? "var(--color-surface-alt)" : undefined,
              }}
              onMouseEnter={() => setHighlightedIndex(matches.length)}
              onClick={() => pickExternal(external!)}
            >
              {external!.exists
                ? strings.userAutocomplete.addExisting(external!.email, orgLabel)
                : strings.userAutocomplete.inviteNew.replace("{email}", external!.email)}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
