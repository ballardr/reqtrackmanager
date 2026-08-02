import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { setAuthToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { OIDC_CLIENT_NONCE_STORAGE_KEY } from "./OrgLoginPage";

const strings = t();

/**
 * Landing point for the OIDC login redirect (E-U-01): the backend's
 * `/api/v1/auth/oidc/callback` finishes the token exchange server-side and
 * redirects here with a working app access token — carried in the URL
 * *fragment*, not the query string, since fragments are never transmitted
 * to any server and so never land in access logs (see the backend redirect
 * in `routers/auth_oidc.py` for the matching rationale).
 *
 * Before trusting that token, this page confirms the `client_nonce` riding
 * alongside it matches the one this same browser generated and stashed in
 * `sessionStorage` before it ever started this login attempt
 * (`OrgLoginPage.generateClientNonce`). Without this check, anyone who can
 * get a victim to open `/oidc-complete#token=<attacker's own valid
 * token>` would silently log the victim's browser into the attacker's
 * account — a login-CSRF / session-fixation attack. A bare URL proves
 * nothing about who's viewing it; the nonce proves the token is the result
 * of a flow *this* browser itself kicked off.
 */
export function OidcCompletePage() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Not react-router's useSearchParams: the payload is in the fragment
    // (after '#'), which react-router treats as opaque and never parses.
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);

    const expectedNonce = sessionStorage.getItem(OIDC_CLIENT_NONCE_STORAGE_KEY);
    sessionStorage.removeItem(OIDC_CLIENT_NONCE_STORAGE_KEY); // single-use regardless of outcome

    const deniedMessage = query.get("message");
    if (query.get("error") === "not_provisioned") {
      // Authenticated successfully at the identity provider, but the org
      // hasn't granted this account's IdP group access (Organization.
      // oidc_required_group) — no token was ever issued, so there's nothing
      // to store; just show why. Still nonce-checked so this page can't be
      // used to plant an arbitrary-looking denial message either.
      const receivedNonce = query.get("client_nonce");
      if (!expectedNonce || receivedNonce !== expectedNonce) {
        setError(strings.login.error);
        return;
      }
      setError(deniedMessage || strings.login.notProvisioned);
      return;
    }

    const token = fragment.get("token");
    const receivedNonce = fragment.get("client_nonce");
    if (!token || !expectedNonce || receivedNonce !== expectedNonce) {
      setError(strings.login.error);
      return;
    }
    // Clear the fragment immediately so the token never lingers in browser
    // history/back-forward cache as a visible URL.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    setAuthToken(token);
    refreshUser().then(() => navigate("/projects", { replace: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) {
    return (
      <div className="container" style={{ maxWidth: 380, marginTop: "4rem" }}>
        <div className="card stack">
          <div style={{ color: "var(--color-danger)" }}>{error}</div>
          <Link to="/login" className="btn" style={{ alignSelf: "flex-start" }}>
            {strings.login.title}
          </Link>
        </div>
      </div>
    );
  }
  return null;
}
