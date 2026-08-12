/**
 * Module: testing/StatefulAuthProvider
 *
 * Split out of storybook-helpers.tsx (a file otherwise made up entirely of
 * plain functions — fixture builders, decorator factories) purely to keep
 * that file free of a real component export, since a file mixing component
 * and non-component exports breaks Fast Refresh
 * (react-refresh/only-export-components). Not used directly by stories —
 * `withStatefulAuth` in storybook-helpers.tsx is the public entry point.
 */
import { useState, type ReactNode } from "react";

import type { User } from "../api/types";
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
      setUser((current) => ({ ...current, ui_preferences: { ...current.ui_preferences, [key]: uiValue } })),
    ...overrides,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
