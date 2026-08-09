import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { SignupConfig } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { resolveLandingPath } from "./LoginPage";

const strings = t();

/**
 * Public self-registration form (`ServerSettings.signup_mode`). Fetches
 * the public, unauthenticated signup-config on mount to decide what to
 * render: nothing usable if signup is `disabled` (unless an invite token
 * is present in the URL, which bypasses the mode entirely — an explicit
 * admin invite is authorization enough, see `routers/auth.py::signup`), a
 * plain form for `always_on`, and the same plain form plus a hint for
 * `org_specified` (the email-domain match happens server-side on submit,
 * no client-side org picker needed).
 */
export function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inviteToken = searchParams.get("invite") ?? undefined;

  const [config, setConfig] = useState<SignupConfig | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.get<SignupConfig>("/api/v1/system/signup-config").then(setConfig);
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await signup(email, password, displayName, inviteToken);
      navigate(await resolveLandingPath(user));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.signup.error);
    } finally {
      setSubmitting(false);
    }
  }

  if (config === null) {
    return null; // brief loading flash only — avoids rendering a form that might immediately need to be replaced
  }

  const signupUsable = inviteToken || config.signup_mode !== "disabled";
  if (!signupUsable) {
    return (
      <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
        <div className="card stack">
          <p>{strings.signup.unavailable}</p>
          <a className="btn" href="/login">
            {strings.signup.backToLogin}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
      <form className="card stack" onSubmit={handleSubmit}>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.signup.title}</h1>
        {inviteToken ? (
          <p className="text-muted">{strings.signup.invitePrompt}</p>
        ) : (
          config.signup_mode === "org_specified" && <p className="text-muted">{strings.signup.orgSpecifiedHint}</p>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.signup.displayName}
          <input
            className="input" required autoFocus value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.signup.email}
          <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.signup.password}
          <input
            className="input" type="password" required minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "…" : strings.signup.submit}
        </button>
        <a className="text-muted" href="/login">
          {strings.signup.backToLogin}
        </a>
      </form>
    </div>
  );
}
