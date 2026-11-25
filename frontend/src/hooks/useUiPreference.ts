import type { UiPreferenceValue } from "../api/types";
import { useAuth } from "../context/AuthContext";

/**
 * Generic read/write access to one key in the current user's `ui_preferences` bag (`User.ui_preferences` on the
 * backend), the key/value store for low-stakes UI display preferences (view mode, nav-rail collapse,
 * collapsible-section state) that need no dedicated field. `useAuth()`'s `user` is the single source of truth, so a
 * change made anywhere is reflected everywhere the same key is read. Values may be any JSON
 * (`UiPreferenceValue`); callers storing structured data must validate what they read, since the bag is open-ended.
 */
export function useUiPreference<T extends UiPreferenceValue>(key: string, defaultValue: T): [T, (value: T) => void] {
  const { user, setUiPreference } = useAuth();
  const stored = user?.ui_preferences[key];
  const value = (stored === undefined ? defaultValue : (stored as T));

  function setValue(next: T) {
    setUiPreference(key, next);
  }

  return [value, setValue];
}
