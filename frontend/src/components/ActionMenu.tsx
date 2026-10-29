/**
 * Module: components/ActionMenu
 *
 * A small kebab ("more actions") trigger that reveals a short menu of
 * related, non-primary actions — the "one door" shape style guide
 * Principle 11 already applies to grouped downloads, extended here to any
 * pair (or small group) of secondary actions that would otherwise sit on
 * screen together as separate, permanently-visible buttons competing for
 * the same row. See `docs/ux-style-guide.md`'s "Pattern: action menu" and
 * "Org Admin: Users/Groups, org-level
 * actions..." section — first call site is `OrgAdminPage.tsx`'s Overview
 * group, combining "Rename" and "Export {org} bundle" behind one trigger
 * instead of two adjacent buttons plus an always-visible rename input.
 *
 * Design/implementation notes:
 * - Reuses `Popover` as the anchored, positioned, focus-trapped/restored
 *   container (`dialogA11y.ts`) rather than reinventing anchoring —
 *   the same reuse `SplitButtonTrigger` already makes for its own revealed
 *   alternatives list.
 * - Record detail pages put this menu in `RecordHeader`, where it holds the
 *   record's object actions even when there is only one (style guide "Pattern:
 *   record header and object actions"); the usual two-or-more floor is waived
 *   there so the position never changes with permissions.
 * - `role="menu"` on the menu container and `role="menuitem"` on each
 * action, as required — `Popover`'s root keeps its
 *   existing `role="dialog"`/`aria-label`, so this nests a real ARIA menu
 *   inside it rather than changing `Popover` itself, which other callers
 *   (that aren't menus at all, e.g. "New group"'s create form) shouldn't
 *   be forced to inherit menu semantics from.
 * - Each item is a real, individually focusable `<button>`, so Tab/Shift+Tab
 *   moves between them and Escape/outside-click closes the menu (both via
 *   `Popover`'s shared `dialogA11y` hook). A short flat menu relies on that
 *   alone. A menu with a submenu (an item carrying `children`) also gets the
 *   WAI-ARIA menu keys, because a submenu cannot be reached or left without
 *   them: Up/Down/Home/End move within a level, Right (or Enter, Space, click)
 *   opens a submenu and focuses its first item, Left or Escape closes it and
 *   returns to its parent (Escape closes only the submenu, not the menu; with focus on an
 *   open parent it also closes only the submenu).
 *   Menus without a submenu are unchanged.
 * - A submenu opens on mouse hover after a short intent delay (so a diagonal
 *   move toward it does not close it), and on click or the keys above (a
 *   hover-only submenu cannot be opened on a touch screen or from the
 *   keyboard). It sits beside its parent (on the side with room) and, on a
 *   narrow screen, inline beneath it. One level only: a submenu item's own
 *   `children` are ignored.
 */
import type { ReactNode } from "react";
import { ChevronRight, MoreVertical } from "lucide-react";
import { Fragment, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { Popover } from "./Popover";

export interface ActionMenuItem {
  /** Visible label and accessible name for this menu item. */
  label: ReactNode;
  /** Decorative icon shown before `label` — not repeated in the accessible name. */
  icon?: ReactNode;
  onSelect: () => void;
  /** Marks a destructive action (Archive, Delete permanently) with the danger outline. */
  danger?: boolean;
  /** Stable identity when `label` isn't a plain string; defaults to the
   * string label. Never relies on position, since the item list can change
   * while the menu is open. */
  key?: string;
  /** A heading shown above this item when it starts a run of items with the same group (items of one group sit together). */
  group?: string;
  /** Muted words after the label, part of the item's name ("CSV re-imports"). */
  hint?: string;
  /** Tooltip, e.g. the full name of an acronym label. */
  title?: string;
  /** Makes this item a parent: it opens a second list of these items (one level only; their own `children` are
   * ignored) instead of acting itself, so its own `onSelect` is not called. */
  children?: ActionMenuItem[];
}

/** Milliseconds the pointer must rest on a parent before its submenu opens, and before one opened that way closes
 * after the pointer leaves, so a diagonal move toward the submenu does not drop it. */
const HOVER_INTENT_MS = 150;
/** Below this viewport width a submenu opens inline beneath its parent, not beside it. */
const NARROW_VIEWPORT_PX = 640;
const SUBMENU_GAP_PX = 2;
const SUBMENU_MARGIN_PX = 8;

/** How a submenu came to be open: a hover one closes when the pointer leaves, the others stay until closed. */
type OpenedBy = "hover" | "click" | "key";

const itemKeyOf = (item: ActionMenuItem, index: number): string =>
  item.key ?? (typeof item.label === "string" ? item.label : String(index));

/**
 * Renders a `MoreVertical` kebab button; clicking it opens a `Popover`
 * (anchored to the kebab) containing `items` as `role="menuitem"` buttons.
 * Selecting an item closes the menu and then calls its own `onSelect` —
 * callers don't need to close the menu themselves.
 *
 * @param triggerLabel - Accessible name (`aria-label`/`title`) for the
 *   kebab trigger itself, and the menu's own `aria-label`/`Popover` title.
 *   Should name what the menu acts on (e.g. `` `${org.name} actions` ``),
 *   not a bare "More actions" — Principle 8 (every interactive control has
 *   a real name), especially relevant if more than one `ActionMenu` can
 *   ever appear on the same page.
 * @param items - The menu's rows, in display order.
 * @param disabled - Disables the trigger itself (e.g. while one of the
 *   menu's own actions, such as an export, is already in flight).
 */
export function ActionMenu({
  triggerLabel,
  items,
  disabled,
  footer,
}: {
  triggerLabel: string;
  items: ActionMenuItem[];
  disabled?: boolean;
  /** Muted text under the items (a note that applies to the whole menu). */
  footer?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="btn btn-icon"
        aria-label={triggerLabel}
        title={triggerLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <MoreVertical />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} fit title={triggerLabel} onClose={() => setOpen(false)}>
          <ActionMenuList label={triggerLabel} items={items} footer={footer} onSelect={() => setOpen(false)} />
        </Popover>
      )}
    </>
  );
}

