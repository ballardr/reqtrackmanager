/**
 * Module: components/ItemRowList
 *
 * A compact, flat list of editable items: one row per item with its name (and a muted detail), then the item's
 * actions on the right (move, settings, remove). It fits "an ordered set of things, each with a few rarely used
 * settings" (the columns of a table or sheet), where the settings sit behind a gear (`SettingsPopoverButton`).
 *
 * Pure presentation, as `RemovableItemList`: the caller owns data and actions. The name wraps rather than
 * truncating, and a row with no name yet shows the caller's placeholder in muted text.
 */
import type { ReactNode } from "react";

export interface ItemRow {
  /** Stable key for the row. */
  id: string;
  /** What the row is called; empty shows `emptyName`. */
  name: string;
  /** A muted second part after the name, e.g. the field's code. */
  detail?: ReactNode;
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
        <li key={item.id} className="item-list-row">
          <span className="item-list-row__name">
            {item.name !== "" ? item.name : <span className="text-muted">{emptyName}</span>}
            {item.detail && (
              typeof item.detail === "string" ? (
                <span className="text-muted item-list-row__detail"> {item.detail}</span>
              ) : (
                <span className="text-muted item-list-row__detail" style={{ display: "inline-flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center", marginLeft: "var(--space-2)" }}>
                  {item.detail}
                </span>
              )
            )}
          </span>
          {item.actions && <span className="item-list-row__actions">{item.actions}</span>}
        </li>
      ))}
    </ul>
  );
}
