import { useEffect, useState } from "react";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";
import { t } from "../i18n/strings";
import type { DigestMode, NotificationPreference, ProjectListItem } from "../api/types";

type LandingMode = "auto" | "overview" | "project";

function landingModeFor(preference: string | undefined): LandingMode {
  if (!preference || preference === "auto") return "auto";
  if (preference === "overview") return "overview";
  return "project";
}

const strings = t();

/**
 * User preferences: theme (U-U-01), post-login landing page (U-U-03),
 * pronouns (C-U-18), email digest mode (C-N-05), password change, and
 * TOTP two-factor enrollment (C-U-14).
 */
export function PreferencesPage() {
  const { user, refreshUser } = useAuth();
  const { theme, setTheme } = useTheme();
  const [landingMode, setLandingMode] = useState<LandingMode>(landingModeFor(user?.landing_preference));
  const [landingProjectId, setLandingProjectId] = useState(
    landingModeFor(user?.landing_preference) === "project" ? user?.landing_preference ?? "" : ""
  );
  const [myProjects, setMyProjects] = useState<ProjectListItem[]>([]);
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [pronouns, setPronouns] = useState(user?.pronouns ?? "");
  const [digestMode, setDigestMode] = useState<DigestMode>(user?.email_digest_mode ?? "instant");
  const [saved, setSaved] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [enrollment, setEnrollment] = useState<{ secret: string; qrCodePngBase64: string } | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [twoFactorError, setTwoFactorError] = useState<string | null>(null);

  const [notificationPrefs, setNotificationPrefs] = useState<NotificationPreference[]>([]);

  useEffect(() => {
    api.get<NotificationPreference[]>("/api/v1/notifications/preferences").then(setNotificationPrefs);
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(setMyProjects);
  }, []);

  async function updateNotificationPref(type: string, field: "ui_enabled" | "email_enabled", value: boolean) {
    const current = notificationPrefs.find((p) => p.type === type);
    if (!current) return;
    const updated = { ...current, [field]: value };
    await api.put(`/api/v1/notifications/preferences/${type}`, {
      ui_enabled: updated.ui_enabled, email_enabled: updated.email_enabled,
    });
    setNotificationPrefs((prefs) => prefs.map((p) => (p.type === type ? updated : p)));
  }

  async function save() {
    setProfileError(null);
    try {
      await api.patch("/api/v1/auth/me/preferences", {
        landing_preference: landingMode === "project" ? landingProjectId : landingMode,
        theme_preference: theme,
        display_name: displayName,
        pronouns,
        email_digest_mode: digestMode,
      });
      await refreshUser();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setProfileError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function changePassword() {
    setPasswordError(null);
    setPasswordMessage(null);
    try {
      await api.post("/api/v1/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setPasswordMessage(strings.preferences.saved);
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function startEnrollment() {
    setTwoFactorError(null);
    const result = await api.post<{ secret: string; qr_code_png_base64: string }>("/api/v1/auth/2fa/enroll");
    setEnrollment({ secret: result.secret, qrCodePngBase64: result.qr_code_png_base64 });
  }

  async function confirmEnrollment() {
    setTwoFactorError(null);
    try {
      await api.post("/api/v1/auth/2fa/confirm", { code: confirmCode });
      setEnrollment(null);
      setConfirmCode("");
      await refreshUser();
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function disable2fa() {
    setTwoFactorError(null);
    try {
      await api.post("/api/v1/auth/2fa/disable", { code: disableCode });
      setDisableCode("");
      await refreshUser();
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 480 }}>
      <h1 style={{ margin: 0 }}>{strings.preferences.title}</h1>

      <div className="card stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.avatar}
          <div className="row">
            {user?.avatar_file_id && (
              <img
                src={fileUrl(user.avatar_file_id)}
                alt="avatar"
                style={{ width: 48, height: 48, borderRadius: "50%", objectFit: "cover" }}
              />
            )}
            <input
              type="file"
              accept="image/*"
              onChange={async (e) => {
                if (e.target.files?.[0]) {
                  await api.postFile("/api/v1/auth/me/avatar", e.target.files[0]);
                  await refreshUser();
                }
              }}
            />
          </div>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.displayName}
          <input
            className="input"
            value={displayName}
            disabled={user?.display_name_locked}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          {user?.display_name_locked && <span className="text-muted">{strings.preferences.displayNameLocked}</span>}
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.pronouns}
          <input className="input" value={pronouns} onChange={(e) => setPronouns(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.theme}
          <select className="input" value={theme} onChange={(e) => setTheme(e.target.value as ThemePreference)}>
            <option value="light">{strings.preferences.light}</option>
            <option value="dark">{strings.preferences.dark}</option>
            <option value="system">{strings.preferences.system}</option>
          </select>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.landing}
          <select
            className="input"
            value={landingMode}
            onChange={(e) => setLandingMode(e.target.value as LandingMode)}
          >
            <option value="auto">{strings.preferences.landingAuto}</option>
            <option value="overview">{strings.preferences.landingOverview}</option>
            <option value="project">{strings.preferences.landingProject}</option>
          </select>
        </label>
        {landingMode === "project" && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.preferences.landingProjectSelect}
            <select className="input" value={landingProjectId} onChange={(e) => setLandingProjectId(e.target.value)}>
              {myProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.preferences.emailDigest}
          <select className="input" value={digestMode} onChange={(e) => setDigestMode(e.target.value as DigestMode)}>
            <option value="instant">{strings.preferences.digestInstant}</option>
            <option value="daily">{strings.preferences.digestDaily}</option>
            <option value="none">{strings.preferences.digestNone}</option>
          </select>
        </label>
        {profileError && <div style={{ color: "var(--color-danger)" }}>{profileError}</div>}
        <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
          {strings.preferences.save}
        </button>
        {saved && <div style={{ color: "var(--color-accent)" }}>{strings.preferences.saved}</div>}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.security}</h2>

        <div className="stack">
          <strong>{strings.preferences.changePassword}</strong>
          <input
            className="input"
            type="password"
            placeholder={strings.preferences.currentPassword}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
          <input
            className="input"
            type="password"
            placeholder={strings.preferences.newPassword}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          {passwordError && <div style={{ color: "var(--color-danger)" }}>{passwordError}</div>}
          {passwordMessage && <div style={{ color: "var(--color-accent)" }}>{passwordMessage}</div>}
          <button className="btn" onClick={changePassword} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.changePassword}
          </button>
        </div>

        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{strings.preferences.twoFactor}</strong>
            <span className="badge">
              {user?.is_2fa_enabled ? strings.preferences.twoFactorEnabled : strings.preferences.twoFactorDisabled}
            </span>
          </div>
          {twoFactorError && <div style={{ color: "var(--color-danger)" }}>{twoFactorError}</div>}

          {!user?.is_2fa_enabled && !enrollment && (
            <button className="btn" onClick={startEnrollment} style={{ alignSelf: "flex-start" }}>
              {strings.preferences.enable2fa}
            </button>
          )}

          {enrollment && (
            <div className="stack">
              <p className="text-muted">{strings.preferences.scanQrCode}</p>
              <img
                src={`data:image/png;base64,${enrollment.qrCodePngBase64}`}
                alt="2FA QR code"
                style={{ width: 180, height: 180 }}
              />
              <div className="row">
                <input
                  className="input"
                  style={{ maxWidth: 160 }}
                  placeholder={strings.preferences.confirmCode}
                  value={confirmCode}
                  onChange={(e) => setConfirmCode(e.target.value)}
                />
                <button className="btn btn-primary" onClick={confirmEnrollment}>
                  {strings.preferences.confirmCode}
                </button>
              </div>
            </div>
          )}

          {user?.is_2fa_enabled && (
            <div className="row">
              <input
                className="input"
                style={{ maxWidth: 160 }}
                placeholder={strings.preferences.enterCodeToDisable}
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
              />
              <button className="btn btn-danger" onClick={disable2fa}>
                {strings.preferences.disable2fa}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.notifications.preferencesTitle}</h2>
        <table>
          <thead>
            <tr>
              <th></th>
              <th>{strings.notifications.ui}</th>
              <th>{strings.notifications.email}</th>
            </tr>
          </thead>
          <tbody>
            {notificationPrefs.map((p) => (
              <tr key={p.type}>
                <td>{strings.notifications.types[p.type]}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={p.ui_enabled}
                    onChange={(e) => updateNotificationPref(p.type, "ui_enabled", e.target.checked)}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={p.email_enabled}
                    onChange={(e) => updateNotificationPref(p.type, "email_enabled", e.target.checked)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
