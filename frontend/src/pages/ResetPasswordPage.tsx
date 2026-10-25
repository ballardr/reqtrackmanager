/**
 * Module: pages/ResetPasswordPage
 *
 * Signed-out page a password-reset link opens (`/reset-password#token=...`): the person chooses a new
 * password (`POST /auth/reset-password`).
 *
 * Responsibilities: read the link's secret from the URL fragment and remove it from the address bar at once,
 * collect and confirm the new password, and send the person to the sign-in page with a confirmation.
 *
 * Design decisions: the secret is in the fragment, which browsers never send to a server, so it stays out of
 * access logs and referrers; it is held in component state only after being cleared from the URL. The page
 * does not sign the person in: they sign in with the new password (and second factor, if enrolled).
 */
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { AuthCard } from "../components/AuthCard";
import { TextField } from "../components/FormFields";
import { t } from "../i18n/strings";

const strings = t();

/**
 * @returns The secret in the current URL fragment (`#token=...`), or `""` when there is none.
 */
function tokenFromFragment(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
}

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [token] = useState(tokenFromFragment);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [linkRejected, setLinkRejected] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLinkRejected(false);
    if (password !== confirm) {
      setError(strings.passwordReset.passwordsDiffer);
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/api/v1/auth/reset-password", { token, new_password: password });
      navigate("/login", { state: { message: strings.passwordReset.done } });
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setLinkRejected(true);
        setError(strings.passwordReset.invalidLink);
      } else {
        setError(err instanceof ApiError && err.status === 429 ? err.message : strings.passwordReset.resetError);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <AuthCard>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.passwordReset.resetTitle}</h1>
        <p role="alert">{strings.passwordReset.missingLink}</p>
        <a className="btn" href="/forgot-password">
          {strings.passwordReset.requestNew}
        </a>
      </AuthCard>
    );
  }

  return (
    <AuthCard onSubmit={handleSubmit}>
      <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.passwordReset.resetTitle}</h1>
      <p className="text-muted">{strings.passwordReset.resetPrompt}</p>
      <TextField helpNotNeeded required
        label={strings.passwordReset.newPassword}
        value={password}
        onChange={setPassword}
        inputProps={{ minLength: 8, type: "password", autoFocus: true, autoComplete: "new-password" }}
      />
      <TextField helpNotNeeded required
        label={strings.passwordReset.confirmPassword}
        value={confirm}
        onChange={setConfirm}
        inputProps={{ minLength: 8, type: "password", autoComplete: "new-password" }}
      />
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)" }}>
          {error}
          {linkRejected && (
            <>
              {" "}
              <a href="/forgot-password">{strings.passwordReset.requestNew}</a>
            </>
          )}
        </div>
      )}
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? "…" : strings.passwordReset.submit}
      </button>
    </AuthCard>
  );
}
