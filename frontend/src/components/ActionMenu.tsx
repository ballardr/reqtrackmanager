/**
 * Module: components/ActionMenu
 *
 * A small kebab ("more actions") trigger that reveals a short menu of related, non-primary actions: the "one
 * door" shape of style guide Principle 11, for secondary actions that would otherwise sit on screen as separate
 * buttons competing for the same row. See `docs/ux-style-guide.md`'s "Pattern: action menu".
 *
 * Design notes:
 * - `Popover` is the anchored, focus-trapped container (`dialogA11y.ts`), as in `SplitButtonTrigger`. It closes
 *   on a click outside (including a diagram canvas), on Escape and on Tab.
 * - `RecordHeader` uses this menu for the record's object actions even when there is only one (style guide
 *   "Pattern: record header and object actions"), so the position never changes with permissions.
 * - `role="menu"` on the menu container and `role="menuitem"` on each row, nested inside `Popover`'s
 *   `role="dialog"`, so other `Popover` callers do not inherit menu semantics.
 * - A row is a plain text row (class `menu-item`), not a `btn`: no border or fill at rest, a tint on hover and
 *   focus, danger as coloured text.
 * - A menu with more than one level is a tree, not a flat list or a side flyout: an item with `children`, or a
 *   run of more than one item with the same `group`, is a parent row (chevron, `aria-expanded`) that expands in
 *   place, its rows in a labelled `role="group"` under a guide line, to three levels. A group holding one item
 *   stays a heading; a menu with neither stays flat. The first parent starts open.
 * - Keys: Up/Down/Home/End move through the visible rows; Right on a parent opens it and moves to its first
 *   row; Left closes an open parent, or the level the focus is in, and returns to its parent; Escape closes the
 *   level the focus is in, or the menu when the focus is not in a level; Enter, Space and a click open or close
 *   a parent; Tab closes the menu.
 */
import type { ReactNode } from "react";
import { ChevronRight, MoreVertical } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState } from "react";
import type { DragEvent, KeyboardEvent } from "react";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

export interface ActionMenuItem {
  /** Visible label and accessible name for this menu item. */
  label: ReactNode;
  /** Decorative icon shown before `label` — not repeated in the accessible name. */
  icon?: ReactNode;
  onSelect: () => void;
  /** Greys the item out and ignores a click; `title` should say why. */
  disabled?: boolean;
  /** Marks a destructive action (Archive, Delete permanently) with the danger outline. */
  danger?: boolean;
  /** Stable identity when `label` isn't a plain string; defaults to the
   * string label. Never relies on position, since the item list can change
   * while the menu is open. */
  key?: string;
  /** Items of one group sit together. A run of several becomes a parent row named for the group; a single item keeps
   * the group's name as a heading above it. */
  group?: string;
  /** Muted words after the label, part of the item's name ("CSV re-imports"). */
  hint?: string;
  /** Tooltip, e.g. the full name of an acronym label. */
  title?: string;
  /** Makes the item draggable: called when a drag starts, to set the data a drop target reads (a palette-style menu whose
   * entries can also be dropped on a canvas). The menu closes when the drag ends, not when it starts, so the source stays
   * mounted for the whole drag. Ignored on a submenu item and on a disabled one. */
  onDragStart?: (event: DragEvent<HTMLButtonElement>) => void;
  /** Makes this item a parent: it expands in place to show these items (to three levels in all; a third-level item's
   * own `children` are ignored) instead of acting itself, so its own `onSelect` is not called. */
  children?: ActionMenuItem[];
}

/** Levels of a menu tree: a group, an item with children, and the items under it. */
const MAX_LEVELS = 3;

/** A row of the menu as drawn: a leaf (an action), a parent that expands, or a heading over a lone grouped item. */
type MenuNode =
  | { kind: "leaf"; key: string; item: ActionMenuItem }
  | { kind: "parent"; key: string; label: ReactNode; name: string; icon?: ReactNode; children: MenuNode[] }
  | { kind: "heading"; key: string; label: string };

const itemKeyOf = (item: ActionMenuItem, index: number): string =>
  item.key ?? (typeof item.label === "string" ? item.label : String(index));

/**
 * Renders a `MoreVertical` kebab button; clicking it opens a `Popover` (anchored to the kebab) containing `items`
 * as `role="menuitem"` rows. Selecting an item closes the menu and then calls its `onSelect`.
 *
 * @param triggerLabel - Accessible name (`aria-label`/`title`) for the kebab trigger, and the menu's
 *   `aria-label`/`Popover` title. Names what the menu acts on (e.g. `` `${org.name} actions` ``), not a bare
 *   "More actions" (Principle 8), since several menus can appear on one page.
 * @param items - The menu's rows, in display order.
 * @param disabled - Disables the trigger itself (e.g. while one of the
 *   menu's own actions, such as an export, is already in flight).
 * @param footer - Muted text under the items.
 * @param icon - The trigger's picture in place of the kebab.
 * @param triggerText - A word beside the icon, for a trigger that must say what it opens.
 * @param size - `sm` for a trigger that sits beside a field's title (the placeholder menu); `md` (default) otherwise.
 */