/**
 * The `role="menu"` list of items both `ActionMenu` (kebab) and `MenuButton` (labelled button) show in
 * their `Popover`. Selecting an item calls `onSelect` (the caller closes the popover) and then the item's
 * own `onSelect`.
 *
 * @param label - The menu's accessible name.
 * @param items - The rows, in display order.
 * @param onSelect - Called first when any item is chosen.
 * @param footer - Muted text under the items.
 */
export function ActionMenuList({
  label,
  items,
  onSelect,
  footer,
}: {
  label: string;
  items: ActionMenuItem[];
  onSelect: () => void;
  footer?: ReactNode;
}) {
  const [open, setOpen] = useState<{ key: string; by: OpenedBy } | null>(null);
  const hoverTimer = useRef<number | undefined>(undefined);
  const hasSubmenu = items.some((item) => item.children && item.children.length > 0);

  const clearHoverTimer = useCallback(() => window.clearTimeout(hoverTimer.current), []);
  useEffect(() => clearHoverTimer, [clearHoverTimer]);

  /** Moves the pointer onto a row: a parent opens after the intent delay, any other row closes a hover-opened submenu. */
  function hoverRow(key: string | null) {
    if (!hasSubmenu) return;
    clearHoverTimer();
    hoverTimer.current = window.setTimeout(() => {
      setOpen((current) => {
        if (key) return current?.key === key ? current : { key, by: "hover" };
        return current?.by === "hover" ? null : current;
      });
    }, HOVER_INTENT_MS);
  }

  function leaveRow(key: string) {
    clearHoverTimer();
    hoverTimer.current = window.setTimeout(() => {
      setOpen((current) => (current?.key === key && current.by === "hover" ? null : current));
    }, HOVER_INTENT_MS);
  }

  /** The menu keys, only for a menu that has a submenu (a flat menu relies on Tab, see the module comment). */
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!hasSubmenu) return;
    const target = e.target as HTMLElement;
    if (target.getAttribute("role") !== "menuitem") return;
    const level = target.closest<HTMLElement>('[role="menu"]');
    if (!level) return;
    const inSubmenu = level !== e.currentTarget;
    const siblings = Array.from(level.querySelectorAll<HTMLElement>(':scope > [role="menuitem"], :scope > .menu-submenu-host > [role="menuitem"]'));
    const at = siblings.indexOf(target);
    const move = (to: number) => {
      e.preventDefault();
      siblings[(to + siblings.length) % siblings.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(siblings.length - 1);
    else if (e.key === "ArrowRight" && !inSubmenu && target.getAttribute("aria-haspopup") === "menu") {
      e.preventDefault();
      setOpen({ key: target.dataset.itemKey ?? "", by: "key" });
    } else if (e.key === "Escape" && !inSubmenu && target.getAttribute("aria-expanded") === "true") {
      // Focus is on a parent whose submenu is open (opened by click or hover): Escape closes that first.
      e.preventDefault();
      e.stopPropagation();
      setOpen(null);
    } else if ((e.key === "ArrowLeft" || e.key === "Escape") && inSubmenu) {
      // Only the submenu closes: stopping the event keeps the dialog's own Escape handler from closing the menu too.
      e.preventDefault();
      e.stopPropagation();
      const parent = level.parentElement?.querySelector<HTMLElement>(':scope > [role="menuitem"]');
      setOpen(null);
      parent?.focus();
    }
  }

  return (
    <div role="menu" aria-label={label} className="stack" style={{ gap: "0.15rem", minWidth: 180 }} onKeyDown={onKeyDown}>
      {items.map((item, i) => {
        // Keyed by label, not index: a caller's item list can change while the menu is open (Org Admin adds
        // "Rename" once its settings load), and an index key made React hand one item's button — and click
        // handler — to another, so clicking "Export" opened Rename (found 2026-10-04 via the e2e suite).
        const key = itemKeyOf(item, i);
        return (
          <Fragment key={key}>
            {item.group && item.group !== items[i - 1]?.group && (
              <span role="presentation" className="menu-group-label">{item.group}</span>
            )}
            {item.children && item.children.length > 0 ? (
              <SubmenuItem
                item={item}
                itemKey={key}
                isOpen={open?.key === key}
                focusFirst={open?.key === key && open.by === "key"}
                onHover={() => hoverRow(key)}
                onLeave={() => leaveRow(key)}
                onOpen={(by) => setOpen({ key, by })}
                onSelect={onSelect}
              />
            ) : (
              <button
                type="button"
                role="menuitem"
                className={item.danger ? "btn btn-danger menu-item" : "btn menu-item"}
                title={item.title}
                onMouseEnter={() => hoverRow(null)}
                onClick={() => {
                  onSelect();
                  item.onSelect();
                }}
              >
                {item.icon} {item.label}
                {item.hint && <span className="text-muted menu-item-hint">{item.hint}</span>}
              </button>
            )}
          </Fragment>
        );
      })}
      {footer && <span role="presentation" className="menu-footer text-muted">{footer}</span>}
    </div>
  );
}

