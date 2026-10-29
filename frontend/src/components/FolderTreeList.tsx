/**
 * Module: components/FolderTreeList
 *
 * The one folder-and-items list, drawn like a file manager's list view: a header row with a sortable Name column
 * (and any further columns to its right), one row per folder or item, a disclosure chevron and folder icon on each
 * folder, a type icon on each item, children indented under their folder and banded rows.
 *
 * Responsibilities:
 * - Show the tree `utils/reportFolders` builds, generic over the item type, so the report chooser and the
 *   report setup list share one implementation of the shape.
 * - Sort each level by the Name column or a column that declares a `sortValue`: folders always come first, then
 *   items; a node marked `pinned` (Favourites) stays on top.
 * - Keyboard (an ARIA tree grid): Up/Down/Home/End move between visible rows, Right opens a folder (or moves to its
 *   first child), Left closes it (or moves to its parent), Enter opens an item or toggles a folder.
 * - Name an empty open folder with a muted "Empty folder" row, so an open folder never looks broken.
 *
 * Design decisions: expansion is controlled by the caller (`expanded` / `onToggle`), as `TreeView`'s controlled mode
 * is, because the chooser opens every folder while a search is active and persists the person's own layout; the
 * folder's chevron, icon and name are one button named "Expand X" / "Collapse X" so the whole label is the click
 * target and a folder has one control, and an item's type icon sits outside the item's button so the button's name
 * stays the item's title; a folder's row can carry trailing controls (`renderFolderActions`) as an item's does. Pure presentation: the data, the selection and every action stay with the caller. A column
 * with `hideBelow` is dropped under 640px (the Name column wraps instead of clipping).
 *
 * Dependencies: `utils/reportFolders` (`FolderNode`), `lucide-react`, the `.folder-tree-*` rules in `theme.css`.
 */
import { ChevronDown, ChevronRight, ChevronUp, Folder, FolderOpen } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { FolderNode } from "../utils/reportFolders";
import { Badge } from "./Badge";

/** A column to the right of Name. */
export interface FolderTreeColumn<T> {
  id: string;
  header: string;
  /** The cell for an item (a folder's cell is empty). */
  render: (item: T) => ReactNode;
  /** Makes the header sortable by this value (numbers sort numerically, text without regard to case). */
  sortValue?: (item: T) => string | number;
  /** A CSS width for the column (default `minmax(6rem, 10rem)`). */
  width?: string;
  /** Drop the column under 640px, where the row has no room for it. */
  hideBelow?: boolean;
}

/** What an item's row shows besides its name. */
export interface FolderTreeItemView {
  /** The type icon (decorative; `iconLabel` names it). */
  icon: ReactNode;
  /** The type in words, the icon's accessible name and tooltip. */
  iconLabel: string;
  /** A muted second line under the name. */
  description?: string;
}

/** A visible row: a node with where it sits in the tree. */
interface Row<T> {
  node: FolderNode<T>;
  depth: number;
  parentId: string | null;
  position: number;
  setSize: number;
  /** An open folder with nothing in it. */
  emptyOpen?: boolean;
}

type SortState = { column: "name" | string; descending: boolean };

function compare(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
}

/** Sorts one level: pinned folders, then folders by name, then items by the chosen column. */
function sortLevel<T>(nodes: FolderNode<T>[], sort: SortState, columns: FolderTreeColumn<T>[]): FolderNode<T>[] {
  const column = columns.find((c) => c.id === sort.column);
  const direction = sort.descending ? -1 : 1;
  const rank = (n: FolderNode<T>) => (n.pinned ? 0 : n.kind === "folder" ? 1 : 2);
  return [...nodes].sort((a, b) => {
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    if (a.pinned) return 0;
    if (a.kind === "folder") return direction * compare(a.name, b.name);
    const by = column?.sortValue && a.item !== undefined && b.item !== undefined
      ? compare(column.sortValue(a.item), column.sortValue(b.item))
      : compare(a.name, b.name);
    return direction * by || compare(a.name, b.name);
  });
}

function flatten<T>(
  nodes: FolderNode<T>[], expanded: ReadonlySet<string>, sort: SortState, columns: FolderTreeColumn<T>[],
  depth = 0, parentId: string | null = null,
): Row<T>[] {
  const sorted = sortLevel(nodes, sort, columns);
  return sorted.flatMap((node, index) => {
    const row: Row<T> = { node, depth, parentId, position: index + 1, setSize: sorted.length };
    if (node.kind !== "folder" || !expanded.has(node.id)) return [row];
    if (node.children.length === 0) return [row, { ...row, node: { ...node, id: `${node.id}:empty` }, depth: depth + 1, parentId: node.id, emptyOpen: true }];
    return [row, ...flatten(node.children, expanded, sort, columns, depth + 1, node.id)];
  });
}

