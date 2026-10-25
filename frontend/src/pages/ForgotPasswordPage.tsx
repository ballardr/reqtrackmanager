/**
 * Module: pages/ForgotPasswordPage
 *
 * Signed-out page where a person asks for a password-reset link (`POST /auth/forgot-password`).
 *
 * Responsibilities: collect the account's email and show one confirmation whatever the address is, because
 * the API answers the same way for every address (it never reveals whether an account exists). A rate-limit
 * refusal is shown as such. The link itself arrives by email and opens `ResetPasswordPage`.
 */
import { useState, type FormEvent } from "react";

import { ApiError, api } from "../api/client";
import { AuthCard } from "../components/AuthCard";
import { TextField } from "../components/FormFields";
import { t } from "../i18n/strings";

const strings = t();

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post("/api/v1/auth/forgot-password", { email });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? err.message : strings.passwordReset.forgotError);
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <AuthCard>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.passwordReset.forgotTitle}</h1>
        <p role="status">{strings.passwordReset.forgotSent}</p>
        <a className="btn" href="/login">
          {strings.passwordReset.backToLogin}
        </a>
      </AuthCard>
    );
  }

  return (
    <AuthCard onSubmit={handleSubmit}>
      <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.passwordReset.forgotTitle}</h1>
      <p className="text-muted">{strings.passwordReset.forgotPrompt}</p>
      <TextField helpNotNeeded required
        label={strings.passwordReset.email}
        value={email}
        onChange={setEmail}
        inputProps={{ type: "email", autoFocus: true }}
      />
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? "…" : strings.passwordReset.sendLink}
      </button>
      <a className="text-muted" href="/login">
        {strings.passwordReset.backToLogin}
      </a>
    </AuthCard>
  );
}
