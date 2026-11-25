import { Plus, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FileUploadTrigger } from "../components/FileUploadTrigger";
import { Modal } from "../components/Modal";
import { OneTimeSecret } from "../components/OneTimeSecret";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelPlural } from "../context/BrandingContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { PROJECT_SCOPES, parseProjectScope } from "../api/projectScope";
import { DEFAULT_NEW_PROJECT_ORG_PREFERENCE } from "../hooks/defaultProjectOrganization";
import { DEFAULT_PROJECT_SCOPE_PREFERENCE } from "../hooks/useProjectScope";
import { SHOW_PROJECT_CODE_PREFERENCE } from "../hooks/useRecordCode";
import { useUiPreference } from "../hooks/useUiPreference";
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
import { collapseProjectRoles, ORG_ROLE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { Badge } from "../components/Badge";
import { CheckboxField, DateField, TextField } from "../components/FormFields";
import { LabeledSelect } from "../components/LabeledSelect";
import { SearchPreferencesPanel } from "../components/SearchPreferencesPanel";
import { FormGrid, FormGridFull } from "../components/FormGrid";
import { FormActions } from "../components/FormActions";
import { useLoadOnChange } from "../hooks/useLoadOnChange";

type LandingMode = "auto" | "overview" | "project";

function landingModeFor(preference: string | undefined): LandingMode {
  if (!preference || preference === "auto") return "auto";
  if (preference === "overview") return "overview";
  return "project";
}

/**
 * The `ResourceMenu` groups. Each key is the route segment under `/preferences/:group?` (App.tsx), so a
 * selection is a real navigation; an unrecognised or absent `:group` falls back to "profile". The page uses
 * `ResourceMenu` like the other admin-tier pages (`docs/ux-style-guide.md` Principle 1).
 */
type PreferencesGroupKey = "profile" | "search" | "security" | "access" | "pats" | "notifications";

const PREFERENCES_GROUP_KEYS: PreferencesGroupKey[] = ["profile", "search", "security", "access", "pats", "notifications"];

/** User preferences: theme (U-U-01), landing page (U-U-03), pronouns (C-U-18), email digest (C-N-05), password change and TOTP enrolment (C-U-14). */
export function PreferencesPage() {
  const strings = useStrings();
  const { group: groupParam } = useParams<{ group?: string }>();
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const { showToast } = useToast();
  const [avatarError, setAvatarError] = useState<string | null>(null);
  // Tier 1 `ConfirmDialog` state for the two token actions below.
  const [patToRevoke, setPatToRevoke] = useState<string | null>(null);
  const [revokeAllPatsOpen, setRevokeAllPatsOpen] = useState(false);
  const [contentBoxed, setContentBoxed] = useUiPreference<boolean>("content_boxed", false);
  const [showProjectCode, setShowProjectCode] = useUiPreference<boolean>(SHOW_PROJECT_CODE_PREFERENCE, true);
  const [storedProjectScope, setDefaultProjectScope] = useUiPreference<string>(DEFAULT_PROJECT_SCOPE_PREFERENCE, "this");
  const defaultProjectScope = parseProjectScope(storedProjectScope) ?? "this";
  const [storedNewProjectOrg, setDefaultNewProjectOrg] = useUiPreference<string>(DEFAULT_NEW_PROJECT_ORG_PREFERENCE, "");
  // The active organisations the New project dialog offers (the same `mine=true` read).
  const [creatableOrgs, setCreatableOrgs] = useState<Organization[]>([]);
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
  // "Leave organisation" Tier 1 `ConfirmDialog`; holds the whole `Organization` so the dialog can name it.
  const [orgToLeave, setOrgToLeave] = useState<Organization | null>(null);
  const [pats, setPats] = useState<PersonalAccessToken[]>([]);
  const [newPatName, setNewPatName] = useState("");
  const [newPatOrgIds, setNewPatOrgIds] = useState<Set<string>>(new Set());
  const [newPatProjectIds, setNewPatProjectIds] = useState<Set<string>>(new Set());
  const [newPatExpiry, setNewPatExpiry] = useState("");
  const [expiryAutoFilled, setExpiryAutoFilled] = useState(true);
  const [fetchedMaxExpiresAt, setMaxExpiresAt] = useState<string | null>(null);
  const [patError, setPatError] = useState<string | null>(null);
  const [createdPat, setCreatedPat] = useState<PersonalAccessTokenCreateResult | null>(null);
  // The "New personal access token" form creates a new entity, so it opens in a `Modal` (Principle 3).
  const [patFormOpen, setPatFormOpen] = useState(false);

  /**
   * Loads everything the "Your access" tab shows (projects, organisation memberships and roles, groups).
   * `leaveOrg` calls it again so a left organisation, and projects reachable only through it, disappear.
   */
  async function loadMyAccess() {
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then(setMyProjects);
    api.get<Organization[]>("/api/v1/orgs?mine=true").then((list) => setCreatableOrgs(list.filter((o) => o.is_active)));
    api.get<MyMemberships>("/api/v1/auth/me/memberships").then((memberships) => {
      setMyGroupsByOrg(
        Object.fromEntries(memberships.organizations.map((m) => [m.organization_id, m.groups]))
      );
    });
    const orgs = await api.get<Organization[]>("/api/v1/orgs");
    // `GET /orgs` returns every organisation to a server administrator (I-M-05), but this is a personal
    // picker, so it is narrowed to real memberships. The member directory (open to any organisation role,
    // `routers/orgs.py::list_org_users`) is the membership test: a 403 means the administrator is not a
    // member, and is filtered out instead of aborting the batch.
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
  }

  useLoadOnChange(() => {
    api.get<NotificationPreference[]>("/api/v1/notifications/preferences").then(setNotificationPrefs);
    api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
    loadMyAccess();
  }, []);

  async function leaveOrg(orgId: string) {
    setOrgToLeave(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/membership`);
      showToast(strings.preferences.leftOrgToast(orgLabel));
      await loadMyAccess();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  function toggleNewPatOrg(orgId: string) {
    setNewPatOrgIds((current) => {
      const next = new Set(current);
      if (next.has(orgId)) next.delete(orgId);
      else next.add(orgId);
      // A project is a scope only alongside its organisation: drop selected projects whose organisation was deselected.
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

  // Refetches the longest allowed expiry when the selected organisations change and pre-fills the date
  // with it; the field is overwritten only while it is empty or still holds an earlier pre-filled value.
  const maxExpiresAt = newPatOrgIds.size === 0 ? null : fetchedMaxExpiresAt;

  useEffect(() => {
    if (newPatOrgIds.size === 0) return;
    const params = new URLSearchParams();
    for (const orgId of newPatOrgIds) params.append("organization_ids", orgId);
    api.get<{ max_expires_at: string }>(`/api/v1/me/pats/max-lifetime?${params.toString()}`).then(({ max_expires_at }) => {
      setMaxExpiresAt(max_expires_at);
      if (expiryAutoFilled) setNewPatExpiry(max_expires_at.slice(0, 10));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newPatOrgIds]);

  const expiryTooLong = !!(maxExpiresAt && newPatExpiry && new Date(newPatExpiry) > new Date(maxExpiresAt));

  function resetPatForm() {
    setNewPatName("");
    setNewPatOrgIds(new Set());
    setNewPatProjectIds(new Set());
    setNewPatExpiry("");
    setExpiryAutoFilled(true);
    setPatError(null);
  }

  function openPatForm() {
    resetPatForm();
    setPatFormOpen(true);
  }

  function closePatForm() {
    resetPatForm();
    setPatFormOpen(false);
  }

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
      closePatForm();
      api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
    } catch (err) {
      setPatError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function revokePat(id: string) {
    setPatToRevoke(null);
    try {
      await api.delete(`/api/v1/me/pats/${id}`);
      setPats((current) => current.map((p) => (p.id === id ? { ...p, revoked_at: new Date().toISOString() } : p)));
      showToast(strings.preferences.patRevokedToast);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function revokeAllPats() {
    setRevokeAllPatsOpen(false);
    try {
      await api.post("/api/v1/me/pats/revoke-all");
      api.get<PersonalAccessToken[]>("/api/v1/me/pats").then(setPats);
      showToast(strings.preferences.patRevokedAllToast);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // Edits are staged locally and sent once by `saveNotificationPrefs`, so toggling a whole column is one request.
  function updateNotificationPref(type: string, field: "ui_enabled" | "email_enabled", value: boolean) {
    setNotificationPrefs((prefs) => prefs.map((p) => (p.type === type ? { ...p, [field]: value } : p)));
    setNotificationPrefsDirty(true);
    setNotificationPrefsSaved(false);
  }

  /** Core types are labelled by the (terminology-aware) string table; a module-registered type carries its own label. */
  function notificationTypeLabel(p: NotificationPreference): string {
    return (strings.notifications.types as Record<string, string>)[p.type] ?? p.label ?? p.type;
  }

  function toggleAllNotificationPrefs(field: "ui_enabled" | "email_enabled") {
    const allEnabled = notificationPrefs.every((p) => p[field]);
    setNotificationPrefs((prefs) => prefs.map((p) => ({ ...p, [field]: !allEnabled })));
    setNotificationPrefsDirty(true);
    setNotificationPrefsSaved(false);
  }

  async function saveNotificationPrefs() {
    try {
      await Promise.all(
        notificationPrefs.map((p) =>
          api.put(`/api/v1/notifications/preferences/${p.type}`, {
            ui_enabled: p.ui_enabled, email_enabled: p.email_enabled,
          })
        )
      );
      setNotificationPrefsDirty(false);
      setNotificationPrefsSaved(true);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
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
      // A password change invalidates every earlier token, including this session's (User.token_version),
      // so the person signs in again.
      logout();
      navigate("/login", { state: { message: strings.login.reauthRequired } });
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function startEnrollment() {
    setTwoFactorError(null);
    try {
      const result = await api.post<{ secret: string; qr_code_png_base64: string }>("/api/v1/auth/2fa/enroll");
      setEnrollment({ secret: result.secret, qrCodePngBase64: result.qr_code_png_base64 });
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function confirmEnrollment() {
    setTwoFactorError(null);
    try {
      await api.post("/api/v1/auth/2fa/status", { action: "confirm", code: confirmCode });
      setEnrollment(null);
      setConfirmCode("");
      showToast(strings.mutation.success("two-factor authentication", strings.mutation.past.enable));
      await refreshUser();
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function disable2fa() {
    setTwoFactorError(null);
    try {
      await api.post("/api/v1/auth/2fa/status", { action: "disable", code: disableCode });
      // Disabling 2FA also bumps `token_version`, ending this session.
      logout();
      navigate("/login", { state: { message: strings.login.reauthRequired } });
    } catch (err) {
      setTwoFactorError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  const activeGroup: PreferencesGroupKey = PREFERENCES_GROUP_KEYS.includes(groupParam as PreferencesGroupKey)
    ? (groupParam as PreferencesGroupKey)
    : "profile";

  const groups: ResourceMenuGroupDef<PreferencesGroupKey>[] = [
    { key: "profile", label: strings.preferences.profile, href: "/preferences/profile" },
    { key: "search", label: strings.preferences.searchGroup, href: "/preferences/search" },
    { key: "security", label: strings.preferences.security, href: "/preferences/security" },
    { key: "access", label: strings.preferences.access, href: "/preferences/access" },
    { key: "pats", label: strings.preferences.pats, href: "/preferences/pats" },
    { key: "notifications", label: strings.notifications.preferencesTitle, href: "/preferences/notifications" },
  ];

  return (
    <div className="stack">
      <ResourceMenu
        title={strings.preferences.title}
        ariaLabel={strings.preferences.sectionsNav}
        groups={groups}
        active={activeGroup}
      >
      {activeGroup === "profile" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.profile}</h2>
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{strings.preferences.avatar}</span>
          <div className="row">
            {user?.avatar_file_id && (
              <img
                src={fileUrl(user.avatar_file_id)}
                alt="avatar"
                style={{ width: 48, height: 48, borderRadius: "50%", objectFit: "cover" }}
              />
            )}
            <FileUploadTrigger
              accept="image/*"
              onSelect={async (file) => {
                setAvatarError(null);
                try {
                  await api.postFile("/api/v1/auth/me/avatar", file);
                  await refreshUser();
                } catch (err) {
                  setAvatarError(err instanceof ApiError ? err.message : strings.common.error);
                }
              }}
            >
              <Upload size={14} /> {strings.common.chooseFile}
            </FileUploadTrigger>
          </div>
          {avatarError && <div style={{ color: "var(--color-danger)" }}>{avatarError}</div>}
        </div>
        <FormGrid minColumn="18rem">
          <TextField helpNotNeeded
            label={strings.preferences.displayName}
            value={displayName}
            onChange={setDisplayName}
            disabled={user?.display_name_locked}
            hint={user?.display_name_locked ? strings.preferences.displayNameLocked(orgLabel) : undefined}
          />
          <TextField help={strings.help.pronouns} label={strings.preferences.pronouns} value={pronouns} onChange={setPronouns} />
          <LabeledSelect helpNotNeeded
            label={strings.preferences.theme}
            value={theme}
            onChange={(next) => setTheme(next as ThemePreference)}
            options={[{ value: "light", label: strings.preferences.light }, { value: "dark", label: strings.preferences.dark }, { value: "system", label: strings.preferences.system }]}
            placeholder={null}
          />
          <LabeledSelect help={strings.help.contentWidth}
            label={strings.preferences.contentWidth}
            value={contentBoxed ? "boxed" : "full"}
            onChange={(next) => setContentBoxed(next === "boxed")}
            options={[{ value: "full", label: strings.preferences.contentWidthFull }, { value: "boxed", label: strings.preferences.contentWidthBoxed }]}
            placeholder={null}
          />
          <FormGridFull>
            <CheckboxField help={strings.help.showProjectCode}
              label={strings.preferences.showProjectCode}
              checked={showProjectCode}
              onChange={setShowProjectCode}
            />
          </FormGridFull>
          <LabeledSelect help={strings.help.defaultProjectScope}
            label={strings.preferences.defaultProjectScope}
            value={defaultProjectScope}
            onChange={setDefaultProjectScope}
            options={PROJECT_SCOPES.map((scope) => ({ value: scope, label: strings.projectScope.options[scope] }))}
            placeholder={null}
          />
          {creatableOrgs.length > 1 && (
            <LabeledSelect help={strings.help.defaultNewProjectOrg(orgLabel)}
              label={strings.preferences.defaultNewProjectOrg(orgLabel)}
              value={creatableOrgs.some((o) => o.id === storedNewProjectOrg) ? storedNewProjectOrg : ""}
              onChange={setDefaultNewProjectOrg}
              options={creatableOrgs.map((o) => ({ value: o.id, label: o.name }))}
              placeholder={strings.preferences.defaultNewProjectOrgNone(orgLabel)}
            />
          )}
          <LabeledSelect help={strings.help.landingPage}
            label={strings.preferences.landing}
            value={landingMode}
            onChange={(next) => setLandingMode(next as LandingMode)}
            options={[{ value: "auto", label: strings.preferences.landingAuto }, { value: "overview", label: strings.preferences.landingOverview }, { value: "project", label: strings.preferences.landingProject }]}
            placeholder={null}
          />
          {landingMode === "project" && (
            <LabeledSelect helpNotNeeded
              label={strings.preferences.landingProjectSelect}
              value={landingProjectId}
              onChange={setLandingProjectId}
              options={myProjects.map((p) => ({ value: p.id, label: p.name }))}
              placeholder={null}
            />
          )}
          <LabeledSelect help={strings.help.emailDigest}
            label={strings.preferences.emailDigest}
            value={digestMode}
            onChange={(next) => setDigestMode(next as DigestMode)}
            options={[{ value: "instant", label: strings.preferences.digestInstant }, { value: "daily", label: strings.preferences.digestDaily }, { value: "none", label: strings.preferences.digestNone }]}
            placeholder={null}
          />
        </FormGrid>
        {profileError && <div style={{ color: "var(--color-danger)" }}>{profileError}</div>}
        <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
          {strings.preferences.save}
        </button>
        {saved && <div style={{ color: "var(--color-accent)" }}>{strings.preferences.saved}</div>}
      </div>
      )}

      {activeGroup === "search" && <SearchPreferencesPanel />}

      {activeGroup === "security" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.security}</h2>
        <CollapsibleSection sectionKey="preferences.security.change_password" variant="plain" title={strings.preferences.changePassword}>
          <FormGrid minColumn="18rem">
            <TextField helpNotNeeded
              label={strings.preferences.currentPassword}
              value={currentPassword}
              onChange={setCurrentPassword}
              inputProps={{ type: "password" }}
            />
            <TextField helpNotNeeded
              label={strings.preferences.newPassword}
              value={newPassword}
              onChange={setNewPassword}
              inputProps={{ type: "password" }}
            />
          </FormGrid>
          {passwordError && <div style={{ color: "var(--color-danger)" }}>{passwordError}</div>}
          <button className="btn" onClick={changePassword} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.changePassword}
          </button>
        </CollapsibleSection>

        <CollapsibleSection
          sectionKey="preferences.security.two_factor"
          variant="plain"
          title={
            <span className="row" style={{ gap: "var(--space-3)" }}>
              {strings.preferences.twoFactor}
              <ToggleSwitch
                checked={!!user?.is_2fa_enabled || !!enrollment}
                // Disabled once on: turning 2FA off needs a TOTP code (below), so this switch only starts enrolment.
                disabled={!!user?.is_2fa_enabled || !!enrollment}
                onChange={() => startEnrollment()}
                label={strings.preferences.enable2fa}
              />
              <Badge>
                {user?.is_2fa_enabled ? strings.preferences.twoFactorEnabled : strings.preferences.twoFactorDisabled}
              </Badge>
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
              <div className="row" style={{ alignItems: "flex-end" }}>
                <TextField helpNotNeeded
                  label={strings.preferences.confirmCode}
                  value={confirmCode}
                  onChange={setConfirmCode}
                  inputProps={{ style: { maxWidth: 160 } }}
                />
                <button className="btn btn-primary" onClick={confirmEnrollment}>
                  {strings.preferences.confirmCode}
                </button>
              </div>
            </div>
          )}

          {user?.is_2fa_enabled && (
            <div className="row" style={{ alignItems: "flex-end" }}>
              <TextField helpNotNeeded
                label={strings.preferences.authenticatorCode}
                hint={strings.preferences.enterCodeToDisable}
                value={disableCode}
                onChange={setDisableCode}
                inputProps={{ style: { maxWidth: 160 } }}
              />
              <button className="btn btn-danger" onClick={disable2fa}>
                {strings.preferences.disable2fa}
              </button>
            </div>
          )}
        </CollapsibleSection>
      </div>
      )}

      {activeGroup === "access" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.access}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.preferences.accessHint(orgLabel)}</p>
        {myOrgs.length === 0 && <p className="text-muted">{strings.orgAdmin.noOrganizations(orgLabelPlural)}</p>}
        {myOrgs.map((org) => {
          const roles = myOrgRoles[org.id] ?? [];
          const orgProjects = myProjects.filter((p) => p.organization_id === org.id);
          return (
            <div key={org.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-4)" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  <strong>{org.name}</strong>{" "}
                  {roles.map((r) => (
                    <Badge key={r}>{ORG_ROLE_LABEL[r]}</Badge>
                  ))}
                </span>
                <div className="row" style={{ gap: "var(--space-2)" }}>
                  {roles.includes("org_admin") && (
                    <Link to={`/orgs/${org.id}/admin`} className="btn">{strings.preferences.manageOrganisation(orgLabel)}</Link>
                  )}
                  {/* Leaving is the person's own membership, not an organisation setting; it asks a Tier 1
                      `ConfirmDialog` and ends with a `Toast`. */}
                  <button
                    className="btn btn-danger"
                    onClick={() => setOrgToLeave(org)}
                    title={strings.preferences.leaveOrgTooltip(org.name)}
                    aria-label={strings.preferences.leaveOrgAriaLabel(org.name)}
                  >
                    {strings.preferences.leaveOrg}
                  </button>
                </div>
              </div>
              {orgProjects.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {orgProjects.map((p) => (
                    <li key={p.id} style={{ listStyle: "disc" }}>
                      <Link to={`/projects/${p.id}`}>{p.name}</Link>{" "}
                      <span className="text-muted">
                        ({collapseProjectRoles(p.my_roles).map((r) => PROJECT_ROLE_LABEL[r]).join(", ") || "—"})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {(myGroupsByOrg[org.id] ?? []).length > 0 && (
                <div className="stack" style={{ gap: "var(--space-1)" }}>
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

      {activeGroup === "pats" && (
      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.preferences.pats}</h2>
            <p className="text-muted" style={{ margin: 0 }}>{strings.preferences.patsHint(orgLabel)}</p>
          </div>
          <button className="btn btn-primary" onClick={openPatForm}>
            <Plus /> {strings.preferences.patNew}
          </button>
        </div>

        {pats.filter((p) => !p.revoked_at).length === 0 ? (
          <p className="text-muted">{strings.preferences.patNone}</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
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
                        onClick={() => setPatToRevoke(p.id)}
                      >
                        {strings.preferences.patRevoke}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          </div>
        )}
        {pats.filter((p) => !p.revoked_at).length > 0 && (
          <button className="btn btn-danger" onClick={() => setRevokeAllPatsOpen(true)} style={{ alignSelf: "flex-start" }}>
            {strings.preferences.patRevokeAll}
          </button>
        )}

        {patFormOpen && (
          <Modal title={strings.preferences.patNew} onClose={closePatForm} size="lg">
            <div className="stack">
              <FormGrid minColumn="18rem">
                <TextField helpNotNeeded
                  label={strings.preferences.patName}
                  placeholder={strings.preferences.patNamePlaceholder}
                  value={newPatName}
                  onChange={setNewPatName}
                />
                <DateField help={strings.help.tokenExpiry}
                  label={strings.preferences.patExpiry}
                  value={newPatExpiry}
                  onChange={(next) => {
                    setExpiryAutoFilled(false);
                    setNewPatExpiry(next);
                  }}
                  hint={
                    expiryTooLong && maxExpiresAt ? (
                      <span style={{ color: "var(--color-danger)" }}>
                        {strings.preferences.patExpiryTooLong(orgLabelPlural).replace(
                          "{date}", new Date(maxExpiresAt).toLocaleDateString()
                        )}
                      </span>
                    ) : undefined
                  }
                />
                <FormGridFull>
                  <div className="stack" style={{ gap: "var(--space-1)" }}>
                    <span>{strings.preferences.patOrgs(orgLabelPlural)}</span>
                    {myOrgs.map((org) => (
                      <CheckboxField helpNotNeeded
                        key={org.id}
                        label={org.name}
                        checked={newPatOrgIds.has(org.id)}
                        onChange={() => toggleNewPatOrg(org.id)}
                      />
                    ))}
                  </div>
                </FormGridFull>
                {newPatOrgIds.size > 0 && (
                  <FormGridFull>
                    <div className="stack" style={{ gap: "var(--space-1)" }}>
                      <span>{strings.preferences.patProjects}</span>
                      {(() => {
                        const scopedProjects = myProjects.filter((p) => newPatOrgIds.has(p.organization_id));
                        return scopedProjects.length === 0 ? (
                          <span className="text-muted">{strings.preferences.patNoProjectsInOrgs(orgLabel)}</span>
                        ) : (
                          scopedProjects.map((project) => (
                            <CheckboxField helpNotNeeded
                              key={project.id}
                              label={project.name}
                              checked={newPatProjectIds.has(project.id)}
                              onChange={() => toggleNewPatProject(project.id)}
                            />
                          ))
                        );
                      })()}
                      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.preferences.patProjectsHint(orgLabelPlural)}</span>
                    </div>
                  </FormGridFull>
                )}
              </FormGrid>
              <FormActions
                error={patError}
                onCancel={closePatForm}
                onSave={createPat}
                saveLabel={strings.preferences.patCreate}
              />
            </div>
          </Modal>
        )}

        {createdPat && (
          <OneTimeSecret
            title={strings.preferences.patCreatedTitle}
            hint={strings.preferences.patCreatedHint}
            secret={createdPat.token}
            dismissLabel={strings.common.close}
            onDismiss={() => setCreatedPat(null)}
          />
        )}
      </div>
      )}

      {activeGroup === "notifications" && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.notifications.preferencesTitle}</h2>
        <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th></th>
              <th>
                <div className="stack" style={{ gap: "var(--space-1)", alignItems: "center" }}>
                  {strings.notifications.ui}
                  <button className="btn" onClick={() => toggleAllNotificationPrefs("ui_enabled")}>
                    {strings.notifications.toggleAll}
                  </button>
                </div>
              </th>
              <th>
                <div className="stack" style={{ gap: "var(--space-1)", alignItems: "center" }}>
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
                <td>{notificationTypeLabel(p)}</td>
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
      </ResourceMenu>

      {orgToLeave && (
        <ConfirmDialog
          title={strings.preferences.leaveOrgTitle(orgToLeave.name)}
          message={strings.preferences.leaveOrgConfirm(orgLabel)}
          confirmLabel={strings.preferences.leaveOrg}
          onConfirm={() => leaveOrg(orgToLeave.id)}
          onCancel={() => setOrgToLeave(null)}
        />
      )}
      {patToRevoke && (
        <ConfirmDialog
          title={strings.preferences.patRevokeTitle}
          message={strings.preferences.patRevokeConfirm}
          confirmLabel={strings.preferences.patRevoke}
          onConfirm={() => revokePat(patToRevoke)}
          onCancel={() => setPatToRevoke(null)}
        />
      )}
      {revokeAllPatsOpen && (
        <ConfirmDialog
          title={strings.preferences.patRevokeAllTitle}
          message={strings.preferences.patRevokeAllConfirm}
          confirmLabel={strings.preferences.patRevokeAll}
          onConfirm={revokeAllPats}
          onCancel={() => setRevokeAllPatsOpen(false)}
        />
      )}
    </div>
  );
}
