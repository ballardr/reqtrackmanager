import { FolderKanban, Users } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { api } from "../api/client";
import type { ExternalUserMatch, OrgGroup, OrgUser, OrgUserSearchResult, ProjectGroup } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { t } from "../i18n/strings";

const strings = t();

type Option =
  | { kind: "user"; user: OrgUser }
  | { kind: "group"; group: OrgGroup }
  | { kind: "projectGroup"; group: ProjectGroup }
  | { kind: "external"; match: ExternalUserMatch };

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
 *
 * Optional third match kind (PR5 of the members/groups directory rework
 * plan): pass `groups` (and `onSelectGroup`) to also match org groups by
 * name, always client-side against the passed-in array — mirroring the
 * default (no-`organizationId`) user-matching logic exactly, regardless of
 * whether user matching itself is running client- or server-side in this
 * instance. A group match renders with a `Users` icon and an "Org group"
 * badge so it's visually distinct from a user row in the same dropdown, and
 * selecting one calls `onSelectGroup(groupId)` instead of `onSelect`, then
 * closes/resets the control the same way a user pick does. There is no
 * dedicated "group" icon anywhere else in this app to match (grepped every
 * existing group-related header/row for one before adding this) — `Users`
 * (plural) was chosen over the single-person `User` glyph used implicitly
 * elsewhere for exactly that reason: it reads as "more than one person," a
 * reasonable stand-in for "a group of users," and isn't already claimed by
 * another concept in this codebase's icon usage.
 *
 * Optional fourth match kind (PR7): pass `projectGroups` (and
 * `onSelectProjectGroup`) to also match this project's own `ProjectGroup`s
 * by name, same client-side substring match. A project group is a
 * genuinely different concept from an org group — local to this one
 * project rather than org-wide — so it needs a visually distinguishable,
 * not identical, treatment: `FolderKanban` (the same icon `Layout.tsx`'s
 * nav rail already uses for "Projects") instead of `Users`, and a
 * "Project group" badge instead of "Org group" (the org-group badge's text
 * was tightened from the previous bare "Group" to "Org group" at the same
 * time, now that a second, similarly-named group concept can appear in the
 * same dropdown — leaving it as just "Group" would read as ambiguous next
 * to "Project group"). Selecting a project-group match calls
 * `onSelectProjectGroup(groupId)` instead of `onSelect`/`onSelectGroup`.
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
}: {
  users: OrgUser[];
  onSelect: (userId: string) => void;
  onSelectExternal?: (email: string) => void;
  /** Org groups to also match by name (PR5 — see module docstring). Omit to
   * keep this instance user-only, unchanged from before this prop existed. */
  groups?: OrgGroup[];
  /** Required alongside `groups` — called with the matched group's id
   * instead of `onSelect` when a group option is chosen. */
  onSelectGroup?: (groupId: string) => void;
  /** This project's own `ProjectGroup`s to also match by name (PR7 — see
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

  // Group matches (PR5 — see module docstring): always client-side against
  // the passed-in `groups` array, mirroring the default user-matching
  // branch above exactly (substring match on the one text field a group
  // has, `name`), regardless of whether `matches` above is running
  // client- or server-side in this instance.
  const groupMatches =
    groups && needle.length > 0 ? groups.filter((g) => g.name.toLowerCase().includes(needle)).slice(0, 8) : [];

  // Project-group matches (PR7 — see module docstring): same client-side
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
          {groupMatches.map((g, j) => {
            const index = matches.length + j;
            return (
              <button
                key={g.id}
                id={optionId(index)}
                role="option"
                aria-selected={highlightedIndex === index}
                type="button"
                className="btn"
                style={{
                  border: "none", justifyContent: "flex-start", textAlign: "left", alignItems: "center", gap: "0.35rem",
                  background: highlightedIndex === index ? "var(--color-surface-alt)" : undefined,
                }}
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => pickGroup(g)}
              >
                <Users size={14} aria-hidden="true" />
                {g.name} <span className="badge">{strings.userAutocomplete.groupBadge}</span>
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
                className="btn"
                style={{
                  border: "none", justifyContent: "flex-start", textAlign: "left", alignItems: "center", gap: "0.35rem",
                  background: highlightedIndex === index ? "var(--color-surface-alt)" : undefined,
                }}
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => pickProjectGroup(g)}
              >
                <FolderKanban size={14} aria-hidden="true" />
                {g.name} <span className="badge">{strings.userAutocomplete.projectGroupBadge}</span>
              </button>
            );
          })}
          {canInvite && (
            <button
              id={optionId(matches.length + groupMatches.length + projectGroupMatches.length)}
              role="option"
              aria-selected={highlightedIndex === matches.length + groupMatches.length + projectGroupMatches.length}
              type="button"
              className="btn"
              style={{
                border: "none", justifyContent: "flex-start", textAlign: "left",
                background:
                  highlightedIndex === matches.length + groupMatches.length + projectGroupMatches.length
                    ? "var(--color-surface-alt)"
                    : undefined,
              }}
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
