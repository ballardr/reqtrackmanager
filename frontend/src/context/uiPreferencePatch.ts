/**
 * Module: context/uiPreferencePatch
 *
 * Applies a partial `ui_preferences` update the same way the backend merge does
 * (`services/ui_preferences.py`): shallow by top-level key, `null` removes the key. Shared by
 * the real `AuthProvider` (optimistic update) and the Storybook auth providers so a story
 * cannot drift from production behaviour.
 */
import type { UiPreferenceValue } from "../api/types";

/** Returns a new bag with `patch` applied; `current` is not mutated. */
export function applyUiPreferencePatch(
  current: Record<string, UiPreferenceValue>,
  patch: Record<string, UiPreferenceValue | null>,
): Record<string, UiPreferenceValue> {
  const next = { ...current };
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete next[key];
    else next[key] = value;
  }
  return next;
}
