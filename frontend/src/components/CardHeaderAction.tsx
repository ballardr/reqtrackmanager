/**
 * Module: components/CardHeaderAction
 *
 * Puts an action (a Save button) on the heading line of the `DetailCard` it is rendered in, as a form's actions
 * sit in its dialog header (`FormActions`): reachable however long the card is. The component owning the draft
 * renders it where its fields are. Outside a card, or before the header has rendered, the children draw in place.
 */
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { useDetailCardActions } from "./detailCardSlots";

/**
 * @param children The action to show on the card's heading line.
 */
export function CardHeaderAction({ children }: { children: ReactNode }) {
  const slot = useDetailCardActions();
  return slot ? createPortal(children, slot) : <>{children}</>;
}
