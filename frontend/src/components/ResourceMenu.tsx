import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { useStickyViewportTop } from "../hooks/useStickyViewportTop";
import { InlineSelect, type InlineSelectOption } from "./LabeledSelect";

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
 * A shared, accessible left-hand vertical menu of route-addressable groups, with a content pane on the right (the
 * "resource menu" of the style guide, Principle 1: sub-pages for more than five setting groups opened rarely as a
 * whole; `docs/ux-style-guide.md`, "Pattern: settings hierarchy").
 *
 * Keyboard support follows `Tabs.tsx` (arrow keys move focus, `Home`/`End` jump to the ends) but not its
 * `role="tablist"` pattern: each group is a real URL segment, so the menu is real links with `aria-current="page"`.
 * Arrow keys are vertical, and moving focus also navigates, since a highlighted-but-unselected item would read as active.
 *
 * Renders both the menu and the content pane (`children`), which are always laid out together.
 *
 * A group may carry `children` (sub-pages): it renders as a disclosure button (`aria-expanded`) with its sub-pages as an
 * indented list of links beneath it. The group holding the active page is open until collapsed, other groups start
 * closed, and `active` may be a group key or a sub-page key. Arrow keys move through the rows shown; landing on a link
 * navigates, landing on a header only moves focus. `Enter`/`Space` on a header toggles it.
 *
 * With one plain group (or none) the menu strip is skipped and `children` renders directly, so a caller can declare an
 * always-present group unconditionally. A single group that has sub-pages keeps the menu, since its sub-pages are the choices.
 *
 * On a wide viewport the section list is a sticky column no taller than the window below where it starts (the container
 * publishes that start as `--sticky-viewport-top`, `useStickyViewportTop`), so a long list scrolls on its own and grows
 * to full height as the page scrolls up under the header. Choosing a section brings the content pane back to its top
 * when the page was scrolled past it, and the active entry is scrolled into view within the list.
 *
 * Below `MOBILE_BREAKPOINT_PX` the link list is replaced with a single native `<select>`, so a long group list does not
 * push the selected group's content down a phone-width page; this matches `FilterPanel`'s narrow-viewport pattern
 * (`useNarrowViewport`), with a dropdown here because exactly one group is always the current page.
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
  /** The entity being administered (an organisation or project name), rendered as the page's `<h1>` above the menu and
   * content grid. Optional so a non-entity-scoped menu need not invent one; every entity-scoped consumer passes it, since
   * a menu with no other page chrome gives no way to tell which entity is shown. */
  title?: string;
  subtitle?: string;
  /** Rendered immediately after the `<h1>`, on the same row (e.g. an `EntitySwitcher` chevron) for a page whose title
   * this component renders. Ignored when `title` is omitted. */
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
  const containerRef = useRef<HTMLDivElement | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const firstRender = useRef(true);
  // The same two elements as state, so the height hook measures once they exist (the list is absent on a narrow window).
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [navEl, setNavEl] = useState<HTMLElement | null>(null);
  useStickyViewportTop(containerEl, navEl);
  const setContainer = useCallback((el: HTMLDivElement | null) => {
    containerRef.current = el;
    setContainerEl(el);
  }, []);
  const setNav = useCallback((el: HTMLElement | null) => {
    navRef.current = el;
    setNavEl(el);
  }, []);

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

  // Keep the active entry visible inside the list's own scroll area, and (after the first render, so a fresh visit
  // is not moved) bring the content pane back to its top when the page is scrolled past the start of it.
  useEffect(() => {
    const nav = navRef.current;
    const current = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (nav && current && (current.offsetTop < nav.scrollTop || current.offsetTop + current.offsetHeight > nav.scrollTop + nav.clientHeight)) {
      nav.scrollTop = current.offsetTop - (nav.clientHeight - current.offsetHeight) / 2;
    }
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const container = containerRef.current;
    const headerBottom = document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0;
    if (container && container.getBoundingClientRect().top < headerBottom && typeof container.scrollIntoView === "function") {
      container.scrollIntoView({ block: "start" });
    }
  }, [active]);

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
      {groups.length <= 1 && !groups[0]?.children?.length ? (
        children
      ) : (
        /* Its own "resource-menu" class, not the shared ".row" utility: Playwright specs use ".row" to scope one list
            row, and a ".row" wrapper around the whole content pane would become the outermost match for any text in
            the selected group's content and hijack those locators. */
        <div className="resource-menu" ref={setContainer}>
          {isNarrow ? (
            <InlineSelect
              ariaLabel={ariaLabel}
              value={active}
              placeholder={null}
              onChange={(chosen) => {
                const next =
                  groups.find((g) => g.key === chosen) ?? groups.flatMap((g) => g.children ?? []).find((c) => c.key === chosen);
                if (next) navigate(next.href);
              }}
              options={groups.flatMap((g): InlineSelectOption[] =>
                g.children?.length
                  ? g.children.map((c) => ({ value: c.key, label: c.label, group: g.label }))
                  : [{ value: g.key, label: g.label }],
              )}
            />
          ) : (
            <nav aria-label={ariaLabel} className="resource-menu-nav scroll-region" ref={setNav}>
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
