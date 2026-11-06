import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useNarrowViewport } from "../hooks/useNarrowViewport";

// Matches FilterPanel.tsx's and Layout.tsx's own mobile breakpoint
// (theme.css, `@media (max-width: 860px)`) — all three should agree on
// where "mobile" starts rather than disagreeing at some widths.
const MOBILE_BREAKPOINT_PX = 860;

/** A sub-page listed under an expandable group. */
export interface ResourceMenuChildDef {
  key: string;
  label: string;
  /** Full route path of the sub-page, a real URL like a group's own. */
  href: string;
}

export interface ResourceMenuGroupDef<K extends string> {
  key: K;
  label: string;
  /** Full route path this group's menu item links to — a real URL, not
   * client-only state, so a bookmark or browser back/forward lands on the
   * same group. For a group with `children` it is the first sub-page's path. */
  href: string;
  /** Sub-pages. A group with two or more is an expandable entry (a second level, never a third) whose header only
   * expands and collapses; a group without them is a plain link. */
  children?: ResourceMenuChildDef[];
}

/** One focusable row of the menu as currently shown: a plain group link, an expandable group's header, or a sub-page. */
type VisibleRow =
  | { id: string; kind: "link"; key: string; href: string }
  | { id: string; kind: "header"; key: string }
  | { id: string; kind: "child"; key: string; href: string };

/**
 * A shared, accessible left-hand vertical menu of route-addressable
 * groups, with a content pane on the right — the "resource menu" shape
 * named in the style guide (Principle 1: resource-menu
 * sub-pages for more than five setting groups opened rarely as a whole).
 * First user: Org Admin's 15-way flat accordion wall, split into 6 groups
 * (`docs/ux-style-guide.md`, "Pattern: settings hierarchy").
 *
 * Modelled on `Tabs.tsx`'s WAI-ARIA-conscious keyboard support (arrow keys
 * move focus, `Home`/`End` jump to the ends) but deliberately *not* built
 * on the `role="tablist"`/`"tab"` pattern Tabs uses — each group here is a
 * real URL segment (`href`), not client-only state, so the menu is built
 * from real links with `aria-current="page"` on the active one rather than
 * `aria-selected`. Arrow-key navigation is vertical (`ArrowUp`/`ArrowDown`,
 * matching the menu's own layout) rather than horizontal, and — mirroring
 * Tabs' own automatic-activation model, just adapted from internal state
 * to routing — moving focus with an arrow key also navigates, since a
 * highlighted-but-unselected menu item would otherwise read as active
 * without being the one whose content pane is showing.
 *
 * Renders both the menu and the content pane (`children`) as one unit —
 * unlike `Tabs` (menu strip only, panel wrapper left to the caller) — since
 * the two are always laid out together here and the caller has no reason
 * to place them independently.
 *
 * A group may carry `children` (sub-pages): it then renders as a disclosure button (`aria-expanded`) with its
 * sub-pages as an indented list of links beneath it. The group holding the active page is open until the person
 * collapses it, other groups start closed, and `active` may be a group key or a sub-page key. Arrow keys move through
 * the rows currently shown (headers and the sub-pages of open groups); landing on a link navigates, landing on a
 * header only moves focus. `Enter`/`Space` on a header (a native button) toggles it.
 *
 * When `groups.length <= 1` the menu strip itself (the `<nav>`/`<ul>` of
 * group links) is skipped entirely and `children` renders directly —
 * a single-entry menu has nothing to switch between, so the chrome
 * would just be a list with one link that's always already active. This
 * lets a caller declare an always-present group unconditionally (e.g.
 * `OrgOverviewPage.tsx`'s "Overview") without that caller needing to know
 * whether any other group exists — `ResourceMenu` itself decides whether
 * that's worth a visible menu.
 *
 * Below `MOBILE_BREAKPOINT_PX` the vertical `<nav>`/`<ul>` link list is
 * replaced with a single native `<select>` (platform-review-2026-09,
 * "resource menus wasting space on narrow windows"). Org Admin alone has up
 * to 10 groups — the full-height list this component renders on desktop
 * pushes every group's own content below a page-and-a-half of nav chrome on
 * a phone-width viewport, forcing a scroll past all of it just to reach the
 * selected group's settings. A `<select>` collapses that same list of
 * groups to one row, matching `FilterPanel`'s own narrow-viewport pattern
 * (`useNarrowViewport`) even though the two widgets differ (accordion
 * there, since that content is optional filter chrome; a dropdown here,
 * since exactly one group is always the "current page").
 */
