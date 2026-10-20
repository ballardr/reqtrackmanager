/**
 * Module: components/detailAsideContext
 *
 * Tells a panel it is drawn inside `DetailLayout`'s aside card. The aside is one card whose tab strip
 * (or single "Links" heading) is its title, so a panel inside it draws no card and no title of its own
 * (`ArtefactLinksPanel` is the one that does today). It is a context, not a prop, so a detail page
 * passes its panel as it always did and a panel used elsewhere (a card of its own, or inside another
 * record's card) is unaffected.
 */
import { createContext, useContext } from "react";

const DetailAsideContext = createContext(false);

/** Wraps the aside's content; panels below it read `useInDetailAside()`. */
export const DetailAsideProvider = DetailAsideContext.Provider;

/** True when the calling panel is rendered inside a `DetailLayout` aside card. */
export function useInDetailAside(): boolean {
  return useContext(DetailAsideContext);
}
