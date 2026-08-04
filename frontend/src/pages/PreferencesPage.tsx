import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { useAuth } from "../context/AuthContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { t } from "../i18n/strings";
import type {
  DigestMode,
  NotificationPreference,
  Organization,
  PersonalAccessToken,
  PersonalAccessTokenCreateResult,
  ProjectListItem,
} from "../api/types";

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
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const [contentBoxed, setContentBoxed] = useUiPreference<boolean>("content_boxed", false);
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
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [enrollment, setEnrollment] = useState<{ secret: string; qrCodePngBase64: string } | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [twoFactorError, setTwoFactorError] = useState<string | null>(null);

  const [notificationPrefs, setNotificationPrefs] = useState<NotificationPreference[]>([]);

  const [myOrgs, setMyOrgs] = useState<Organization[]>([]);
  const [pats, setPats] = useState<PersonalAccessToken[]>([]);
  const [newPatName, setNewPatName] = useState("");
  const [newPatOrgIds, setNewPatOrgIds] = useState<Set<string>>(new Set());
  const [newPatExpiry, setNewPatExpiry] = useState("");
  const [patError, setPatError] = useState<string | null>(null);
  const [createdPat, setCreatedPat] = useState<PersonalAccessTokenCreateResult | null>(null);

  useEffect(() => {
    api.get<NotificationPreference[]>("/api/v1/notifications/preferences").then(setNotificationPrefs);
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(setMyProjects);
    api.get<Organization[]>("/api/v1/orgs").then(setMyOrgs);
    api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
  }, []);

  function toggleNewPatOrg(orgId: string) {
    setNewPatOrgIds((current) => {
      const next = new Set(current);
      if (next.has(orgId)) next.delete(orgId);
      else next.add(orgId);
      return next;
    });
  }

  async function createPat() {
    setPatError(null);
    if (newPatOrgIds.size === 0) {
      setPatError(strings.preferences.patNoOrgsSelected);
      return;
    }
    try {
      const created = await api.post<PersonalAccessTokenCreateResult>("/api/v1/me/pats", {
        name: newPatName,
        allowed_organization_ids: Array.from(newPatOrgIds),
        requested_expires_at: newPatExpiry ? new Date(newPatExpiry).toISOString() : undefined,
      });
      setCreatedPat(created);
      setNewPatName("");
      setNewPatOrgIds(new Set());
      setNewPatExpiry("");
      api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
    } catch (err) {
      setPatError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function revokePat(id: string) {
    await api.delete(`/api/v1/me/pats/${id}`);
    setPats((current) => current.map((p) => (p.id === id ? { ...p, revoked_at: new Date().toISOString() } : p)));
  }

  async function revokeAllPats() {
    if (!window.confirm(strings.preferences.patRevokeAllConfirm)) return;
    await api.post("/api/v1/me/pats/revoke-all");
    api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
  }

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
    try {
      await api.post("/api/v1/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      // A password change invalidates every token issued before it,
      // including the one this request just used (see User.token_version) —
      // the current session is already dead, so send the user to log back in
      // rather than leaving the app running on a token the server now rejects.
      logout();
      navigate("/login", { state: { message: strings.login.reauthRequired } });
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
      // Same rationale as changePassword: disabling 2FA also bumps
      // token_version, so the current session token is already dead.
      logout();
      navigate("/login", { state: { message: strings.login.reauthRequired } });
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.preferences.title}</h1>

      <CollapsibleSection sectionKey="preferences.profile" title={strings.preferences.profile}>
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
          {strings.preferences.contentWidth}
          <select
            className="input"
            value={contentBoxed ? "boxed" : "full"}
            onChange={(e) => setContentBoxed(e.target.value === "boxed")}
          >
            <option value="full">{strings.preferences.contentWidthFull}</option>
            <option value="boxed">{strings.preferences.contentWidthBoxed}</option>
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
      </CollapsibleSection>

      <CollapsibleSection sectionKey="preferences.security" title={strings.preferences.security}>
        <CollapsibleSection sectionKey="preferences.security.change_password" variant="plain" title={strings.preferences.changePassword}>
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
          <button className="btn" onClick={changePassword} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.changePassword}
          </button>
        </CollapsibleSection>

        <CollapsibleSection
          sectionKey="preferences.security.two_factor"
          variant="plain"
          title={
            <span className="row" style={{ gap: "0.5rem" }}>
              {strings.preferences.twoFactor}
              <span className="badge">
                {user?.is_2fa_enabled ? strings.preferences.twoFactorEnabled : strings.preferences.twoFactorDisabled}
              </span>
            </span>
          }
        >
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
        </CollapsibleSection>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="preferences.pats" title={strings.preferences.pats}>
        <p className="text-muted">{strings.preferences.patsHint}</p>

        {pats.filter((p) => !p.revoked_at).length === 0 ? (
          <p className="text-muted">{strings.preferences.patNone}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{strings.preferences.patName}</th>
                <th>{strings.orgAdmin.organizations}</th>
                <th>{strings.preferences.patExpires}</th>
                <th>{strings.preferences.patLastUsed}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pats
                .filter((p) => !p.revoked_at)
                .map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.allowed_organizations.map((o) => o.name).join(", ")}</td>
                    <td>{new Date(p.expires_at).toLocaleDateString()}</td>
                    <td>{p.last_used_at ? new Date(p.last_used_at).toLocaleString() : strings.preferences.patNever}</td>
                    <td>
                      <button
                        className="btn btn-danger"
                        onClick={() => {
                          if (window.confirm(strings.preferences.patRevokeConfirm)) revokePat(p.id);
                        }}
                      >
                        {strings.preferences.patRevoke}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
        {pats.filter((p) => !p.revoked_at).length > 0 && (
          <button className="btn btn-danger" onClick={revokeAllPats} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.patRevokeAll}
          </button>
        )}

        <CollapsibleSection sectionKey="preferences.pats.create" variant="plain" title={strings.common.create}>
          <input
            className="input"
            placeholder={strings.preferences.patNamePlaceholder}
            value={newPatName}
            onChange={(e) => setNewPatName(e.target.value)}
          />
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.preferences.patOrgs}
            <div className="stack" style={{ gap: "0.25rem" }}>
              {myOrgs.map((org) => (
                <label key={org.id} className="row" style={{ gap: "0.5rem" }}>
                  <input
                    type="checkbox"
                    checked={newPatOrgIds.has(org.id)}
                    onChange={() => toggleNewPatOrg(org.id)}
                  />
                  {org.name}
                </label>
              ))}
            </div>
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.preferences.patExpiry}
            <input
              className="input"
              type="date"
              value={newPatExpiry}
              onChange={(e) => setNewPatExpiry(e.target.value)}
            />
            <span className="text-muted">{strings.preferences.patExpiryHint}</span>
          </label>
          {patError && <div style={{ color: "var(--color-danger)" }}>{patError}</div>}
          <button className="btn btn-primary" onClick={createPat} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.patCreate}
          </button>
        </CollapsibleSection>

        {createdPat && (
          <div className="stack" style={{ border: "1px solid var(--color-accent)", borderRadius: 6, padding: "0.75rem" }}>
            <strong>{strings.preferences.patCreatedTitle}</strong>
            <p className="text-muted">{strings.preferences.patCreatedHint}</p>
            <code style={{ wordBreak: "break-all", background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 4 }}>
              {createdPat.token}
            </code>
            <button className="btn" onClick={() => navigator.clipboard.writeText(createdPat.token)} style={{ alignSelf: "flex-start" }}>
              {strings.common.copy}
            </button>
            <button className="btn" onClick={() => setCreatedPat(null)} style={{ alignSelf: "flex-start" }}>
              {strings.common.cancel}
            </button>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection sectionKey="preferences.notifications" title={strings.notifications.preferencesTitle}>
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
      </CollapsibleSection>
    </div>
  );
}
