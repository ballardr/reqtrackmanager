/**
 * Module: hooks/useNavGroupActive
 *
 * The channel by which a navigation entry tells the foldable group around it that it is the current page
 * (`components/NavGroup`), so the group can keep that entry visible without knowing what its entries are.
 *
 * `NavRailLink` calls it, so core and module entries report themselves; an entry that is not a `NavRailLink`
 * either calls it too or sets `NavGroup`'s `containsActive`.
 */
import { createContext, useContext, useLayoutEffect } from "react";

/** What an entry inside a group tells it: `markActive` registers one active entry and returns its removal. */
export interface NavGroupContextValue {
  markActive: () => () => void;
}

export const NavGroupContext = createContext<NavGroupContextValue | null>(null);

/**
 * Reports that the calling entry is the current page to the group around it, if there is one.
 *
 * @param active Whether the calling entry is the current page.
 */
export function useNavGroupActive(active: boolean): void {
  const group = useContext(NavGroupContext);
  // Layout effect, so a folded group that holds the page is known before the first paint instead of flashing hidden.
  useLayoutEffect(() => {
    if (!group || !active) return undefined;
    return group.markActive();
  }, [group, active]);
}
