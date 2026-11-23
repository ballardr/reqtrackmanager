/**
 * Module: components/CappedList
 *
 * Caps a list that can grow without bound at a screenful (10 by default) and puts the rest behind a "Show all N"
 * button opening a scrolling `Modal` (docs/ux-style-guide.md, "Pattern: compact forms and add-on-demand"). The
 * caller's `renderList` draws both the inline and the modal copy, so any per-item action works in either.
 */
import { useState, type ReactNode } from "react";

import { Modal } from "./Modal";

/** How many items show before the rest move behind "Show all". */
export const DEFAULT_LIST_CAP = 10;

/**
 * @param items The full list.
 * @param renderList Renders a list of items (the first `limit`, or all of them in the modal).
 * @param noun What the items are, plural, for the button: "Show all 14 participants".
 * @param modalTitle Title of the modal that holds the full list.
 * @param limit How many items to show inline.
 */
export function CappedList<T>({
  items,
  renderList,
  noun,
  modalTitle,
  limit = DEFAULT_LIST_CAP,
}: {
  items: T[];
  renderList: (items: T[]) => ReactNode;
  noun: string;
  modalTitle: string;
  limit?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  if (items.length <= limit) return <>{renderList(items)}</>;
  return (
    <>
      {renderList(items.slice(0, limit))}
      <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setShowAll(true)}>
        Show all {items.length} {noun}
      </button>
      {showAll && (
        <Modal title={modalTitle} onClose={() => setShowAll(false)}>
          <div className="stack">{renderList(items)}</div>
        </Modal>
      )}
    </>
  );
}
