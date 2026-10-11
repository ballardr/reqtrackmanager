/**
 * Module: context/AuthContextValue
 *
 * The `AuthContext` object and its value type, split out of AuthContext.tsx
 * so that file can keep exporting only components/hooks (`AuthProvider`,
 * `useAuth`) — a file mixing component and non-component exports breaks
 * Fast Refresh (react-refresh/only-export-components). Storybook stories
 * import `AuthContext` from here directly to supply a fixture user via
 * `<AuthContext.Provider value={...}>` without round-tripping through real
 * `login()`/`/auth/me` calls.
 */
import { createContext } from "react";

import type { UiPreferenceValue, User } from "../api/types";

export type LoginResult = { requires2fa: false; user: User } | { requires2fa: true; challengeToken: string };

export interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  signup: (email: string, password: string, displayName: string, inviteToken?: string) => Promise<User>;
  verify2fa: (challengeToken: string, code: string) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  /** Sets one `ui_preferences` key; `null` removes it (and persists the removal). */
  setUiPreference: (key: string, value: UiPreferenceValue | null) => void;
  /** Applies several keys in one request (`null` removes) — use when keys must change together,
   * since separate concurrent PATCHes are read-modify-write on the same server-side bag.
   * Applied optimistically; rejects if the server refused it (e.g. the size bound), after the
   * local copy has been re-synced from the server. Callers that report success must await it. */
  setUiPreferences: (patch: Record<string, UiPreferenceValue | null>) => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
