import { useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { AUTH_UNAUTHORIZED_EVENT, api, loadStoredToken, setAuthToken } from "../api/client";
import type { User } from "../api/types";
import { AuthContext, type AuthContextValue, type LoginResult } from "./AuthContextValue";

/** Provides the authenticated user and login/logout actions to the app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.get<User>("/api/v1/auth/me");
      setUser(me);
    } catch {
      setAuthToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    const token = loadStoredToken();
    if (!token) {
      setLoading(false);
      return;
    }
    refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string): Promise<LoginResult> => {
    const result = await api.post<
      { access_token: string; user: User } | { requires_2fa: true; challenge_token: string }
    >("/api/v1/auth/login", { email, password });
    if ("requires_2fa" in result) {
      return { requires2fa: true, challengeToken: result.challenge_token };
    }
    setAuthToken(result.access_token);
    setUser(result.user);
    return { requires2fa: false, user: result.user };
  }, []);

  const signup = useCallback(
    async (email: string, password: string, displayName: string, inviteToken?: string): Promise<User> => {
      const result = await api.post<{ access_token: string; user: User }>("/api/v1/auth/signup", {
        email,
        password,
        display_name: displayName,
        invite_token: inviteToken || undefined,
      });
      setAuthToken(result.access_token);
      setUser(result.user);
      return result.user;
    },
    [],
  );

  const verify2fa = useCallback(async (challengeToken: string, code: string): Promise<User> => {
    const result = await api.post<{ access_token: string; user: User }>("/api/v1/auth/2fa/verify", {
      challenge_token: challengeToken,
      code,
    });
    setAuthToken(result.access_token);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setUser(null);
  }, []);

  // A 401 with `WWW-Authenticate` (client.ts's `AUTH_UNAUTHORIZED_EVENT`)
  // means the session token itself is dead — expired, or invalidated by a
  // password change/2FA change in another tab. Clearing `user` immediately
  // (rather than only on the next mount) is what makes `ProtectedRoutes`
  // (App.tsx) redirect to /login right away instead of leaving the page
  // rendered on stale data until a hard refresh forces a re-check.
  useEffect(() => {
    const onUnauthorized = () => {
      setAuthToken(null);
      setUser(null);
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  // Applied optimistically (an instant toggle shouldn't wait on a round
  // trip) and persisted server-side (U-U-01/U-U-03's existing preference
  // fields all sync this way) so it follows the user across devices/
  // sessions rather than living only in this browser's localStorage.
  const setUiPreference = useCallback((key: string, value: string | boolean) => {
    setUser((current) => (current ? { ...current, ui_preferences: { ...current.ui_preferences, [key]: value } } : current));
    api.patch("/api/v1/auth/me/preferences", { ui_preferences: { [key]: value } }).catch(() => {
      // Best-effort: a failed sync just means this device's next reload
      // falls back to whatever was last persisted — not worth surfacing
      // as an error for a low-stakes display preference.
    });
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, verify2fa, logout, refreshUser, setUiPreference }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