/**
 * A menu row that opens a second list (`ActionMenuItem.children`). The parent is a `menuitem` with
 * `aria-haspopup="menu"`/`aria-expanded`; the list is a `role="menu"` inside the same host element, so the
 * pointer moving into it stays within the host and the popover's outside-click and focus trap still cover it.
 * Beside the parent on a wide screen (on the side with room), inline beneath it on a narrow one.
 */
function SubmenuItem({
  item, itemKey, isOpen, focusFirst, onHover, onLeave, onOpen, onSelect,
}: {
  item: ActionMenuItem;
  itemKey: string;
  isOpen: boolean;
  focusFirst: boolean;
  onHover: () => void;
  onLeave: () => void;
  onOpen: (by: OpenedBy) => void;
  onSelect: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const name = typeof item.label === "string" ? item.label : itemKey;

  // Place the list beside the parent, flipped to the left when the right has no room, kept inside the viewport.
  useLayoutEffect(() => {
    if (!isOpen) return;
    function place() {
      const host = hostRef.current;
      const list = listRef.current;
      if (!host || !list) return;
      if (window.innerWidth < NARROW_VIEWPORT_PX) {
        list.style.position = "static";
        list.style.visibility = "visible";
        return;
      }
      const parent = host.getBoundingClientRect();
      const own = list.getBoundingClientRect();
      const fitsRight = parent.right + SUBMENU_GAP_PX + own.width <= window.innerWidth - SUBMENU_MARGIN_PX;
      const left = fitsRight ? parent.right + SUBMENU_GAP_PX : Math.max(SUBMENU_MARGIN_PX, parent.left - SUBMENU_GAP_PX - own.width);
      const top = Math.max(SUBMENU_MARGIN_PX, Math.min(parent.top, window.innerHeight - own.height - SUBMENU_MARGIN_PX));
      list.style.position = "fixed";
      list.style.left = `${left}px`;
      list.style.top = `${top}px`;
      list.style.visibility = "visible";
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && focusFirst) listRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [isOpen, focusFirst]);

  return (
    <div ref={hostRef} className="menu-submenu-host" onMouseEnter={onHover} onMouseLeave={onLeave}>
      <button
        type="button"
        role="menuitem"
        className="btn menu-item menu-submenu-parent"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listId : undefined}
        data-item-key={itemKey}
        onClick={() => onOpen("click")}
      >
        {item.icon} {item.label}
        <ChevronRight aria-hidden="true" size={14} className="menu-submenu-chevron" />
      </button>
      {isOpen && (
        <div
          ref={listRef}
          id={listId}
          role="menu"
          aria-label={name}
          className="card stack menu-submenu"
          style={{ gap: "0.15rem", visibility: "hidden" }}
        >
          {(item.children ?? []).map((child, j) => (
            <button
              key={itemKeyOf(child, j)}
              type="button"
              role="menuitem"
              className={child.danger ? "btn btn-danger menu-item" : "btn menu-item"}
              title={child.title}
              onClick={() => {
                onSelect();
                child.onSelect();
              }}
            >
              {child.icon} {child.label}
              {child.hint && <span className="text-muted menu-item-hint">{child.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
