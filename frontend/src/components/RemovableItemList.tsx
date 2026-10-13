/**
 * Module: components/RemovableItemList
 *
 * A wrapped row of compact items, each with a small "x" that asks to remove it: the one shape
 * for "these records are linked here" lists (participants, covered Personas, audiences, outcomes)
 * that used to be a bulleted list with a text "Remove" button on every line. Chips take a
 * fraction of the height. The "x" only *asks*: the caller opens its tier-1 confirm
 * (docs/ux-style-guide.md "confirmation, in two tiers") and does the removal. A long list is
 * capped by `CappedList`.
 */
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { CappedList } from "./CappedList";

export interface RemovableItem {
  id: string;
  /** What the chip shows: a name, a link. */
  content: ReactNode;
  /** The name of the remove button, e.g. "Remove Dana Whitfield". */
  removeLabel: string;
}

/**
 * @param items The items to show.
 * @param onRemove Called with the item whose "x" was pressed; omit for a read-only list.
 * @param noun Plural noun for the "Show all" button, e.g. "participants".
 * @param modalTitle Title of the full-list modal.
 */
export function RemovableItemList({
  items,
  onRemove,
  noun,
  modalTitle,
}: {
  items: RemovableItem[];
  onRemove?: (id: string) => void;
  noun: string;
  modalTitle: string;
}) {
  return (
    <CappedList
      items={items}
      noun={noun}
      modalTitle={modalTitle}
      renderList={(shown) => (
        <ul className="removable-list">
          {shown.map((item) => (
            <li key={item.id} className="removable-item">
              {item.content}
              {onRemove && (
                <button type="button" className="removable-item__remove" aria-label={item.removeLabel} title={item.removeLabel} onClick={() => onRemove(item.id)}>
                  <X size={12} aria-hidden="true" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    />
  );
}