export function ActionMenu({
  triggerLabel,
  items,
  disabled,
  footer,
  icon,
  size = "md",
  triggerText,
}: {
  triggerLabel: string;
  items: ActionMenuItem[];
  disabled?: boolean;
  /** Muted text under the items (a note that applies to the whole menu). */
  footer?: ReactNode;
  /** The trigger's picture when the menu is about one thing (Snippets) and not "more actions"; the kebab when omitted. */
  icon?: ReactNode;
  size?: "sm" | "md";
  /** A word shown beside the icon ("+ Field") for a trigger that must say what it opens; the accessible name stays `triggerLabel`. */
  triggerText?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <Tooltip label={triggerLabel} disabled={open || !!triggerText}>
        <button
          ref={triggerRef}
          type="button"
          className={`btn${size === "sm" ? " btn-sm" : ""}${triggerText ? "" : " btn-icon"}`}
          aria-label={triggerLabel}
          aria-haspopup="menu"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
        >
          {icon ?? <MoreVertical />}
          {triggerText && <span style={{ marginLeft: "var(--space-1)" }}>{triggerText}</span>}
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} fit menu title={triggerLabel} onClose={() => setOpen(false)}>
          <ActionMenuList label={triggerLabel} items={items} footer={footer} onSelect={() => setOpen(false)} />
        </Popover>
      )}
    </>
  );
}

/**
 * Turns the items into the rows drawn: an item with `children` and a run of several items sharing a `group` become
 * parents (down to `MAX_LEVELS`), a lone grouped item keeps its group as a heading, anything else is a leaf.
 *
 * @param items - The items of one level, in display order.
 * @param level - 1 for the menu's own items; a group is only formed there.
 * @param prefix - The parent's key, so a row's key is unique across the whole tree.
 * @returns The rows of that level.
 */
function buildNodes(items: ActionMenuItem[], level: number, prefix: string): MenuNode[] {
  const nodes: MenuNode[] = [];
  let i = 0;
  while (i < items.length) {
    const item = items[i];
    const key = `${prefix}${itemKeyOf(item, i)}`;
    if (item.children && item.children.length > 0 && level < MAX_LEVELS) {
      const name = typeof item.label === "string" ? item.label : key;
      nodes.push({ kind: "parent", key, label: item.label, name, icon: item.icon, children: buildNodes(item.children, level + 1, `${key}/`) });
      i += 1;
    } else if (level === 1 && item.group) {
      let end = i;
      while (end < items.length && items[end].group === item.group) end += 1;
      const run = items.slice(i, end).map((member) => ({ ...member, group: undefined }));
      if (run.length > 1) {
        const groupKey = `${prefix}group:${item.group}`;
        nodes.push({ kind: "parent", key: groupKey, label: item.group, name: item.group, children: buildNodes(run, level + 1, `${groupKey}/`) });
      } else {
        nodes.push({ kind: "heading", key: `${key}#heading`, label: item.group }, { kind: "leaf", key, item: run[0] });
      }
      i = end;
    } else {
      nodes.push({ kind: "leaf", key, item });
      i += 1;
    }
  }
  return nodes;
}

/** The key of the first parent at the top level, which starts open so the menu is not a column of closed rows. */
const firstParentKey = (nodes: MenuNode[]): string | undefined => nodes.find((n) => n.kind === "parent")?.key;

