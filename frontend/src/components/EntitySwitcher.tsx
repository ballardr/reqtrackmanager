/**
 * Module: components/EntitySwitcher
 *
 * The generic "entity quick-switch" chevron (docs/compliance-module-plan.md
 * Phase 28) — a small `ChevronDown` button that sits next to an entity's
 * name in a page's own `<h1>` and opens a `Popover` listing every sibling
 * instance of the same entity type the current user can reach, as plain
 * links to the equivalent page for that instance.
 *
 * This is deliberately *not* a persistent "current entity" context or an
 * Azure/Entra-style tenant switcher — `docs/ux-style-guide.md` Principle 9
 * explicitly rejects that shape for org-level navigation, because this
 * app's content deliberately pools across every org a user belongs to.
 * This component only ever appears on a page already scoped to one
 * specific entity instance by its own URL; picking a sibling just
 * navigates to that sibling's equivalent page, the same as any other link
 * — it introduces no ambient state and changes nothing about how any other
 * page renders. See the style guide's Principle 9 note for the fuller
 * distinction.
 *
 * Parameterized only by the current entity's id and a `loadOptions` loader
 * returning every candidate sibling (including, harmlessly, the current
 * entity itself — filtered out below) — no module- or entity-specific
 * logic lives in this file, so a caller wires up whatever "list of
 * siblings I can reach" fetch makes sense for its own entity type
 * (`GET /orgs?mine=true`, `GET /projects?archived=false`, the compliance
 * module's own cross-org standards fan-out, etc.) rather than this
 * component knowing about any of them.
 *
 * The trigger renders nothing at all while the sibling list is loading or
 * turns out empty — a chevron that opens onto an empty popover, or that
 * flashes in and back out once loading resolves, is worse than no
 * affordance. Once there are more than a handful of siblings, a lightweight
 * substring filter appears above the list, reusing `UserAutocomplete`'s own
 * "lowercase/trim the query, filter on it, hide everything when empty"
 * idiom (not the component itself — this list has no user/group-selection
 * semantics) rather than inventing a second filtering convention.
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
 *   here). Re-run whenever `currentId` changes.
 */
export function EntitySwitcher({
  label,
  currentId,
  loadOptions,
}: {
  label: string;
  currentId: string;
  loadOptions: () => Promise<EntitySwitcherOption[]>;
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
        // A failed sibling-list fetch is equivalent to "nothing to switch
        // to" — this is a small, secondary navigation affordance, not
        // core page content, so it disappears quietly rather than
        // breaking (or ever error-toasting) the page it sits on.
        if (!cancelled) setSiblings([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  if (!siblings || siblings.length === 0) return null;

  const needle = query.trim().toLowerCase();
  const visible = needle.length === 0 ? siblings : siblings.filter((s) => s.label.toLowerCase().includes(needle));

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="btn"
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
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            )}
            <div className="stack" style={{ gap: "0.15rem", maxHeight: 320, overflowY: "auto" }}>
              {visible.map((s) => (
                <Link
                  key={s.id}
                  to={s.href}
                  className="btn"
                  style={{ justifyContent: "flex-start" }}
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
