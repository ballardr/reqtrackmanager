import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, loadStoredToken, setAuthToken } from "../api/client";
import type { User } from "../api/types";

type LoginResult = { requires2fa: false } | { requires2fa: true; challengeToken: string };

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  verify2fa: (challengeToken: string, code: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

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
    return { requires2fa: false };
  }, []);

  const verify2fa = useCallback(async (challengeToken: string, code: string) => {
    const result = await api.post<{ access_token: string; user: User }>("/api/v1/auth/2fa/verify", {
      challenge_token: challengeToken,
      code,
    });
    setAuthToken(result.access_token);
    setUser(result.user);
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, verify2fa, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
