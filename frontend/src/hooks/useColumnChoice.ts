import { useCallback, useMemo } from "react";

import { useAuth } from "../context/AuthContext";

/**
 * Which optional columns of one list a person has chosen to show, remembered per person in `ui_preferences`
 * (`column_choice_<key>`), so the choice follows them between browsers.
 *
 * The stored value is the list of shown column ids; no stored value means the list's defaults. A stored id that
 * is no longer a column (one removed in a later release) is ignored rather than trusted, and a column added
 * later is shown only if the defaults show it.
 *
 * @param key Names the list, e.g. `report_setup_project`.
 * @param allIds Every optional column the list offers now.
 * @param defaultIds The columns shown until the person chooses.
 * @returns `visible` (the shown ids, in `allIds` order), `isDefault`, `toggle(id, shown)` and `reset()`.
 */
export function useColumnChoice(key: string, allIds: readonly string[], defaultIds: readonly string[]) {
  const { user, setUiPreference } = useAuth();
  const prefKey = `column_choice_${key}`;
  const stored = user?.ui_preferences[prefKey];
  const known = useMemo(() => new Set(allIds), [allIds]);
  const chosen = useMemo(
    () => (Array.isArray(stored) ? new Set(stored.filter((id): id is string => typeof id === "string" && known.has(id))) : null),
    [stored, known],
  );
  const visible = useMemo(() => {
    const shown = chosen ?? new Set(defaultIds);
    return allIds.filter((id) => shown.has(id));
  }, [chosen, defaultIds, allIds]);

  const toggle = useCallback(
    (id: string, shown: boolean) => {
      const next = new Set(visible);
      if (shown) next.add(id);
      else next.delete(id);
      setUiPreference(prefKey, allIds.filter((c) => next.has(c)));
    },
    [visible, allIds, prefKey, setUiPreference],
  );
  const reset = useCallback(() => setUiPreference(prefKey, null), [prefKey, setUiPreference]);

  return { visible, isDefault: chosen === null, toggle, reset };
}
