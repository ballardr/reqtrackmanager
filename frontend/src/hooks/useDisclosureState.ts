import { useUiPreference } from "./useUiPreference";

/** Rows remembered per list; the oldest choice is dropped past it, so the preference bag stays bounded. */
const MAX_REMEMBERED = 50;

/**
 * Per-viewer open/closed state for the rows of one list (`DisclosureRow`), kept in the user's `ui_preferences` bag
 * under a single key per list. Only the rows whose state differs from `defaultCollapsed` are stored, so a list of any
 * length costs a handful of ids rather than one preference key per row (the bag is capped at a few hundred keys).
 *
 * @param listKey Stable name of the list, for example `stageWorkflows:project`.
 * @param defaultCollapsed Whether a row nobody has toggled is closed; a stored toggle always reverses the current
 *   default, so a list whose default changes (one item, then several) keeps each person's reversals.
 * @returns `isCollapsed(id)` and `toggle(id)`.
 */
export function useDisclosureState(listKey: string, defaultCollapsed: boolean) {
  const [stored, setStored] = useUiPreference<string[]>(`disclosure_toggled:${listKey}`, []);
  const toggled = Array.isArray(stored) ? stored : [];

  return {
    isCollapsed: (id: string): boolean => (toggled.includes(id) ? !defaultCollapsed : defaultCollapsed),
    toggle: (id: string) => {
      const next = toggled.includes(id) ? toggled.filter((other) => other !== id) : [...toggled, id];
      setStored(next.slice(-MAX_REMEMBERED));
    },
  };
}
