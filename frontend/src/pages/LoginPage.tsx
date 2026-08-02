import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ProjectListItem, User } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Resolves where to send the user after login (U-U-03): a specific project,
 * the project overview list, or "automatic" (the sole accessible project if
 * there's exactly one, else the overview list).
 */
export async function resolveLandingPath(user: User): Promise<string> {
  const preference = user.landing_preference;
  if (preference && preference !== "auto" && preference !== "overview") {
    return `/projects/${preference}`;
  }
  if (preference === "overview") {
    return "/projects";
  }
  const projects = await api.get<ProjectListItem[]>("/api/v1/projects?archived=false");
  return projects.length === 1 ? `/projects/${projects[0].id}` : "/projects";
}

export function LoginPage() {
  const { login, verify2fa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const reauthMessage = (location.state as { message?: string } | null)?.message ?? null;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if (result.requires2fa) {
        setChallengeToken(result.challengeToken);
      } else {
        navigate(await resolveLandingPath(result.user));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.login.error);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify2fa(e: FormEvent) {
    e.preventDefault();
    if (!challengeToken) return;
    setError(null);
    setSubmitting(true);
    try {
      const user = await verify2fa(challengeToken, code);
      navigate(await resolveLandingPath(user));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.login.error);
    } finally {
      setSubmitting(false);
    }
  }

  if (challengeToken) {
    return (
      <div className="container" style={{ maxWidth: 380, marginTop: "4rem" }}>
        <form className="card stack" onSubmit={handleVerify2fa}>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.login.twoFactorTitle}</h1>
          <p className="text-muted">{strings.login.twoFactorPrompt}</p>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.login.twoFactorCode}
            <input
              className="input"
              inputMode="numeric"
              autoFocus
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "…" : strings.login.submit}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: 380, marginTop: "4rem" }}>
      <form className="card stack" onSubmit={handleSubmit}>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.login.title}</h1>
        {reauthMessage && <div className="text-muted">{reauthMessage}</div>}
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.login.email}
          <input
            className="input"
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.login.password}
          <input
            className="input"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "…" : strings.login.submit}
        </button>
      </form>
    </div>
  );
}
