import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import type { ProjectListItem, ServerSettings, SignupConfig, User } from "../api/types";
import { LoginBrandHeader } from "../components/LoginBrandHeader";
import { useAuth } from "../context/AuthContext";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Resolves where to send the user after login (U-U-03): a specific project,
 * the project overview list, or "automatic" (the sole accessible project if
 * there's exactly one, else the overview list).
 */
export async function resolveLandingPath(user: User): Promise<string> {
  const preference = user.landing_preference;
  if (preference && preference !== "auto" && preference !== "overview") {
    return `/projects/${preference}`;
  }
  if (preference === "overview") {
    return "/projects";
  }
  const projects = await api.get<ProjectListItem[]>("/api/v1/projects?archived=false");
  return projects.length === 1 ? `/projects/${projects[0].id}` : "/projects";
}

export function LoginPage() {
  const { login, verify2fa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const routerState = location.state as { message?: string; challengeToken?: string } | null;
  const reauthMessage = routerState?.message ?? null;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  // Pre-populated when arriving from OrgLoginPage's own 2FA branch (E-P-03) —
  // that page never duplicates the code-entry form, it hands off its
  // already-issued challenge token here via router state so this page opens
  // straight on step two instead of asking for email/password again.
  const [challengeToken, setChallengeToken] = useState<string | null>(routerState?.challengeToken ?? null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loginBackgroundFileId, setLoginBackgroundFileId] = useState<string | null>(null);
  const [signupAvailable, setSignupAvailable] = useState(false);
  // Platform-default branding (U-C-02) — this page is pre-auth/outside
  // BrandingProvider (no org/project context to resolve an org's own
  // branding against), so it falls back straight to the deployment-wide
  // default, same fields `BrandingContext`'s own serverDefault uses.
  const [brandLogoFileId, setBrandLogoFileId] = useState<string | null>(null);
  const [brandTitle, setBrandTitle] = useState(strings.appName);

  useEffect(() => {
    api.get<ServerSettings>("/api/v1/system/branding").then((s) => {
      setLoginBackgroundFileId(s.default_login_background_file_id);
      setBrandLogoFileId(s.default_logo_file_id);
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
        navigate(await resolveLandingPath(result.user));
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
      navigate(await resolveLandingPath(user));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.login.error);
    } finally {
      setSubmitting(false);
    }
  }

  const backgroundStyle = loginBackgroundFileId
    ? {
        backgroundImage: `url(${fileUrl(loginBackgroundFileId)})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        minHeight: "100vh",
      }
    : { minHeight: "100vh" };

  if (challengeToken) {
    return (
      <div style={backgroundStyle}>
      <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
        <form className="card stack" onSubmit={handleVerify2fa}>
          <LoginBrandHeader logoFileId={brandLogoFileId} title={brandTitle} />
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.login.twoFactorTitle}</h2>
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
      </div>
    );
  }

  return (
    <div style={backgroundStyle}>
    <div className="container" style={{ maxWidth: 380, paddingTop: "4rem" }}>
      <form className="card stack" onSubmit={handleSubmit}>
        <LoginBrandHeader logoFileId={brandLogoFileId} title={brandTitle} />
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.login.title}</h2>
        {reauthMessage && <div className="text-muted">{reauthMessage}</div>}
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
        {signupAvailable && (
          <div className="text-muted" style={{ textAlign: "center" }}>
            {strings.login.signUpPrompt} <a href="/signup">{strings.login.signUpLink}</a>
          </div>
        )}
      </form>
    </div>
    </div>
  );
}
