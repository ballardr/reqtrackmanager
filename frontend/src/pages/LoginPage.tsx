import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ServerSettings, SignupConfig } from "../api/types";
import { LoginAnnouncements } from "../components/LoginAnnouncements";
import { LoginBrandHeader } from "../components/LoginBrandHeader";
import { SignedOutPage } from "../components/SignedOutPage";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";
import { TextField } from "../components/FormFields";
import { resolvePostSignInPath } from "../utils/signInDestination";

const strings = t();

export function LoginPage() {
  const { login, verify2fa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const routerState = location.state as { message?: string; challengeToken?: string } | null;
  // Only a redirect's own message (a password change ending the session) is shown; a page to return to adds no text.
  const reauthMessage = routerState?.message ?? null;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  // Set when arriving from OrgLoginPage's 2FA branch (E-P-03): it hands its issued challenge token over
  // in router state so this page opens on the code step.
  const [challengeToken, setChallengeToken] = useState<string | null>(routerState?.challengeToken ?? null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loginBackgroundFileId, setLoginBackgroundFileId] = useState<string | null>(null);
  const [signupAvailable, setSignupAvailable] = useState(false);
  // Platform-default branding (U-C-02): the page is outside BrandingProvider (no organisation context),
  // so it uses the deployment-wide default, the same fields as `BrandingContext`'s serverDefault.
  const [brandLogoFileId, setBrandLogoFileId] = useState<string | null>(null);
  const [brandTitle, setBrandTitle] = useState(strings.appName);
  const [brandBandColorHex, setBrandBandColorHex] = useState<string | null>(null);
  const [brandBandTextColorHex, setBrandBandTextColorHex] = useState<string | null>(null);

  useEffect(() => {
    api.get<ServerSettings>("/api/v1/system/branding").then((s) => {
      setLoginBackgroundFileId(s.default_login_background_file_id);
      setBrandLogoFileId(s.default_logo_file_id);
      setBrandBandColorHex(s.logo_band_color_hex);
      setBrandBandTextColorHex(s.logo_band_text_color_hex);
      setBrandTitle(s.default_header_title || strings.appName);
    });
    api.get<SignupConfig>("/api/v1/system/signup-config").then((c) => setSignupAvailable(c.signup_mode !== "disabled"));
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if (result.requires2fa) {
        setChallengeToken(result.challengeToken);
      } else {
        navigate(await resolvePostSignInPath(result.user));
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
      const user = await verify2fa(challengeToken, code);
      navigate(await resolvePostSignInPath(user));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.login.error);
    } finally {
      setSubmitting(false);
    }
  }

  if (challengeToken) {
    return (
      <SignedOutPage backgroundFileId={loginBackgroundFileId}>
        <form className="card stack" onSubmit={handleVerify2fa}>
          <LoginBrandHeader logoFileId={brandLogoFileId} title={brandTitle} bandColorHex={brandBandColorHex} bandTextColorHex={brandBandTextColorHex} />
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.login.twoFactorTitle}</h2>
          <p className="text-muted">{strings.login.twoFactorPrompt}</p>
          <TextField helpNotNeeded
            label={strings.login.twoFactorCode}
            value={code}
            onChange={setCode}
            inputProps={{ required: true, inputMode: "numeric", autoFocus: true }}
          />
          {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "…" : strings.login.submit}
          </button>
        </form>
      </SignedOutPage>
    );
  }

  return (
    <SignedOutPage backgroundFileId={loginBackgroundFileId}>
      <LoginAnnouncements />
      <form className="card stack" onSubmit={handleSubmit}>
        <LoginBrandHeader logoFileId={brandLogoFileId} title={brandTitle} bandColorHex={brandBandColorHex} bandTextColorHex={brandBandTextColorHex} />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.login.title}</h2>
        {reauthMessage && <div className="text-muted">{reauthMessage}</div>}
        <TextField helpNotNeeded
          label={strings.login.email}
          value={email}
          onChange={setEmail}
          inputProps={{ required: true, autoFocus: true, type: "email" }}
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
        {signupAvailable && (
          <div className="text-muted" style={{ textAlign: "center" }}>
            {strings.login.signUpPrompt} <a href="/signup">{strings.login.signUpLink}</a>
          </div>
        )}
      </form>
    </SignedOutPage>
  );
}
