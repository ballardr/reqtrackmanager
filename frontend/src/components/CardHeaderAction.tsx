/**
 * Module: components/CardHeaderAction
 *
 * Puts an action (a Save button, say) on the heading line of the `DetailCard` it is rendered in, beside the card's title, the way a
 * form's actions sit in its dialog's header (`FormActions`): reachable without scrolling however long the card is. The component
 * owning the draft renders it where its fields are; the button appears in the header. Outside a card, or before the card's header has
 * rendered, the children are drawn in place.
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
