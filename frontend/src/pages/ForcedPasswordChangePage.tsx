/**
 * Module: pages/ForcedPasswordChangePage
 *
 * The only screen an account sees while an administrator-set password is still in place
 * (`User.must_change_password`): the person enters the password they were given and chooses their own.
 *
 * Responsibilities: collect and confirm the new password, send it with `POST /auth/change-password`, and send the
 * person to the sign-in page afterwards (the change ends every session, including this one). Signing out is the
 * alternative.
 *
 * Design decisions: rendered in place of the whole signed-in application by `App.tsx`, not as a route, so there is no
 * address that leaves it; the server refuses every other request of the account in any case
 * (`services.password_change_gate`).
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { AuthCard } from "../components/AuthCard";
import { TextField } from "../components/FormFields";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Asks for a new password before the application can be used.
 */
export function ForcedPasswordChangePage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError(strings.forcedPasswordChange.passwordsDiffer);
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/api/v1/auth/change-password", { current_password: current, new_password: password });
      logout();
      navigate("/login", { state: { message: strings.login.reauthRequired } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.forcedPasswordChange.failed);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard onSubmit={handleSubmit}>
      <h1 style={{ margin: 0, fontSize: "1.4rem" }}>{strings.forcedPasswordChange.title}</h1>
      <p className="text-muted">{strings.forcedPasswordChange.prompt}</p>
      <TextField helpNotNeeded required
        label={strings.forcedPasswordChange.currentPassword}
        value={current}
        onChange={setCurrent}
        inputProps={{ type: "password", autoFocus: true, autoComplete: "current-password" }}
      />
      <TextField helpNotNeeded required
        label={strings.forcedPasswordChange.newPassword}
        value={password}
        onChange={setPassword}
        inputProps={{ minLength: 8, type: "password", autoComplete: "new-password" }}
      />
      <TextField helpNotNeeded required
        label={strings.forcedPasswordChange.confirmPassword}
        value={confirm}
        onChange={setConfirm}
        inputProps={{ minLength: 8, type: "password", autoComplete: "new-password" }}
      />
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)" }}>
          {error}
        </div>
      )}
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? "…" : strings.forcedPasswordChange.submit}
      </button>
      <button className="btn" type="button" onClick={() => { logout(); navigate("/login"); }}>
        {strings.forcedPasswordChange.signOut}
      </button>
    </AuthCard>
  );
}