/**
 * @param nodes The tree to show (`buildFolderTree`'s output, or any `FolderNode` tree).
 * @param label Names the grid for assistive technology.
 * @param expanded The ids of the open folders.
 * @param onToggle Called with a folder's id and whether it should now be open.
 * @param itemView The icon, icon name and description of an item's row.
 * @param onOpenItem Called when an item's name is activated.
 * @param isSelected Whether an item is the chosen one (highlighted, `aria-current`).
 * @param columns Further columns to the right of Name.
 * @param renderItemActions The trailing controls of an item's row (a favourite star), after the last column.
 * @param renderFolderActions The trailing controls of a folder's row (the setup list's New folder, Rename and Delete).
 * @param folderBadge The small count shown beside a folder's name.
 * @param emptyText Shown instead of the grid when there is nothing to list.
 */
export function FolderTreeList<T>({
  nodes, label, expanded, onToggle, itemView, onOpenItem, isSelected, columns = [], renderItemActions, renderFolderActions, folderBadge, emptyText,
}: {
  nodes: FolderNode<T>[];
  label: string;
  expanded: ReadonlySet<string>;
  onToggle: (id: string, open: boolean) => void;
  itemView: (item: T) => FolderTreeItemView;
  onOpenItem: (item: T) => void;
  isSelected?: (item: T) => boolean;
  columns?: FolderTreeColumn<T>[];
  renderItemActions?: (item: T) => ReactNode;
  renderFolderActions?: (node: FolderNode<T>) => ReactNode;
  folderBadge?: (node: FolderNode<T>) => string;
  emptyText?: string;
}) {
  const text = useStrings().folderTreeList;
  const [sort, setSort] = useState<SortState>({ column: "name", descending: false });
  const [activeId, setActiveId] = useState<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => flatten(nodes, expanded, sort, columns), [nodes, expanded, sort, columns]);
  const focusable = rows.filter((r) => !r.emptyOpen);
  const tabStop = focusable.find((r) => r.node.id === activeId)?.node.id ?? focusable[0]?.node.id;
  const hasActions = Boolean(renderItemActions || renderFolderActions);
  const template = `minmax(0, 1fr) ${columns.map((c) => c.width ?? "minmax(6rem, 10rem)").join(" ")} ${hasActions ? "auto" : ""}`;

  if (focusable.length === 0 && emptyText) return <p className="text-muted">{emptyText}</p>;

  function rowElement(id: string): HTMLElement | null {
    return grid.current?.querySelector<HTMLElement>(`[data-ftl-row="${CSS.escape(id)}"]`) ?? null;
  }
  function focusRow(id: string | undefined) {
    if (!id) return;
    setActiveId(id);
    rowElement(id)?.focus();
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const target = (event.target as HTMLElement).closest<HTMLElement>("[data-ftl-row]");
    if (!target) return;
    const id = target.dataset.ftlRow as string;
    const index = focusable.findIndex((r) => r.node.id === id);
    const row = focusable[index];
    const onRow = event.target === target;
    if (!row) return;
    const isFolder = row.node.kind === "folder";
    const open = isFolder && expanded.has(row.node.id);
    switch (event.key) {
      case "ArrowDown":
        focusRow(focusable[Math.min(index + 1, focusable.length - 1)].node.id);
        break;
      case "ArrowUp":
        focusRow(focusable[Math.max(index - 1, 0)].node.id);
        break;
      case "Home":
        focusRow(focusable[0].node.id);
        break;
      case "End":
        focusRow(focusable[focusable.length - 1].node.id);
        break;
      case "ArrowRight":
        if (isFolder && !open) onToggle(row.node.id, true);
        else if (isFolder && focusable[index + 1]?.parentId === row.node.id) focusRow(focusable[index + 1].node.id);
        break;
      case "ArrowLeft":
        if (isFolder && open) onToggle(row.node.id, false);
        else if (row.parentId) focusRow(row.parentId);
        break;
      case "Enter":
        // On a button inside the row, Enter is that button's own click.
        if (!onRow) return;
        if (isFolder) onToggle(row.node.id, !open);
        else if (row.node.item !== undefined) onOpenItem(row.node.item);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  function sortBy(column: string) {
    setSort((current) => (current.column === column ? { column, descending: !current.descending } : { column, descending: false }));
  }
  const ariaSort = (column: string) => (sort.column === column ? (sort.descending ? "descending" : "ascending") : "none");

  return (
    <div ref={grid} className="folder-tree-list" role="treegrid" aria-label={label} onKeyDown={onKeyDown}>
      <div role="row" className="folder-tree-header" style={{ gridTemplateColumns: template }}>
        <div role="columnheader" aria-sort={ariaSort("name")}>
          <SortButton label={text.nameHeader} active={sort.column === "name"} descending={sort.descending} onClick={() => sortBy("name")} />
        </div>
        {columns.map((c) => (
          <div key={c.id} role="columnheader" aria-sort={c.sortValue ? ariaSort(c.id) : undefined} className={c.hideBelow ? "folder-tree-wide" : undefined}>
            {c.sortValue ? <SortButton label={c.header} active={sort.column === c.id} descending={sort.descending} onClick={() => sortBy(c.id)} /> : c.header}
          </div>
        ))}
        {hasActions && <div role="columnheader"><span className="sr-only">{text.actionsHeader}</span></div>}
      </div>
      {rows.map((row, visibleIndex) => {
        const { node, depth } = row;
        const band = visibleIndex % 2 === 1 ? " folder-tree-band" : "";
        const indent = { paddingInlineStart: `calc(var(--space-3) + ${depth} * 1.25rem)` };
        if (row.emptyOpen) {
          return (
            <div key={node.id} role="row" aria-level={depth + 1} className={`folder-tree-row${band}`} style={{ gridTemplateColumns: template }}>
              <div role="gridcell" className="text-muted folder-tree-empty" style={indent}>{text.emptyFolder}</div>
            </div>
          );
        }
        const common = {
          role: "row" as const,
          "data-ftl-row": node.id,
          "aria-level": depth + 1,
          "aria-posinset": row.position,
          "aria-setsize": row.setSize,
          tabIndex: node.id === tabStop ? 0 : -1,
          onFocus: () => setActiveId(node.id),
          style: { gridTemplateColumns: template },
        };
        if (node.kind === "folder") {
          const open = expanded.has(node.id);
          const Icon = open ? FolderOpen : Folder;
          return (
            <div key={node.id} {...common} aria-expanded={open} className={`folder-tree-row folder-tree-folder${band}`}>
              <div role="gridcell" className="folder-tree-name" style={indent}>
                <button
                  type="button" className="folder-tree-toggle" tabIndex={-1} aria-expanded={open}
                  aria-label={text.toggle(node.name, open)} title={text.toggle(node.name, open)}
                  onClick={() => onToggle(node.id, !open)}
                >
                  {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
                  <Icon aria-hidden="true" className="folder-tree-folder-icon" />
                  <strong>{node.name}</strong>
                </button>
                {folderBadge && <Badge>{folderBadge(node)}</Badge>}
              </div>
              {columns.map((c) => <div key={c.id} role="gridcell" className={c.hideBelow ? "folder-tree-wide" : undefined} />)}
              {hasActions && <div role="gridcell">{renderFolderActions?.(node)}</div>}
            </div>
          );
        }
        const item = node.item as T;
        const view = itemView(item);
        const selected = isSelected?.(item) ?? false;
        return (
          <div key={node.id} {...common} aria-selected={selected} className={`folder-tree-row${band}${selected ? " folder-tree-selected" : ""}`}>
            <div role="gridcell" className="folder-tree-name" style={indent}>
              <span className="folder-tree-chevron-gap" aria-hidden="true" />
              <span role="img" aria-label={view.iconLabel} title={view.iconLabel} className="folder-tree-type-icon">{view.icon}</span>
              <button
                type="button" className="folder-tree-item" tabIndex={-1} data-report-picker-item=""
                aria-current={selected ? "true" : undefined} onClick={() => onOpenItem(item)}
              >
                <span className="stack" style={{ gap: 0 }}>
                  <span>{node.name}</span>
                  {view.description && <span className="text-muted folder-tree-description">{view.description}</span>}
                </span>
              </button>
            </div>
            {columns.map((c) => (
              <div key={c.id} role="gridcell" className={c.hideBelow ? "folder-tree-wide" : undefined}>{c.render(item)}</div>
            ))}
            {hasActions && <div role="gridcell">{renderItemActions?.(item)}</div>}
          </div>
        );
      })}
    </div>
  );
}

function SortButton({ label, active, descending, onClick }: { label: string; active: boolean; descending: boolean; onClick: () => void }) {
  const text = useStrings().folderTreeList;
  return (
    <button type="button" className="th-sort" onClick={onClick} title={text.sortBy(label)}>
      {label}
      {active && (descending ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />)}
    </button>
  );
}