/**
 * The `role="menu"` list of items both `ActionMenu` (kebab) and `MenuButton` (labelled button) show in
 * their `Popover`. Selecting an item calls `onSelect` (the caller closes the popover) and then the item's
 * own `onSelect`; Tab calls `onSelect` alone, which closes the menu.
 *
 * @param label - The menu's accessible name.
 * @param items - The rows, in display order.
 * @param onSelect - Called first when any item is chosen, and when Tab leaves the menu.
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
  const rootRef = useRef<HTMLDivElement>(null);
  const nodes = buildNodes(items, 1, "");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set(firstParentKey(nodes) ? [firstParentKey(nodes) as string] : []));
  const focusInto = useRef<string | null>(null);

  function setOpen(key: string, open: boolean) {
    setExpanded((current) => {
      const next = new Set(current);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  /** Moves focus to the first row of a parent's group, which must be in the document. */
  function focusFirstRowOf(parentKey: string) {
    const group = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-group-key]") ?? []).find((g) => g.dataset.groupKey === parentKey);
    group?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus();
  }

  // After a key opens a parent, its first row takes focus once the group is in the document.
  useEffect(() => {
    if (focusInto.current === null) return;
    focusFirstRowOf(focusInto.current);
    focusInto.current = null;
  }, [expanded]);

  /** The menu keys (see the module comment). Events from outside a row (the footer) are ignored. */
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const target = e.target as HTMLElement;
    if (target.getAttribute("role") !== "menuitem") return;
    if (e.key === "Tab") {
      e.preventDefault();
      onSelect();
      return;
    }
    const rows = Array.from(rootRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') ?? []);
    const at = rows.indexOf(target);
    const move = (to: number) => {
      e.preventDefault();
      rows[(to + rows.length) % rows.length]?.focus();
    };
    const group = target.closest<HTMLElement>("[data-group-key]");
    const parentKey = target.dataset.parentKey;
    const isOpenParent = parentKey !== undefined && target.getAttribute("aria-expanded") === "true";
    /** Closes the level the focus is in and returns to its parent row; true when there was one to close. */
    const closeLevel = (closeOpenParent: boolean): boolean => {
      if (closeOpenParent && isOpenParent && parentKey !== undefined) {
        setOpen(parentKey, false);
        return true;
      }
      if (!group?.dataset.groupKey) return false;
      setOpen(group.dataset.groupKey, false);
      Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-parent-key]") ?? []).find((p) => p.dataset.parentKey === group.dataset.groupKey)?.focus();
      return true;
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(rows.length - 1);
    else if (e.key === "ArrowRight" && parentKey !== undefined) {
      e.preventDefault();
      if (isOpenParent) focusFirstRowOf(parentKey);
      else {
        focusInto.current = parentKey;
        setOpen(parentKey, true);
      }
    } else if ((e.key === "ArrowLeft" || e.key === "Escape") && closeLevel(e.key === "ArrowLeft")) {
      // Only the level closes: stopping the event keeps the dialog's own Escape handler from closing the menu too.
      e.preventDefault();
      e.stopPropagation();
    }
  }

  return (
    <div ref={rootRef} role="menu" aria-label={label} className="menu-list" onKeyDown={onKeyDown}>
      <MenuRows nodes={nodes} expanded={expanded} onToggle={(key) => setOpen(key, !expanded.has(key))} onSelect={onSelect} />
      {footer && <span role="presentation" className="menu-footer text-muted">{footer}</span>}
    </div>
  );
}

/**
 * Draws one level of the menu: leaves as text rows, headings, and each parent as a row with its children in a
 * labelled group beneath it while it is open.
 *
 * @param nodes - The rows of this level.
 * @param expanded - The keys of the parents that are open.
 * @param onToggle - Called with a parent's key when its row is clicked.
 * @param onSelect - Called first when a leaf is chosen.
 */
function MenuRows({
  nodes, expanded, onToggle, onSelect,
}: {
  nodes: MenuNode[];
  expanded: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onSelect: () => void;
}) {
  const idPrefix = useId();
  return (
    <>
      {nodes.map((node) => {
        // Keyed by label, not index: a caller's item list can change while the menu is open (Org Admin adds
        // "Rename" once its settings load), and an index key would hand one item's button and click handler
        // to another.
        if (node.kind === "heading") return <span key={node.key} role="presentation" className="menu-group-label">{node.label}</span>;
        if (node.kind === "leaf") {
          const { item } = node;
          return (
            <button
              key={node.key}
              type="button"
              role="menuitem"
              className={item.danger ? "menu-item menu-item-danger" : "menu-item"}
              title={item.title}
              disabled={item.disabled}
              draggable={item.onDragStart !== undefined && !item.disabled}
              onDragStart={item.onDragStart}
              onDragEnd={item.onDragStart ? onSelect : undefined}
              onClick={() => {
                onSelect();
                item.onSelect();
              }}
            >
              {item.icon} {item.label}
              {item.hint && <span className="text-muted menu-item-hint">{item.hint}</span>}
            </button>
          );
        }
        const isOpen = expanded.has(node.key);
        const groupId = `${idPrefix}-${node.key.replace(/\s+/g, "_")}`;
        return (
          <Fragment key={node.key}>
            <button
              type="button"
              role="menuitem"
              className="menu-item menu-parent"
              aria-expanded={isOpen}
              aria-controls={isOpen ? groupId : undefined}
              data-parent-key={node.key}
              onClick={() => onToggle(node.key)}
            >
              {node.icon} {node.label}
              <ChevronRight aria-hidden="true" size={14} className="menu-parent-chevron" />
            </button>
            {isOpen && (
              <div id={groupId} role="group" aria-label={node.name} className="menu-tree-group" data-group-key={node.key}>
                <MenuRows nodes={node.children} expanded={expanded} onToggle={onToggle} onSelect={onSelect} />
              </div>
            )}
          </Fragment>
        );
      })}
    </>
  );
}
