/**
 * Module: context/AuthContextValue
 *
 * The `AuthContext` object and its value type, kept apart from AuthContext.tsx so that file exports only components and
 * hooks (`AuthProvider`, `useAuth`); a file mixing both breaks Fast Refresh (`react-refresh/only-export-components`).
 * Storybook stories import `AuthContext` from here to supply a fixture user through `<AuthContext.Provider value={...}>`
 * without real `login()` or `/auth/me` calls.
 */
import { createContext } from "react";

import type { UiPreferenceValue, User } from "../api/types";

export type LoginResult = { requires2fa: false; user: User } | { requires2fa: true; challengeToken: string };

export interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  /** Creates an account; resolves to `null` when the address must be confirmed first (no session is issued). */
  signup: (email: string, password: string, displayName: string, inviteToken?: string) => Promise<User | null>;
  verify2fa: (challengeToken: string, code: string) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  /** Sets one `ui_preferences` key; `null` removes it (and persists the removal). */
  setUiPreference: (key: string, value: UiPreferenceValue | null) => void;
  /** Applies several keys in one request (`null` removes); use when keys must change together, since separate concurrent
   * PATCHes are read-modify-write on the same server-side bag. Applied optimistically; rejects if the server refused it
   * (e.g. the size bound), after the local copy is re-synced from the server. Callers that report success must await it. */
  setUiPreferences: (patch: Record<string, UiPreferenceValue | null>) => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
