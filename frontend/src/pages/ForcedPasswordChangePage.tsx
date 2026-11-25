/**
 * Module: pages/ForcedPasswordChangePage
 *
 * The only screen an account sees while an administrator-set password is in place (`User.must_change_password`): the person enters that
 * password and chooses their own. It collects and confirms the new password, sends `POST /auth/change-password` and sends the person to
 * sign-in (the change ends every session; the current page is remembered for the return); signing out is the alternative. `App.tsx`
 * renders it in place of the whole application, not as a route, so no address leaves it; the server also refuses every other request
 * (`services.password_change_gate`).
 */
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { AuthCard } from "../components/AuthCard";
import { TextField } from "../components/FormFields";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { rememberReturnTo } from "../utils/returnTo";

const strings = t();

/**
 * Asks for a new password before the application can be used.
 */
export function ForcedPasswordChangePage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
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
      // The change ends this session; signing in again returns the person to the page they were on.
      rememberReturnTo(location.pathname + location.search + location.hash);
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
