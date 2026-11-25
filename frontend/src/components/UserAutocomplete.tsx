import { FolderKanban, Users } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { api } from "../api/client";
import type { ExternalUserMatch, OrgGroup, OrgUser, OrgUserSearchResult, ProjectGroup } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { t } from "../i18n/strings";
import { Badge } from "./Badge";
import { ServiceBadge } from "./ServiceBadge";
import { useResetOnChange } from "../hooks/useResetOnChange";

const strings = t();

type Option =
  | { kind: "user"; user: OrgUser }
  | { kind: "group"; group: OrgGroup }
  | { kind: "projectGroup"; group: ProjectGroup }
  | { kind: "external"; match: ExternalUserMatch };

/**
 * Type-to-filter picker over org users, so a caller never pastes a raw user id.
 *
 * Two modes:
 * - Default (no `organizationId`): matches display name or email against the `users` the screen already loaded (no API call).
 * - `organizationId` set: debounced server-side search (`orgs/{id}/users/search`), which can also surface a synthetic
 *   "external" result (an email not yet a member of this org) when `Organization.external_user_policy` allows it.
 *   Selecting it calls `onSelectExternal` instead of `onSelect` (required in this mode). `projectId` lets the search
 *   reveal an existing account elsewhere in the system to a caller who manages that project, not only to org admins (see
 *   the backend endpoint's docstring for why that fact is gated).
 *
 * Optional third match kind: `groups` (with `onSelectGroup`) also matches org groups by name, always client-side against
 * the passed array, whether user matching is client- or server-side. A group match shows a `Users` icon and an
 * "Organisation group" badge, and selecting it calls `onSelectGroup(groupId)` instead of `onSelect`, then closes and
 * resets the control as a user pick does. `Users` (plural) reads as "more than one person" and is not used by another
 * concept in the icon set.
 *
 * Optional fourth match kind: `projectGroups` (with `onSelectProjectGroup`) also matches this project's own
 * `ProjectGroup`s by name, with the same client-side substring match. A project group is local to one project rather than
 * org-wide, so it has a distinct treatment: `FolderKanban` (the icon `Layout.tsx`'s nav rail uses for "Projects") and a
 * "Project group" badge, so the two group badges cannot be confused. Selecting one calls `onSelectProjectGroup(groupId)`.
 */