export function ResourceMenu<K extends string>({
  title,
  subtitle,
  titleAdornment,
  ariaLabel,
  groups,
  active,
  children,
}: {
  /** The entity actually being administered (an org or project's own
   * name) — rendered as the page's `<h1>`, above the menu+content grid.
   * Optional so a future non-entity-scoped resource menu (e.g. a
   * platform-wide settings page) isn't forced to invent one, but every
   * current consumer is scoped to one org/project and should always pass
   * it: a resource menu with no other page chrome around it previously
   * left no way to tell which one you were looking at. */
  title?: string;
  subtitle?: string;
  /** Rendered immediately after the `<h1>`, on the same row — e.g. an
   * `EntitySwitcher` chevron for
   * a page whose title is rendered by this component rather than a bespoke
   * `<h1>` of its own (which can just place the switcher next to its own
   * heading directly, as `ProjectAdminPage.tsx` already does). Ignored
   * when `title` is omitted. */
  titleAdornment?: ReactNode;
  ariaLabel: string;
  groups: ResourceMenuGroupDef<K>[];
  active: K;
  children: ReactNode;
}) {
  // Every menu link is always rendered, so the target of an arrow-key move
  // already exists in the DOM — a direct ref-array focus() call here is
  // synchronous and immediate, the same reasoning as Tabs' own buttonRefs.
  const rowRefs = useRef<Record<string, HTMLElement | null>>({});
  const navigate = useNavigate();
  const isNarrow = useNarrowViewport(MOBILE_BREAKPOINT_PX);

  // The group holding the active page, whether `active` names the group or one of its sub-pages.
  const activeGroupKey = groups.find((g) => g.key === active || g.children?.some((c) => c.key === active))?.key;
  // A person's own expand/collapse choice per group; absent means "open only while it holds the active page". Choosing
  // a new active page clears that group's override so navigating into it always shows it.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [seenActiveGroup, setSeenActiveGroup] = useState(activeGroupKey);
  if (seenActiveGroup !== activeGroupKey) {
    setSeenActiveGroup(activeGroupKey);
    if (activeGroupKey) {
      setOverrides((current) => {
        const next = { ...current };
        delete next[activeGroupKey];
        return next;
      });
    }
  }
  const isOpen = (g: ResourceMenuGroupDef<string>) => overrides[g.key] ?? g.key === activeGroupKey;

  const rows: VisibleRow[] = groups.flatMap((g): VisibleRow[] => {
    if (!g.children?.length) return [{ id: `g:${g.key}`, kind: "link", key: g.key, href: g.href }];
    const header: VisibleRow = { id: `g:${g.key}`, kind: "header", key: g.key };
    return isOpen(g)
      ? [header, ...g.children.map((c): VisibleRow => ({ id: `c:${c.key}`, kind: "child", key: c.key, href: c.href }))]
      : [header];
  });

  function handleKeyDown(e: KeyboardEvent<HTMLElement>, index: number) {
    let nextIndex: number | null = null;
    if (e.key === "ArrowDown") nextIndex = (index + 1) % rows.length;
    else if (e.key === "ArrowUp") nextIndex = (index - 1 + rows.length) % rows.length;
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = rows.length - 1;
    if (nextIndex === null) return;
    e.preventDefault();
    const next = rows[nextIndex];
    if (next.kind !== "header") navigate(next.href);
    rowRefs.current[next.id]?.focus();
  }

  function renderLink(row: Extract<VisibleRow, { href: string }>, label: string, index: number) {
    const isActive = active === row.key;
    return (
      <Link
        ref={(el) => {
          rowRefs.current[row.id] = el;
        }}
        to={row.href}
        className={`nav-link${isActive ? " active" : ""}`}
        aria-current={isActive ? "page" : undefined}
        onKeyDown={(e) => handleKeyDown(e, index)}
      >
        {label}
      </Link>
    );
  }

  return (
    <div className="stack">
      {title && (
        <div className="stack" style={{ gap: "0.15rem" }}>
          <div className="row" style={{ alignItems: "center", gap: "var(--space-1)" }}>
            <h1 style={{ margin: 0 }}>{title}</h1>
            {titleAdornment}
          </div>
          {subtitle && <p className="text-muted" style={{ margin: 0 }}>{subtitle}</p>}
        </div>
      )}
      {groups.length <= 1 ? (
        children
      ) : (
        /* Deliberately its own "resource-menu" class, not the shared ".row"
            utility class — ".row" is used throughout the app's Playwright specs
            as a scoping selector for one specific list row (e.g. `page.locator(
            ".row", { hasText: someRowsOwnText })`); this wrapper spans the
            entire content pane, so reusing ".row" here would make it the new
            outermost ".row" match in DOM order for *any* text anywhere in the
            selected group's content, silently hijacking every such locator on
            every page that adopts ResourceMenu (found via a real Playwright
            failure on an Org Admin delete button during this
            component's first rollout). */
        <div className="resource-menu">
          {isNarrow ? (
            <select
              className="input"
              aria-label={ariaLabel}
              value={active}
              onChange={(e) => {
                const chosen = e.target.value;
                const next =
                  groups.find((g) => g.key === chosen) ?? groups.flatMap((g) => g.children ?? []).find((c) => c.key === chosen);
                if (next) navigate(next.href);
              }}
            >
              {groups.map((g) =>
                g.children?.length ? (
                  <optgroup key={g.key} label={g.label}>
                    {g.children.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.label}
                      </option>
                    ))}
                  </optgroup>
                ) : (
                  <option key={g.key} value={g.key}>
                    {g.label}
                  </option>
                ),
              )}
            </select>
          ) : (
            <nav aria-label={ariaLabel} className="resource-menu-nav">
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
                {groups.map((g) => {
                  const rowIndex = rows.findIndex((r) => r.id === `g:${g.key}`);
                  if (!g.children?.length) {
                    return <li key={g.key}>{renderLink({ id: `g:${g.key}`, kind: "link", key: g.key, href: g.href }, g.label, rowIndex)}</li>;
                  }
                  const open = isOpen(g);
                  const listId = `resource-menu-${g.key}`;
                  return (
                    <li key={g.key}>
                      <button
                        ref={(el) => {
                          rowRefs.current[`g:${g.key}`] = el;
                        }}
                        type="button"
                        className={`nav-link nav-link-button${g.key === activeGroupKey ? " nav-link-parent-active" : ""}`}
                        aria-expanded={open}
                        aria-controls={listId}
                        onClick={() => setOverrides((current) => ({ ...current, [g.key]: !open }))}
                        onKeyDown={(e) => handleKeyDown(e, rowIndex)}
                      >
                        <span className="nav-label">{g.label}</span>
                        <span className="nav-link-button-chevron" aria-hidden="true">
                          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </span>
                      </button>
                      {open && (
                        <ul id={listId} className="nav-more-list" style={{ margin: 0, listStyle: "none" }}>
                          {g.children.map((c) => (
                            <li key={c.key}>
                              {renderLink(
                                { id: `c:${c.key}`, kind: "child", key: c.key, href: c.href },
                                c.label,
                                rows.findIndex((r) => r.id === `c:${c.key}`),
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </nav>
          )}
          <div className="stack resource-menu-content" style={{ flex: 1, minWidth: 0 }}>
            {children}
          </div>
        </div>
      )}
    </div>
  );
}
