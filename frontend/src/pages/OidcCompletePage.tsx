import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { setAuthToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel } from "../context/BrandingContext";
import { t } from "../i18n/strings";
import { OIDC_CLIENT_NONCE_STORAGE_KEY } from "./OrgLoginPage";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { takeReturnTo } from "../utils/returnTo";

const strings = t();

/**
 * Landing point for the OIDC login redirect (E-U-01): the backend's `/api/v1/auth/oidc/callback`
 * completes the token exchange and redirects here with an access token in the URL fragment, not the
 * query string, because fragments are never sent to a server or logged (`routers/auth_oidc.py`).
 *
 * Before trusting the token, the page checks that the accompanying `client_nonce` matches the one this
 * browser stored in `sessionStorage` when it started the login (`OrgLoginPage.generateClientNonce`).
 * Without it, a victim opening `/oidc-complete#token=<attacker's token>` would be signed in to the
 * attacker's account (login CSRF / session fixation).
 */
export function OidcCompletePage() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const orgLabel = useOrgLabel();

  useLoadOnChange(() => {
    // Not react-router's useSearchParams: the payload is in the fragment
    // (after '#'), which react-router treats as opaque and never parses.
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);

    const expectedNonce = sessionStorage.getItem(OIDC_CLIENT_NONCE_STORAGE_KEY);
    sessionStorage.removeItem(OIDC_CLIENT_NONCE_STORAGE_KEY); // single-use regardless of outcome

    const deniedMessage = query.get("message");
    if (query.get("error") === "not_provisioned") {
      // The identity provider authenticated the account but the organisation's required group
      // (Organization.oidc_required_group) was not granted: no token exists, so only show why.
      // Nonce-checked so the page cannot be used to display an arbitrary denial message.
      const receivedNonce = query.get("client_nonce");
      if (!expectedNonce || receivedNonce !== expectedNonce) {
        setError(strings.login.error);
        return;
      }
      setError(deniedMessage || strings.login.notProvisioned(orgLabel));
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
    refreshUser().then(() => navigate(takeReturnTo() ?? "/projects", { replace: true }));
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
