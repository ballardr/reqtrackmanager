/**
 * Module: components/EntitySwitcher
 *
 * The generic "entity quick-switch" chevron: a small `ChevronDown` button beside an entity's name in a page's own
 * `<h1>` opening a `Popover` of every sibling instance of the entity type the user can reach, as links to the
 * equivalent page. It is not a persistent "current entity" context or tenant switcher (`docs/ux-style-guide.md`
 * Principle 9): it appears on a page already scoped by its URL and picking a sibling is an ordinary navigation.
 *
 * It takes the current id and a `loadOptions` loader returning every candidate sibling (the current one is
 * filtered out), so no entity-specific logic lives here. The trigger renders nothing while loading or when the
 * list is empty; beyond a handful of siblings a substring filter appears. The trigger uses the borderless
 * `.entity-switcher-trigger` class (`theme.css`), not `.btn`, so the chevron reads as part of the name.
 */
import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Popover } from "./Popover";

/** Above this many siblings, a filter input appears above the list —
 * mirrors `UserAutocomplete`'s own `.slice(0, 8)` cap. */
const FILTER_THRESHOLD = 8;

export interface EntitySwitcherOption {
  id: string;
  label: string;
  href: string;
}

/**
 * Renders a chevron trigger + popover for switching between sibling
 * entity instances.
 *
 * @param label - Accessible name for both the trigger button and the
 *   popover it opens, e.g. "Switch organisation".
 * @param currentId - The id of the entity instance the current page is
 *   scoped to; excluded from the list of siblings offered.
 * @param loadOptions - Fetches every candidate sibling reachable by the
 *   current user (the current entity may be included; it is filtered out
 *   here). Re-run whenever `currentId` or `reloadKey` changes.
 * @param reloadKey - Optional; change it to refetch the options.
 */
export function EntitySwitcher({
  label,
  currentId,
  loadOptions,
  reloadKey,
}: {
  label: string;
  currentId: string;
  loadOptions: () => Promise<EntitySwitcherOption[]>;
  /** For a caller whose options can change after mount (e.g. a version
   * just created), so the switcher doesn't keep its first list. */
  reloadKey?: string;
}) {
  const [siblings, setSiblings] = useState<EntitySwitcherOption[] | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    loadOptions()
      .then((options) => {
        if (!cancelled) setSiblings(options.filter((o) => o.id !== currentId));
      })
      .catch(() => {
        // A failed sibling-list fetch reads as "nothing to switch to": this secondary affordance disappears
        // quietly rather than breaking or error-toasting the page.
        if (!cancelled) setSiblings([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, reloadKey]);

  if (!siblings || siblings.length === 0) return null;

  const needle = query.trim().toLowerCase();
  const visible = needle.length === 0 ? siblings : siblings.filter((s) => s.label.toLowerCase().includes(needle));

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="entity-switcher-trigger"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronDown size={14} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={label} onClose={() => setOpen(false)}>
          <div className="stack" style={{ gap: "0.15rem" }}>
            {siblings.length > FILTER_THRESHOLD && (
              <input
                className="input"
                placeholder="Filter…"
                aria-label="Filter"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            )}
            <div className="menu-list scroll-region" style={{ maxHeight: 320 }}>
              {visible.map((s) => (
                <Link
                  key={s.id}
                  to={s.href}
                  className="menu-item"
                  onClick={() => setOpen(false)}
                >
                  {s.label}
                </Link>
              ))}
              {visible.length === 0 && (
                <p className="text-muted" style={{ margin: 0 }}>
                  No matches.
                </p>
              )}
            </div>
          </div>
        </Popover>
      )}
    </>
  );
}
