import { useAuth } from "../context/AuthContext";

/**
 * Generic read/write access to one key in the current user's
 * `ui_preferences` bag (`User.ui_preferences` on the backend) — the
 * general-purpose key/value store for lightweight, low-stakes UI display
 * preferences (tile/list view mode, nav-rail collapse, collapsible-section
 * state, and whatever similar preference comes next) that don't warrant
 * their own dedicated field. `useAuth()`'s `user` is the single source of
 * truth; there's no separate local state to keep in sync with it, so a
 * change made anywhere is reflected everywhere this hook reads that same
 * key, instantly.
 */
export function useUiPreference<T extends string | boolean>(key: string, defaultValue: T): [T, (value: T) => void] {
  const { user, setUiPreference } = useAuth();
  const stored = user?.ui_preferences[key];
  const value = (stored === undefined ? defaultValue : (stored as T));

  function setValue(next: T) {
    setUiPreference(key, next);
  }

  return [value, setValue];
}
