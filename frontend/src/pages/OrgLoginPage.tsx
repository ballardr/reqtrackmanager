import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, api, apiUrl } from "../api/client";
import type { OrgLoginInfo } from "../api/types";
import { LoginAnnouncements } from "../components/LoginAnnouncements";
import { LoginBrandHeader } from "../components/LoginBrandHeader";
import { SignedOutPage } from "../components/SignedOutPage";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { resolvePostSignInPath } from "../utils/signInDestination";
import { TextField } from "../components/FormFields";

const strings = t();

// Shared with OidcCompletePage.tsx: the sessionStorage key of the client-generated login nonce.
export const OIDC_CLIENT_NONCE_STORAGE_KEY = "oidc_client_nonce";

/**
 * Generates an unguessable nonce and stores it in this tab's `sessionStorage` before navigating to the SSO
 * login-start endpoint. The backend round-trips it through the signed `state` parameter and the
 * `/oidc-complete` redirect (`security.create_oidc_state_token`), so `OidcCompletePage` can verify the token
 * belongs to this browser's login attempt (login CSRF / session fixation).
 */
function generateClientNonce(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, nonce);
  return nonce;
}

/**
 * An organisation's branded login page (E-P-03), resolved by slug: the "Sign in with SSO" button when
 * configured, and the email/password form unless the organisation sets `sso_only`.
 *
 * Login resolves to the same global User account as the root /login page (C-U-02/C-U-15); the page only
 * changes which method is offered. See docs/enterprise-integration.md for `sso_only` with no native password.
 */
export function OrgLoginPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [info, setInfo] = useState<OrgLoginInfo | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [ssoNonce] = useState(generateClientNonce);

  useEffect(() => {
    if (!slug) return;
    api
      .get<OrgLoginInfo>(`/api/v1/orgs/by-slug/${slug}/login-info`)
      .then(setInfo)
      .catch(() => setNotFound(true));
  }, [slug]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if (result.requires2fa) {
        // A 2FA challenge continues on /login (no duplicate code form); the issued challenge token
        // travels in router state so LoginPage opens on the code step.
        navigate("/login", { state: { challengeToken: result.challengeToken } });
      } else {
        window.location.href = await resolvePostSignInPath(result.user);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.login.error);
    } finally {
      setSubmitting(false);
    }
  }

  if (notFound) {
    return (
      <div className="container" style={{ maxWidth: 380, marginTop: "4rem" }}>
        <div className="card stack">{strings.common.error}</div>
      </div>
    );
  }
  if (!info) return null;

  return (
    <SignedOutPage backgroundFileId={info.login_background_file_id} footerPosition={info.footer_position}>
    <LoginAnnouncements organizationSlug={slug} />
    <div className="card stack">
      <LoginBrandHeader logoFileId={info.logo_file_id} title={info.name} bandColorHex={info.logo_band_color_hex} bandTextColorHex={info.logo_band_text_color_hex} />

      {info.sso_enabled && (
        <a
          className="btn btn-primary"
          href={apiUrl(`/api/v1/auth/oidc/${slug}/login?client_nonce=${encodeURIComponent(ssoNonce)}`)}
          style={{ textAlign: "center" }}
        >
          {strings.login.signInWithSso}
        </a>
      )}

      {info.sso_enabled && !info.sso_only && (
        <div className="row" style={{ justifyContent: "center", color: "var(--color-text-muted)" }}>
          {strings.login.orDivider}
        </div>
      )}

      {!info.sso_only && (
        <form className="stack" onSubmit={handleSubmit}>
          <TextField helpNotNeeded
            label={strings.login.email}
            value={email}
            onChange={setEmail}
            inputProps={{ required: true, type: "email" }}
          />
          <TextField helpNotNeeded
            label={strings.login.password}
            value={password}
            onChange={setPassword}
            inputProps={{ required: true, type: "password" }}
          />
          {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "…" : strings.login.submit}
          </button>
          <a className="text-muted" href="/forgot-password" style={{ textAlign: "center" }}>
            {strings.passwordReset.forgotLink}
          </a>
        </form>
      )}
    </div>
    </SignedOutPage>
  );
}
