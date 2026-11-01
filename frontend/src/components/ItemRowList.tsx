/**
 * Module: components/ItemRowList
 *
 * A compact, flat list of editable items: one row per item with its name (and a muted detail), then the item's
 * actions on the right (move, settings, remove). It is the shape for "an ordered set of things, each with a few
 * rarely used settings" (the columns of a table, sheet or custom table), where the settings sit behind a gear
 * (`SettingsPopoverButton`) instead of being drawn inline for every row.
 *
 * Design decisions: pure presentation, as `RemovableItemList` is; the caller owns the data and the actions, so
 * the rows stay identical whatever they list. The name wraps rather than truncating so a long heading stays
 * readable, and a row with nothing to name yet shows the caller's placeholder in muted text.
 */
import type { ReactNode } from "react";

export interface ItemRow {
  /** Stable key for the row. */
  id: string;
  /** What the row is called; empty shows `emptyName`. */
  name: string;
  /** A muted second part after the name, e.g. the field's code. */
  detail?: string;
  /** The row's controls, drawn right-aligned. */
  actions?: ReactNode;
}

/**
 * @param items The rows, in order.
 * @param label Accessible name of the list.
 * @param emptyName Muted text for a row whose name is empty (e.g. "Choose a field").
 */
export function ItemRowList({ items, label, emptyName }: { items: ItemRow[]; label: string; emptyName: string }) {
  return (
    <ul className="item-row-list" aria-label={label}>
      {items.map((item) => (
        <li key={item.id} className="item-row">
          <span className="item-row__name">
            {item.name !== "" ? item.name : <span className="text-muted">{emptyName}</span>}
            {item.detail && <span className="text-muted item-row__detail"> {item.detail}</span>}
          </span>
          {item.actions && <span className="item-row__actions">{item.actions}</span>}
        </li>
      ))}
    </ul>
  );
}
