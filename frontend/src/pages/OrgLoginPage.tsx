import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { ApiError, api, apiUrl, fileUrl } from "../api/client";
import type { OrgLoginInfo } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { resolveLandingPath } from "./LoginPage";

const strings = t();

// Shared with OidcCompletePage.tsx: the sessionStorage key the client-generated
// login nonce round-trips through. See generateClientNonce()'s docstring below.
export const OIDC_CLIENT_NONCE_STORAGE_KEY = "oidc_client_nonce";

/**
 * Generates a fresh, unguessable nonce and stores it in this tab's
 * `sessionStorage` before the browser ever navigates to the SSO login-start
 * endpoint. The backend round-trips it through the signed `state` parameter
 * and the eventual `/oidc-complete` redirect (see
 * `security.create_oidc_state_token`'s docstring), so `OidcCompletePage` can
 * verify the token it receives belongs to *this* browser's own login
 * attempt rather than one crafted/replayed by an attacker (login-CSRF /
 * session-fixation) — a URL alone proves nothing about who is viewing it.
 */
function generateClientNonce(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  sessionStorage.setItem(OIDC_CLIENT_NONCE_STORAGE_KEY, nonce);
  return nonce;
}

/**
 * An organisation's branded login page (E-P-03), resolved by slug. Offers
 * that org's "Sign in with SSO" button when configured, and the native
 * email/password form as a fallback unless the org has set `sso_only`.
 *
 * Login here always resolves to the same global User account a login from
 * the root /login page would (C-U-02/C-U-15: one account, not one per org)
 * — this page only affects which login method is offered, never which
 * account is reached. See docs/enterprise-integration.md for the documented
 * limitation when `sso_only` is set and a user has no native password.
 */
export function OrgLoginPage() {
  const { slug } = useParams<{ slug: string }>();
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
      if (!result.requires2fa) {
        window.location.href = await resolveLandingPath(result.user);
      }
      // A 2FA challenge on an org-branded page falls through to the plain
      // /login flow rather than duplicating the code-entry form here.
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

  const backgroundStyle = info.login_background_file_id
    ? {
        backgroundImage: `url(${fileUrl(info.login_background_file_id)})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        minHeight: "100vh",
      }
    : { minHeight: "100vh" };

  return (
    <div style={backgroundStyle}>
      <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
        <div className="card stack">
          {info.logo_file_id && (
            <img src={fileUrl(info.logo_file_id)} alt="" style={{ height: 40, alignSelf: "center" }} />
          )}
          <h1 style={{ margin: 0, fontSize: "1.4rem", textAlign: "center" }}>{info.name}</h1>

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
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.login.email}
                <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.login.password}
                <input
                  className="input" type="password" required value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting ? "…" : strings.login.submit}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
