import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelPlural } from "../context/BrandingContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { t } from "../i18n/strings";
import type {
  DigestMode,
  MyMemberships,
  MyOrgGroup,
  NotificationPreference,
  OrgRole,
  OrgUser,
  Organization,
  PersonalAccessToken,
  PersonalAccessTokenCreateResult,
  ProjectListItem,
} from "../api/types";
import { ORG_ROLE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";

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
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
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
  const [notificationPrefsDirty, setNotificationPrefsDirty] = useState(false);
  const [notificationPrefsSaved, setNotificationPrefsSaved] = useState(false);

  const [myOrgs, setMyOrgs] = useState<Organization[]>([]);
  const [myOrgRoles, setMyOrgRoles] = useState<Record<string, OrgRole[]>>({});
  const [myGroupsByOrg, setMyGroupsByOrg] = useState<Record<string, MyOrgGroup[]>>({});
  const [pats, setPats] = useState<PersonalAccessToken[]>([]);
  const [newPatName, setNewPatName] = useState("");
  const [newPatOrgIds, setNewPatOrgIds] = useState<Set<string>>(new Set());
  const [newPatProjectIds, setNewPatProjectIds] = useState<Set<string>>(new Set());
  const [newPatExpiry, setNewPatExpiry] = useState("");
  const [expiryAutoFilled, setExpiryAutoFilled] = useState(true);
  const [maxExpiresAt, setMaxExpiresAt] = useState<string | null>(null);
  const [patError, setPatError] = useState<string | null>(null);
  const [createdPat, setCreatedPat] = useState<PersonalAccessTokenCreateResult | null>(null);

  useEffect(() => {
    api.get<NotificationPreference[]>("/api/v1/notifications/preferences").then(setNotificationPrefs);
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(setMyProjects);
    api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
    api.get<MyMemberships>("/api/v1/auth/me/memberships").then((memberships) => {
      setMyGroupsByOrg(
        Object.fromEntries(memberships.organizations.map((m) => [m.organization_id, m.groups]))
      );
    });
    api.get<Organization[]>("/api/v1/orgs").then(async (orgs) => {
      // `GET /orgs` returns every org on the deployment for a server admin
      // (I-M-05's platform-wide console view), not just orgs they're
      // actually a member of — right for the server-management pages that
      // originally called it, wrong here: this is a *personal* picker
      // ("which of MY orgs can this PAT reach"), so it's narrowed to
      // genuine memberships below. The org member directory (any org
      // role, including plain "member", can call this unfiltered per
      // `routers/orgs.py::list_org_users`) doubles as the membership test —
      // a 403 means "server admin can see this org platform-wide but
      // isn't actually in it," filtered out rather than left as an
      // unhandled rejection that used to abort the whole batch.
      const entries = await Promise.all(
        orgs.map(async (org) => {
          try {
            const orgUsers = await api.get<OrgUser[]>(`/api/v1/orgs/${org.id}/users`);
            const self = orgUsers.find((u) => u.user_id === user?.id);
            return self ? ([org, self.roles] as const) : null;
          } catch (err) {
            if (err instanceof ApiError && err.status === 403) return null;
            throw err;
          }
        })
      );
      const memberships = entries.filter((e): e is readonly [Organization, OrgRole[]] => e !== null);
      setMyOrgs(memberships.map(([org]) => org));
      setMyOrgRoles(Object.fromEntries(memberships.map(([org, roles]) => [org.id, roles])));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggleNewPatOrg(orgId: string) {
    setNewPatOrgIds((current) => {
      const next = new Set(current);
      if (next.has(orgId)) next.delete(orgId);
      else next.add(orgId);
      // A project only makes sense as a scope alongside its own org — drop
      // any selected project whose org just got deselected, rather than
      // silently submitting a project id the org list no longer explains.
      setNewPatProjectIds((currentProjects) => {
        const stillValidOrgIds = next;
        const nextProjects = new Set(
          Array.from(currentProjects).filter((pid) => {
            const project = myProjects.find((p) => p.id === pid);
            return project && stillValidOrgIds.has(project.organization_id);
          })
        );
        return nextProjects;
      });
      return next;
    });
  }

  function toggleNewPatProject(projectId: string) {
    setNewPatProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  }

  // Refetches the longest-allowed expiry whenever the selected orgs
  // change, and pre-fills the date field with it — replacing the old
  // "leave blank to use the longest lifetime allowed" convention, which
  // made the user do the lookup themselves instead of just seeing the
  // actual date. Only overwrites the field while it still holds a
  // previous auto-filled value (or is empty) — a value the user typed in
  // themselves is left alone.
  useEffect(() => {
    if (newPatOrgIds.size === 0) {
      setMaxExpiresAt(null);
      return;
    }
    const params = new URLSearchParams();
    for (const orgId of newPatOrgIds) params.append("organization_ids", orgId);
    api.get<{ max_expires_at: string }>(`/api/v1/me/pats/max-lifetime?${params.toString()}`).then(({ max_expires_at }) => {
      setMaxExpiresAt(max_expires_at);
      if (expiryAutoFilled) setNewPatExpiry(max_expires_at.slice(0, 10));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPatOrgIds]);

  const expiryTooLong = !!(maxExpiresAt && newPatExpiry && new Date(newPatExpiry) > new Date(maxExpiresAt));

  async function createPat() {
    setPatError(null);
    if (newPatOrgIds.size === 0) {
      setPatError(strings.preferences.patNoOrgsSelected(orgLabel));
      return;
    }
    try {
      const created = await api.post<PersonalAccessTokenCreateResult>("/api/v1/me/pats", {
        name: newPatName,
        allowed_organization_ids: Array.from(newPatOrgIds),
        allowed_project_ids: Array.from(newPatProjectIds),
        requested_expires_at: newPatExpiry ? new Date(newPatExpiry).toISOString() : undefined,
      });
      setCreatedPat(created);
      setNewPatName("");
      setNewPatOrgIds(new Set());
      setNewPatProjectIds(new Set());
      setNewPatExpiry("");
      setExpiryAutoFilled(true);
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

  // Edits are staged locally and only sent on `saveNotificationPrefs` — this
  // used to PUT on every single checkbox click, which made "toggle every
  // row in a column at once" fire one request per row with no way to tell
  // the user it had finished (and no undo if they changed their mind
  // mid-click).
  function updateNotificationPref(type: string, field: "ui_enabled" | "email_enabled", value: boolean) {
    setNotificationPrefs((prefs) => prefs.map((p) => (p.type === type ? { ...p, [field]: value } : p)));
    setNotificationPrefsDirty(true);
    setNotificationPrefsSaved(false);
  }

  function toggleAllNotificationPrefs(field: "ui_enabled" | "email_enabled") {
    const allEnabled = notificationPrefs.every((p) => p[field]);
    setNotificationPrefs((prefs) => prefs.map((p) => ({ ...p, [field]: !allEnabled })));
    setNotificationPrefsDirty(true);
    setNotificationPrefsSaved(false);
  }

  async function saveNotificationPrefs() {
    await Promise.all(
      notificationPrefs.map((p) =>
        api.put(`/api/v1/notifications/preferences/${p.type}`, {
          ui_enabled: p.ui_enabled, email_enabled: p.email_enabled,
        })
      )
    );
    setNotificationPrefsDirty(false);
    setNotificationPrefsSaved(true);
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

  const [tab, setTab] = useState<"profile" | "security" | "access" | "pats" | "notifications">("profile");

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "profile", label: strings.preferences.profile },
    { key: "security", label: strings.preferences.security },
    { key: "access", label: strings.preferences.access },
    { key: "pats", label: strings.preferences.pats },
    { key: "notifications", label: strings.notifications.preferencesTitle },
  ];

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.preferences.title}</h1>

      <div className="row" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
        {tabs.map((tb) => (
          <button
            key={tb.key}
            className={`btn ${tab === tb.key ? "btn-primary" : ""}`}
            onClick={() => setTab(tb.key)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "profile" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.profile}</h2>
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
          {user?.display_name_locked && <span className="text-muted">{strings.preferences.displayNameLocked(orgLabel)}</span>}
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
      </div>
      )}

      {tab === "security" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.security}</h2>
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
              <ToggleSwitch
                checked={!!user?.is_2fa_enabled || !!enrollment}
                // Disabled once already on: turning 2FA *off* requires a
                // live TOTP code (below), so a bare toggle can't safely do
                // it in one click — this switch only ever drives the
                // enrollment flow on, never disables silently.
                disabled={!!user?.is_2fa_enabled || !!enrollment}
                onChange={() => startEnrollment()}
                label={strings.preferences.enable2fa}
              />
              <span className="badge">
                {user?.is_2fa_enabled ? strings.preferences.twoFactorEnabled : strings.preferences.twoFactorDisabled}
              </span>
            </span>
          }
        >
          {twoFactorError && <div style={{ color: "var(--color-danger)" }}>{twoFactorError}</div>}

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
      </div>
      )}

      {tab === "access" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.access}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.preferences.accessHint(orgLabel)}</p>
        {myOrgs.length === 0 && <p className="text-muted">{strings.orgAdmin.noOrganizations(orgLabelPlural)}</p>}
        {myOrgs.map((org) => {
          const roles = myOrgRoles[org.id] ?? [];
          const orgProjects = myProjects.filter((p) => p.organization_id === org.id);
          return (
            <div key={org.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.75rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  <strong>{org.name}</strong>{" "}
                  {roles.map((r) => (
                    <span key={r} className="badge">{ORG_ROLE_LABEL[r]}</span>
                  ))}
                </span>
                {roles.includes("org_admin") && (
                  <Link to={`/orgs/${org.id}/admin`} className="btn">{strings.preferences.manageOrganisation(orgLabel)}</Link>
                )}
              </div>
              {orgProjects.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {orgProjects.map((p) => (
                    <li key={p.id} style={{ listStyle: "disc" }}>
                      <Link to={`/projects/${p.id}`}>{p.name}</Link>{" "}
                      <span className="text-muted">
                        ({p.my_roles.map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {(myGroupsByOrg[org.id] ?? []).length > 0 && (
                <div className="stack" style={{ gap: "0.25rem" }}>
                  <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.preferences.myGroups}</span>
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {(myGroupsByOrg[org.id] ?? []).map((g) => (
                      <li key={g.id} style={{ listStyle: "circle" }}>
                        {g.name}
                        {!g.direct && <span className="text-muted"> ({strings.preferences.inheritedGroup})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
      )}

      {tab === "pats" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.pats}</h2>
        <p className="text-muted">{strings.preferences.patsHint(orgLabel)}</p>

        {pats.filter((p) => !p.revoked_at).length === 0 ? (
          <p className="text-muted">{strings.preferences.patNone}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{strings.preferences.patName}</th>
                <th>{strings.orgAdmin.organizations(orgLabelPlural)}</th>
                <th>{strings.preferences.patProjects}</th>
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
                    <td>{p.allowed_projects.length > 0 ? p.allowed_projects.map((pr) => pr.name).join(", ") : strings.preferences.patAllProjects}</td>
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
            {strings.preferences.patOrgs(orgLabelPlural)}
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
          {newPatOrgIds.size > 0 && (
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.preferences.patProjects}
              {(() => {
                const scopedProjects = myProjects.filter((p) => newPatOrgIds.has(p.organization_id));
                return scopedProjects.length === 0 ? (
                  <span className="text-muted">{strings.preferences.patNoProjectsInOrgs(orgLabel)}</span>
                ) : (
                  <div className="stack" style={{ gap: "0.25rem" }}>
                    {scopedProjects.map((project) => (
                      <label key={project.id} className="row" style={{ gap: "0.5rem" }}>
                        <input
                          type="checkbox"
                          checked={newPatProjectIds.has(project.id)}
                          onChange={() => toggleNewPatProject(project.id)}
                        />
                        {project.name}
                      </label>
                    ))}
                  </div>
                );
              })()}
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.preferences.patProjectsHint(orgLabelPlural)}</span>
            </label>
          )}
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.preferences.patExpiry}
            <input
              className="input"
              type="date"
              value={newPatExpiry}
              onChange={(e) => {
                setExpiryAutoFilled(false);
                setNewPatExpiry(e.target.value);
              }}
            />
            {expiryTooLong && maxExpiresAt && (
              <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>
                {strings.preferences.patExpiryTooLong(orgLabelPlural).replace(
                  "{date}", new Date(maxExpiresAt).toLocaleDateString()
                )}
              </span>
            )}
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
      </div>
      )}

      {tab === "notifications" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.notifications.preferencesTitle}</h2>
        <table>
          <thead>
            <tr>
              <th></th>
              <th>
                <div className="stack" style={{ gap: "0.25rem", alignItems: "center" }}>
                  {strings.notifications.ui}
                  <button className="btn" onClick={() => toggleAllNotificationPrefs("ui_enabled")}>
                    {strings.notifications.toggleAll}
                  </button>
                </div>
              </th>
              <th>
                <div className="stack" style={{ gap: "0.25rem", alignItems: "center" }}>
                  {strings.notifications.email}
                  <button className="btn" onClick={() => toggleAllNotificationPrefs("email_enabled")}>
                    {strings.notifications.toggleAll}
                  </button>
                </div>
              </th>
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
        <button
          className="btn btn-primary"
          onClick={saveNotificationPrefs}
          disabled={!notificationPrefsDirty}
          style={{ alignSelf: "flex-start" }}
        >
          {strings.preferences.save}
        </button>
        {notificationPrefsSaved && <div style={{ color: "var(--color-accent)" }}>{strings.preferences.saved}</div>}
      </div>
      )}
    </div>
  );
}
