/**
 * Module: components/dialogSlots
 *
 * The header mount points a `Modal` / `SidePanel` exposes to `FormActions` (see `DialogHeader.tsx`).
 * Kept apart from the components so the context object and hook are not mixed with component exports.
 * A `Popover` provides `null`, so a form inside it keeps its buttons inline.
 */
import { createContext, useContext } from "react";

/** The header's mount points; an element is `null` until the header has rendered. */
export interface DialogSlots {
  actions: HTMLElement | null;
  error: HTMLElement | null;
}

export const DialogSlotContext = createContext<DialogSlots | null>(null);

/**
 * The header slots of the nearest dialog.
 *
 * @returns The slots, or `null` outside a dialog (and inside a `Popover`), where the caller renders inline.
 */
export function useDialogSlots(): DialogSlots | null {
  return useContext(DialogSlotContext);
}