export function UserAutocomplete({
  users,
  onSelect,
  onSelectExternal,
  groups,
  onSelectGroup,
  projectGroups,
  onSelectProjectGroup,
  organizationId,
  projectId,
  placeholder,
  ariaLabel,
}: {
  users: OrgUser[];
  onSelect: (userId: string) => void;
  onSelectExternal?: (email: string) => void;
  /** Organisation groups to also match by name (see module docstring). Omit to
   * keep this instance user-only, unchanged from before this prop existed. */
  groups?: OrgGroup[];
  /** Required alongside `groups` — called with the matched group's id
   * instead of `onSelect` when a group option is chosen. */
  onSelectGroup?: (groupId: string) => void;
  /** This project's own `ProjectGroup`s to also match by name (see
   * module docstring). Omit to keep this instance without project-group
   * matching. */
  projectGroups?: ProjectGroup[];
  /** Required alongside `projectGroups` — called with the matched project
   * group's id instead of `onSelect`/`onSelectGroup` when a project-group
   * option is chosen. */
  onSelectProjectGroup?: (groupId: string) => void;
  organizationId?: string;
  projectId?: string;
  placeholder?: string;
  /** Accessible name for the search input, for callers where the visible `placeholder` alone cannot tell several
   * instances on one page apart (e.g. one per row). Falls back to `placeholder` when omitted. */
  ariaLabel?: string;
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
  useResetOnChange([organizationId, needle.length === 0], () => {
    setServerMatches([]);
    setExternal(null);
  });

  useEffect(() => {
    if (!organizationId || needle.length === 0) return;
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

  // Group matches are always client-side against the passed `groups` array (substring match on `name`), whether
  // `matches` above runs client- or server-side.
  const groupMatches =
    groups && needle.length > 0 ? groups.filter((g) => g.name.toLowerCase().includes(needle)).slice(0, 8) : [];

  // Project-group matches (see module docstring): same client-side
  // substring match as org groups above, against the passed-in
  // `projectGroups` array.
  const projectGroupMatches =
    projectGroups && needle.length > 0
      ? projectGroups.filter((g) => g.name.toLowerCase().includes(needle)).slice(0, 8)
      : [];

  // Whether this instance is wired up to invite an external user at all
  // (vs. only ever adding an existing member) — drives the persistent hint,
  // shown before a query narrows things down to an actual external match.
  const inviteCapable = !!(organizationId && onSelectExternal);
  const canInvite = !!(external && onSelectExternal);
  const options: Option[] = [
    ...matches.map((user): Option => ({ kind: "user", user })),
    ...groupMatches.map((group): Option => ({ kind: "group", group })),
    ...projectGroupMatches.map((group): Option => ({ kind: "projectGroup", group })),
    ...(canInvite ? [{ kind: "external", match: external! } as Option] : []),
  ];
  const showDropdown = open && options.length > 0;

  function pick(user: OrgUser) {
    onSelect(user.user_id);
    setQuery("");
    setOpen(false);
    setHighlightedIndex(-1);
  }

  function pickGroup(group: OrgGroup) {
    onSelectGroup?.(group.id);
    setQuery("");
    setOpen(false);
    setHighlightedIndex(-1);
  }

  function pickProjectGroup(group: ProjectGroup) {
    onSelectProjectGroup?.(group.id);
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
    else if (option.kind === "group") pickGroup(option.group);
    else if (option.kind === "projectGroup") pickProjectGroup(option.group);
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
        aria-label={ariaLabel ?? placeholder}
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
        <p className="text-muted" style={{ margin: "var(--space-1) 0 0", fontSize: "0.75rem" }}>
          {strings.userAutocomplete.canInviteHint}
        </p>
      )}
      {showDropdown && (
        <div
          id={listboxId}
          role="listbox"
          className="card stack scroll-region"
          style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, marginTop: "var(--space-1)",
            padding: "var(--space-1)", gap: "0.15rem", maxHeight: 260,
          }}
        >
          {matches.map((u, i) => (
            <button
              key={u.user_id}
              id={optionId(i)}
              role="option"
              aria-selected={highlightedIndex === i}
              type="button"
              className="menu-item"
              onMouseEnter={() => setHighlightedIndex(i)}
              onClick={() => pick(u)}
            >
              {u.display_name} {u.is_service_account ? <ServiceBadge /> : <span className="text-muted">({u.email})</span>}
            </button>
          ))}
          {groupMatches.map((g, j) => {
            const index = matches.length + j;
            return (
              <button
                key={g.id}
                id={optionId(index)}
                role="option"
                aria-selected={highlightedIndex === index}
                type="button"
                className="menu-item"
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => pickGroup(g)}
              >
                <Users aria-hidden="true" />
                {g.name} <Badge>{strings.userAutocomplete.groupBadge}</Badge>
              </button>
            );
          })}
          {projectGroupMatches.map((g, k) => {
            const index = matches.length + groupMatches.length + k;
            return (
              <button
                key={g.id}
                id={optionId(index)}
                role="option"
                aria-selected={highlightedIndex === index}
                type="button"
                className="menu-item"
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => pickProjectGroup(g)}
              >
                <FolderKanban aria-hidden="true" />
                {g.name} <Badge>{strings.userAutocomplete.projectGroupBadge}</Badge>
              </button>
            );
          })}
          {canInvite && (
            <button
              id={optionId(matches.length + groupMatches.length + projectGroupMatches.length)}
              role="option"
              aria-selected={highlightedIndex === matches.length + groupMatches.length + projectGroupMatches.length}
              type="button"
              className="menu-item"
              onMouseEnter={() => setHighlightedIndex(matches.length + groupMatches.length + projectGroupMatches.length)}
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
