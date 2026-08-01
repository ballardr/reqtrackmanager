import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";

const strings = t();

export function LoginPage() {
  const { login, verify2fa } = useAuth();
  const navigate = useNavigate();
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
        navigate("/projects");
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
      await verify2fa(challengeToken, code);
      navigate("/projects");
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
