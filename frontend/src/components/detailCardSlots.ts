/**
 * Module: components/detailCardSlots
 *
 * The mount point a `DetailCard` exposes on its heading's line (see `CardHeaderAction.tsx`). Kept apart from the components so the
 * context object and hook are not mixed with component exports.
 */
import { createContext, useContext } from "react";

/** The heading line's actions element; `null` until the card has rendered, and outside any card. */
export const DetailCardActionsContext = createContext<HTMLElement | null>(null);

/**
 * The heading-line mount point of the nearest `DetailCard`.
 *
 * @returns The element, or `null` outside a card (the caller then renders inline).
 */
export function useDetailCardActions(): HTMLElement | null {
  return useContext(DetailCardActionsContext);
}
