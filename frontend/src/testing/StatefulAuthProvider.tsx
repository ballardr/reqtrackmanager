/**
 * Module: testing/StatefulAuthProvider
 *
 * Component half of the auth decorator, kept out of storybook-helpers.tsx so
 * that file exports only functions (a mixed file breaks Fast Refresh,
 * react-refresh/only-export-components). Stories use `withStatefulAuth` there.
 */
import { useState, type ReactNode } from "react";

import type { User } from "../api/types";
import { applyUiPreferencePatch } from "../context/uiPreferencePatch";
import { AuthContext, type AuthContextValue } from "../context/AuthContextValue";

export function StatefulAuthProvider({
  initialUser,
  overrides,
  children,
}: {
  initialUser: User;
  overrides: Partial<AuthContextValue>;
  children: ReactNode;
}) {
  const [user, setUser] = useState(initialUser);
  const value: AuthContextValue = {
    user,
    loading: false,
    login: async () => {
      throw new Error("login() was not mocked for this story");
    },
    signup: async () => {
      throw new Error("signup() was not mocked for this story");
    },
    verify2fa: async () => {
      throw new Error("verify2fa() was not mocked for this story");
    },
    logout: () => {},
    refreshUser: async () => {},
    setUiPreference: (key, uiValue) =>
      setUser((current) => ({ ...current, ui_preferences: applyUiPreferencePatch(current.ui_preferences, { [key]: uiValue }) })),
    setUiPreferences: async (patch) =>
      setUser((current) => ({ ...current, ui_preferences: applyUiPreferencePatch(current.ui_preferences, patch) })),
    ...overrides,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
