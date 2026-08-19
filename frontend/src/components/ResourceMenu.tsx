import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

export interface ResourceMenuGroupDef<K extends string> {
  key: K;
  label: string;
  /** Full route path this group's menu item links to — a real URL, not
   * client-only state, so a bookmark or browser back/forward lands on the
   * same group. */
  href: string;
}

/**
 * A shared, accessible left-hand vertical menu of route-addressable
 * groups, with a content pane on the right — the "resource menu" shape
 * named in the 2026-08 UX audit's style guide (Principle 1: resource-menu
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
 */
export function ResourceMenu<K extends string>({
  title,
  subtitle,
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
  ariaLabel: string;
  groups: ResourceMenuGroupDef<K>[];
  active: K;
  children: ReactNode;
}) {
  // Every menu link is always rendered, so the target of an arrow-key move
  // already exists in the DOM — a direct ref-array focus() call here is
  // synchronous and immediate, the same reasoning as Tabs' own buttonRefs.
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const navigate = useNavigate();

  function handleKeyDown(e: KeyboardEvent<HTMLAnchorElement>, index: number) {
    let nextIndex: number | null = null;
    if (e.key === "ArrowDown") nextIndex = (index + 1) % groups.length;
    else if (e.key === "ArrowUp") nextIndex = (index - 1 + groups.length) % groups.length;
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = groups.length - 1;
    if (nextIndex === null) return;
    e.preventDefault();
    navigate(groups[nextIndex].href);
    linkRefs.current[nextIndex]?.focus();
  }

  return (
    <div className="stack">
      {title && (
        <div className="stack" style={{ gap: "0.15rem" }}>
          <h1 style={{ margin: 0 }}>{title}</h1>
          {subtitle && <p className="text-muted" style={{ margin: 0 }}>{subtitle}</p>}
        </div>
      )}
      {/* Deliberately its own "resource-menu" class, not the shared ".row"
          utility class — ".row" is used throughout the app's Playwright specs
          as a scoping selector for one specific list row (e.g. `page.locator(
          ".row", { hasText: someRowsOwnText })`); this wrapper spans the
          entire content pane, so reusing ".row" here would make it the new
          outermost ".row" match in DOM order for *any* text anywhere in the
          selected group's content, silently hijacking every such locator on
          every page that adopts ResourceMenu (found via a real Playwright
          failure on Org Admin's Report templates delete button during this
          component's first rollout). */}
      <div className="resource-menu">
        <nav aria-label={ariaLabel} className="resource-menu-nav">
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
            {groups.map((g, i) => (
              <li key={g.key}>
                <Link
                  ref={(el) => {
                    linkRefs.current[i] = el;
                  }}
                  to={g.href}
                  className={`nav-link${active === g.key ? " active" : ""}`}
                  aria-current={active === g.key ? "page" : undefined}
                  onKeyDown={(e) => handleKeyDown(e, i)}
                >
                  {g.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="stack resource-menu-content" style={{ flex: 1, minWidth: 0 }}>
          {children}
        </div>
      </div>
    </div>
  );
}
