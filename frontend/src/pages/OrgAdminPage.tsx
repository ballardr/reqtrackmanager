import { Lock, LogOut, Plus, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type {
  FileAsset,
  OrgAdvancedSettings,
  OrgGroup,
  OrgPersonalAccessToken,
  OrgReportDefaults,
  OrgRole,
  OrgSsoConfig,
  OrgUser,
  Organization,
  ProjectListItem,
  ReportChapter,
  ReportTemplate,
} from "../api/types";
import { ORG_ROLE_LABEL } from "../api/types";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import { RichTextEditor } from "../components/RichTextEditor";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Organisation administration: users (C-U-01), groups (C-U-08), shared
 * resource files (C-M-03), the organisation logo (U-C-02), and the default
 * template project used for new projects (C-E-04).
 */
export function OrgAdminPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [org, setOrg] = useState<Organization | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [degradedOrgName, setDegradedOrgName] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [enableError, setEnableError] = useState<string | null>(null);
  const [enabling, setEnabling] = useState(false);
  const [bootstrapEmail, setBootstrapEmail] = useState("");
  const [bootstrapName, setBootstrapName] = useState("");
  const [bootstrapPassword, setBootstrapPassword] = useState("");
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [bootstrapCreated, setBootstrapCreated] = useState(false);
  const [leaveError, setLeaveError] = useState<string | null>(null);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [groups, setGroups] = useState<OrgGroup[]>([]);
  const [resources, setResources] = useState<FileAsset[]>([]);
  const [templateProjects, setTemplateProjects] = useState<ProjectListItem[]>([]);

  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [groupMemberInputs, setGroupMemberInputs] = useState<Record<string, string>>({});

  const [advanced, setAdvanced] = useState<OrgAdvancedSettings | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [newMappingGroup, setNewMappingGroup] = useState("");
  const [newMappingRole, setNewMappingRole] = useState<OrgRole>("member");
  const [advancedError, setAdvancedError] = useState<string | null>(null);
  const [userFilter, setUserFilter] = useState<"" | "stale" | "no2fa" | "noaccess">("");
  const [patMaxLifetimeDays, setPatMaxLifetimeDays] = useState("");
  const [orgPats, setOrgPats] = useState<OrgPersonalAccessToken[]>([]);
  const [patBulkResult, setPatBulkResult] = useState<string | null>(null);

  const [ssoConfig, setSsoConfig] = useState<OrgSsoConfig | null>(null);
  const [slugInput, setSlugInput] = useState("");
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ssoOnly, setSsoOnly] = useState(false);
  const [oidcIssuerUrl, setOidcIssuerUrl] = useState("");
  const [oidcClientId, setOidcClientId] = useState("");
  const [oidcClientSecret, setOidcClientSecret] = useState("");
  const [oidcRequiredGroup, setOidcRequiredGroup] = useState("");
  const [ssoError, setSsoError] = useState<string | null>(null);

  const [orgReportDefaultsAvailable, setOrgReportDefaultsAvailable] = useState(false);
  const [orgReportIntro, setOrgReportIntro] = useState("");
  const [orgReportChapters, setOrgReportChapters] = useState<ReportChapter[]>([]);
  const [orgReportAppendices, setOrgReportAppendices] = useState<ReportChapter[]>([]);

  const [reportTemplates, setReportTemplates] = useState<ReportTemplate[]>([]);
  const [newTemplateName, setNewTemplateName] = useState("");
  const [newTemplateAccentColor, setNewTemplateAccentColor] = useState("#475569");
  const [newTemplateIncludeCoverPage, setNewTemplateIncludeCoverPage] = useState(true);
  const [newTemplateIncludeLogo, setNewTemplateIncludeLogo] = useState(true);
  const [newTemplateFooterText, setNewTemplateFooterText] = useState("");

  const [useOwnAccentColor, setUseOwnAccentColor] = useState(false);
  const [accentColorInput, setAccentColorInput] = useState("#475569");
  const [headerTitleInput, setHeaderTitleInput] = useState("");
  const [brandingError, setBrandingError] = useState<string | null>(null);

  const logoInputRef = useRef<HTMLInputElement>(null);
  const resourceInputRef = useRef<HTMLInputElement>(null);
  const loginBackgroundInputRef = useRef<HTMLInputElement>(null);

  async function loadUsers(filter: typeof userFilter) {
    if (!orgId) return;
    const query =
      filter === "stale" ? "?stale_since_days=180" :
      filter === "no2fa" ? "?has_2fa=false" :
      filter === "noaccess" ? "?has_project_access=false" : "";
    try {
      setUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users${query}`));
    } catch (err) {
      // Non-admins get 403 on filtered queries; fall back to the plain list.
      if (err instanceof ApiError && err.status === 403) {
        setUsers(await api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`));
      } else {
        throw err;
      }
    }
  }

  async function reload() {
    if (!orgId) return;
    // Reaching this page at all doesn't imply membership in this specific
    // organisation — a server admin can see every org listed under Server
    // Management without holding any role in most of them (I-M-05: server
    // admin access is tenancy-wide, not content-wide), and a stale link/
    // bookmark can point at an org whose membership has since changed.
    // Every call below requires at least `member`, so this bundle 403s as
    // a whole for exactly that case — caught here so it surfaces as a
    // real message instead of leaving `org` unset and the page spinning
    // forever (its loading gate is just `if (!org) return <Spinner />`).
    let o: Organization, g: OrgGroup[], r: FileAsset[], projects: ProjectListItem[], templates: ReportTemplate[];
    try {
      [o, g, r, projects, templates] = await Promise.all([
        api.get<Organization>(`/api/v1/orgs/${orgId}`),
        api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`),
        api.get<FileAsset[]>(`/api/v1/orgs/${orgId}/resources`),
        api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
        api.get<ReportTemplate[]>(`/api/v1/orgs/${orgId}/report-templates`),
      ]);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : strings.common.error);
      // `GET /orgs/{id}` alone has its own server-admin bypass (unlike the
      // group/resource/template calls above, which is exactly why the
      // bundle as a whole just failed) — best-effort fetch here so the
      // degraded view below can at least show which org this is.
      try {
        setDegradedOrgName((await api.get<Organization>(`/api/v1/orgs/${orgId}`)).name);
      } catch {
        setDegradedOrgName(null);
      }
      return;
    }
    setLoadError(null);
    setDegradedOrgName(null);
    setOrg(o);
    setUseOwnAccentColor(o.accent_color_hex != null);
    setAccentColorInput(o.accent_color_hex ?? "#475569");
    setHeaderTitleInput(o.header_title ?? "");
    setGroups(g);
    setResources(r);
    setTemplateProjects(projects.filter((p) => p.is_template && p.organization_id === orgId));
    setReportTemplates(templates);
    await loadUsers(userFilter);

    try {
      const a = await api.get<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`);
      setAdvanced(a);
      setSmtpHost(a.smtp_host ?? "");
      setSmtpPort(a.smtp_port ? String(a.smtp_port) : "");
      setSmtpUsername(a.smtp_username ?? "");
      setSmtpUseTls(a.smtp_use_tls);
      setPatMaxLifetimeDays(a.pat_max_lifetime_days ? String(a.pat_max_lifetime_days) : "");
      setOrgPats(await api.get<OrgPersonalAccessToken[]>(`/api/v1/orgs/${orgId}/pats`));
    } catch (err) {
      // Non-admins can't read advanced settings (403) — the section is simply hidden for them.
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      const sso = await api.get<OrgSsoConfig>(`/api/v1/orgs/${orgId}/sso-config`);
      setSsoConfig(sso);
      setSlugInput(sso.slug ?? "");
      setSsoEnabled(sso.sso_enabled);
      setSsoOnly(sso.sso_only);
      setOidcIssuerUrl(sso.oidc_issuer_url ?? "");
      setOidcClientId(sso.oidc_client_id ?? "");
      setOidcRequiredGroup(sso.oidc_required_group ?? "");
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) throw err;
    }

    try {
      const rd = await api.get<OrgReportDefaults>(`/api/v1/orgs/${orgId}/report-defaults`);
      setOrgReportDefaultsAvailable(true);
      setOrgReportIntro(rd.intro);
      setOrgReportChapters(rd.chapters);
      setOrgReportAppendices(rd.appendices);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setOrgReportDefaultsAvailable(false);
      } else {
        throw err;
      }
    }
  }

  async function saveOrgReportDefaults() {
    if (!orgId) return;
    await api.put(`/api/v1/orgs/${orgId}/report-defaults`, {
      intro: orgReportIntro, chapters: orgReportChapters, appendices: orgReportAppendices,
    });
    reload();
  }

  function applyUserFilter(filter: typeof userFilter) {
    const next = userFilter === filter ? "" : filter;
    setUserFilter(next);
    loadUsers(next);
  }

  async function saveAdvanced() {
    if (!orgId) return;
    setAdvancedError(null);
    try {
      const saved = await api.put<OrgAdvancedSettings>(`/api/v1/orgs/${orgId}/advanced-settings`, {
        smtp_host: smtpHost || null,
        smtp_port: smtpPort ? Number(smtpPort) : null,
        smtp_username: smtpUsername || null,
        smtp_password: smtpPassword || undefined,
        smtp_use_tls: smtpUseTls,
        sso_group_mappings: advanced?.sso_group_mappings ?? [],
        pat_max_lifetime_days: patMaxLifetimeDays ? Number(patMaxLifetimeDays) : null,
      });
      setAdvanced(saved);
      setSmtpPassword("");
    } catch (err) {
      setAdvancedError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function revokeOrgPat(patId: string) {
    if (!orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/pats/${patId}/revoke`);
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function descopeOrgPat(patId: string) {
    if (!orgId || !window.confirm(strings.orgAdmin.patDescopeConfirm)) return;
    await api.post(`/api/v1/orgs/${orgId}/pats/${patId}/descope`);
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function revokeAllOrgPats() {
    if (!orgId || !window.confirm(strings.orgAdmin.patRevokeAllConfirm)) return;
    const result = await api.post<{ revoked_count: number }>(`/api/v1/orgs/${orgId}/pats/revoke-all`);
    setOrgPats([]);
    setPatBulkResult(strings.orgAdmin.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
  }

  function addMapping() {
    if (!newMappingGroup || !advanced) return;
    setAdvanced({
      ...advanced,
      sso_group_mappings: [...advanced.sso_group_mappings, { sso_group: newMappingGroup, org_role: newMappingRole }],
    });
    setNewMappingGroup("");
  }

  function removeMapping(idx: number) {
    if (!advanced) return;
    setAdvanced({ ...advanced, sso_group_mappings: advanced.sso_group_mappings.filter((_, i) => i !== idx) });
  }

  async function setDefaultTemplate(projectId: string) {
    await api.put(`/api/v1/orgs/${orgId}/default-template`, { project_id: projectId || null });
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  /** Degraded-view action for a *disabled* org specifically (distinct from
   * "not a member" below — a server admin might well already be a genuine
   * member of an org that's since been disabled): re-enables it, then
   * reloads, which now succeeds fully again for anyone who already had a
   * role here. */
  async function enableThisOrg() {
    if (!orgId) return;
    setEnableError(null);
    setEnabling(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/enable`);
      await reload();
    } catch (err) {
      setEnableError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setEnabling(false);
    }
  }

  /** Degraded-view action (self-hosting use case): a server admin with no
   * role in this org grants *themselves* org_admin, then reloads — which
   * now succeeds fully, since they're a genuine member from this point on. */
  async function joinAsAdmin() {
    if (!orgId) return;
    setJoinError(null);
    setJoining(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/join-as-admin`);
      await reload();
    } catch (err) {
      setJoinError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setJoining(false);
    }
  }

  /** Degraded-view action (hosting-company use case): a server admin
   * creates an org_admin user in this org for *someone else*, without
   * becoming a member themselves — the same carve-out `create_org_user`
   * already grants (regardless of whether this org already has users),
   * just reachable from here now that the full page can't load. */
  async function createInitialAdmin() {
    if (!orgId) return;
    setBootstrapError(null);
    setBootstrapCreated(false);
    try {
      await api.post(`/api/v1/orgs/${orgId}/users`, {
        email: bootstrapEmail, display_name: bootstrapName, password: bootstrapPassword, role: "org_admin",
      });
      setBootstrapEmail("");
      setBootstrapName("");
      setBootstrapPassword("");
      setBootstrapCreated(true);
    } catch (err) {
      setBootstrapError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function createUser() {
    await api.post(`/api/v1/orgs/${orgId}/users`, {
      email: newUserEmail, display_name: newUserName, password: newUserPassword, role: "member",
    });
    setNewUserEmail("");
    setNewUserName("");
    setNewUserPassword("");
    reload();
  }

  async function createGroup() {
    await api.post(`/api/v1/orgs/${orgId}/groups`, { name: newGroupName });
    setNewGroupName("");
    reload();
  }

  async function addGroupMember(groupId: string) {
    const userId = groupMemberInputs[groupId];
    if (!userId) return;
    await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { user_id: userId });
    setGroupMemberInputs((m) => ({ ...m, [groupId]: "" }));
    reload();
  }

  async function uploadLogo(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/logo`, file);
    reload();
  }

  async function saveBranding() {
    setBrandingError(null);
    try {
      await api.put<Organization>(`/api/v1/orgs/${orgId}/branding`, {
        accent_color_hex: useOwnAccentColor ? accentColorInput : null,
        header_title: headerTitleInput || null,
      });
      reload();
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function uploadLoginBackground(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/login-background`, file);
    reload();
  }

  async function saveSso() {
    setSsoError(null);
    try {
      const saved = await api.put<OrgSsoConfig>(`/api/v1/orgs/${orgId}/sso-config`, {
        slug: slugInput || null,
        sso_enabled: ssoEnabled,
        sso_only: ssoOnly,
        oidc_issuer_url: oidcIssuerUrl || null,
        oidc_client_id: oidcClientId || null,
        oidc_client_secret: oidcClientSecret || null,
        oidc_required_group: oidcRequiredGroup || null,
      });
      setSsoConfig(saved);
      setOidcClientSecret("");
    } catch (err) {
      setSsoError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function createReportTemplate() {
    if (!newTemplateName) return;
    await api.post(`/api/v1/orgs/${orgId}/report-templates`, {
      name: newTemplateName,
      accent_color_hex: newTemplateAccentColor,
      include_cover_page: newTemplateIncludeCoverPage,
      include_logo: newTemplateIncludeLogo,
      footer_text: newTemplateFooterText || null,
    });
    setNewTemplateName("");
    setNewTemplateAccentColor("#475569");
    setNewTemplateIncludeCoverPage(true);
    setNewTemplateIncludeLogo(true);
    setNewTemplateFooterText("");
    reload();
  }

  async function deleteReportTemplate(templateId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/report-templates/${templateId}`);
    reload();
  }

  async function uploadResource(file: File) {
    await api.postFile(`/api/v1/orgs/${orgId}/resources`, file);
    reload();
  }

  async function deleteResource(fileId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/resources/${fileId}`);
    reload();
  }

  async function toggleDisplayNameLock(user: OrgUser) {
    await api.put(`/api/v1/orgs/${orgId}/users/${user.user_id}/display-name-lock`, {
      display_name_locked: !user.display_name_locked,
    });
    reload();
  }

  async function leaveOrg() {
    setLeaveError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/membership`);
      navigate("/orgs");
    } catch (err) {
      setLeaveError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  const orgIsDisabled = loadError?.toLowerCase().includes("disabled") ?? false;

  if (loadError && orgIsDisabled && user?.is_server_admin) {
    // A server admin hitting a *disabled* org — distinct from "not a
    // member" below, since they might well already be a genuine member of
    // an org that's since been disabled. The one useful action here is
    // re-enabling it, which then reloads as normal for anyone with a
    // pre-existing role.
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.serverOrgs.disabled}</h2>
          <p className="text-muted">{loadError}</p>
          {enableError && <div style={{ color: "var(--color-danger)" }}>{enableError}</div>}
          <button className="btn btn-primary" onClick={enableThisOrg} disabled={enabling} style={{ alignSelf: "flex-start" }}>
            {strings.serverOrgs.enable}
          </button>
        </div>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations}
        </Link>
      </div>
    );
  }

  if (loadError && (orgIsDisabled || !user?.is_server_admin)) {
    // Plain, non-actionable error: a disabled org for a non-server-admin
    // (nothing they can do here), or any org for a non-server-admin who
    // simply isn't a member — no carve-out applies to either case.
    return (
      <div className="card stack">
        <p>{loadError}</p>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations}
        </Link>
      </div>
    );
  }

  if (loadError && user?.is_server_admin) {
    // I-M-05's carve-out, surfaced here rather than just erroring out: a
    // server admin has no automatic role in this org, but can still
    // either become its admin themselves (self-hosting) or create an
    // admin user in it for someone else (hosting-company use case,
    // whether or not this org already has users) — both already allowed
    // server-admin-only at the API layer, just not previously reachable
    // from this page at all.
    return (
      <div className="stack">
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.notAMemberTitle}</h2>
          <p className="text-muted">{strings.orgAdmin.notAMemberHint}</p>
          {joinError && <div style={{ color: "var(--color-danger)" }}>{joinError}</div>}
          <button className="btn btn-primary" onClick={joinAsAdmin} disabled={joining} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.joinAsAdmin}
          </button>
        </div>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.createInitialAdmin}</h2>
          <input className="input" placeholder={strings.orgAdmin.email} value={bootstrapEmail} onChange={(e) => setBootstrapEmail(e.target.value)} />
          <input className="input" placeholder={strings.orgAdmin.name} value={bootstrapName} onChange={(e) => setBootstrapName(e.target.value)} />
          <input
            className="input"
            type="password"
            placeholder={strings.orgAdmin.password}
            value={bootstrapPassword}
            onChange={(e) => setBootstrapPassword(e.target.value)}
          />
          {bootstrapError && <div style={{ color: "var(--color-danger)" }}>{bootstrapError}</div>}
          {bootstrapCreated && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.initialAdminCreated}</div>}
          <button
            className="btn btn-primary"
            onClick={createInitialAdmin}
            disabled={!bootstrapEmail || !bootstrapName || !bootstrapPassword}
            style={{ alignSelf: "flex-start" }}
          >
            {strings.orgAdmin.newUser}
          </button>
        </div>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations}
        </Link>
      </div>
    );
  }

  if (!org) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{org.name}</h1>
        <div className="row">
          {org.logo_file_id && (
            <img src={fileUrl(org.logo_file_id)} alt={`${org.name} logo`} style={{ height: 40 }} />
          )}
          <button className="btn btn-danger" onClick={leaveOrg} title="Remove your own membership in this organisation">
            <LogOut size={14} /> Leave organisation
          </button>
        </div>
      </div>
      {leaveError && <div style={{ color: "var(--color-danger)" }}>{leaveError}</div>}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.branding}</h2>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.logo}
          <input
            ref={logoInputRef}
            type="file"
            accept="image/*"
            onChange={(e) => e.target.files?.[0] && uploadLogo(e.target.files[0])}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.headerTitle}
          <input
            className="input" placeholder={strings.appName}
            value={headerTitleInput} onChange={(e) => setHeaderTitleInput(e.target.value)}
          />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.headerTitleHint}</span>
        </label>
        <label className="row">
          <input type="checkbox" checked={useOwnAccentColor} onChange={(e) => setUseOwnAccentColor(e.target.checked)} />
          {strings.orgAdmin.useOwnAccentColor}
        </label>
        {useOwnAccentColor && (
          <input
            type="color" value={accentColorInput} onChange={(e) => setAccentColorInput(e.target.value)}
            style={{ width: 60, height: 36, padding: 2 }}
          />
        )}
        {brandingError && <div style={{ color: "var(--color-danger)" }}>{brandingError}</div>}
        <button className="btn btn-primary" onClick={saveBranding} style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.saveBranding}
        </button>
      </div>

      {orgReportDefaultsAvailable && (
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Report Defaults</h2>
        <p className="text-muted" style={{ margin: 0 }}>
          Used as the default intro, body chapters, and appendices for any project in this organisation that
          hasn't set its own — see each project's Report Setup tab.
        </p>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span>Default intro</span>
          <RichTextEditor rows={3} value={orgReportIntro} onChange={setOrgReportIntro} />
        </div>
        <ReportChapterListEditor label="Default body chapters" list={orgReportChapters} setList={setOrgReportChapters} />
        <ReportChapterListEditor label="Default appendices" list={orgReportAppendices} setList={setOrgReportAppendices} />
        <button className="btn btn-primary" onClick={saveOrgReportDefaults} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveSettings}
        </button>
      </div>
      )}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.admin.reportTemplates}</h2>
        {reportTemplates.map((tpl) => (
          <div key={tpl.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {tpl.name} <span className="badge" style={{ background: tpl.accent_color_hex }}>&nbsp;&nbsp;</span>
            </span>
            <button className="btn btn-danger" onClick={() => deleteReportTemplate(tpl.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <div className="row">
          <input
            className="input" placeholder={strings.admin.templateName}
            value={newTemplateName} onChange={(e) => setNewTemplateName(e.target.value)}
          />
          <label className="row" style={{ gap: "0.4rem" }}>
            {strings.admin.accentColor}
            <input
              type="color" value={newTemplateAccentColor} onChange={(e) => setNewTemplateAccentColor(e.target.value)}
              style={{ width: 44, height: 32, padding: 2 }}
            />
          </label>
        </div>
        <div className="row">
          <label className="row" style={{ gap: "0.4rem" }}>
            <input
              type="checkbox" checked={newTemplateIncludeCoverPage}
              onChange={(e) => setNewTemplateIncludeCoverPage(e.target.checked)}
            />
            {strings.admin.includeCoverPage}
          </label>
          <label className="row" style={{ gap: "0.4rem" }}>
            <input
              type="checkbox" checked={newTemplateIncludeLogo}
              onChange={(e) => setNewTemplateIncludeLogo(e.target.checked)}
            />
            {strings.admin.includeLogo}
          </label>
        </div>
        <input
          className="input" placeholder={strings.admin.footerText}
          value={newTemplateFooterText} onChange={(e) => setNewTemplateFooterText(e.target.value)}
        />
        <button className="btn btn-primary" onClick={createReportTemplate} disabled={!newTemplateName} style={{ alignSelf: "flex-start" }}>
          <Plus size={14} /> {strings.admin.newReportTemplate}
        </button>
      </div>

      {ssoConfig && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.ssoConfig}</h2>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.slug}
            <input className="input" value={slugInput} onChange={(e) => setSlugInput(e.target.value)} />
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              {strings.orgAdmin.slugHint.replace("{slug}", slugInput || "…")}
            </span>
          </label>
          <label className="row">
            <input type="checkbox" checked={ssoEnabled} onChange={(e) => setSsoEnabled(e.target.checked)} />
            {strings.orgAdmin.ssoEnabled}
          </label>
          <label className="row">
            <input type="checkbox" checked={ssoOnly} onChange={(e) => setSsoOnly(e.target.checked)} />
            {strings.orgAdmin.ssoOnly}
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.oidcIssuerUrl}
            <input className="input" value={oidcIssuerUrl} onChange={(e) => setOidcIssuerUrl(e.target.value)} />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.oidcClientId}
            <input className="input" value={oidcClientId} onChange={(e) => setOidcClientId(e.target.value)} />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.oidcClientSecret}
            <input
              className="input" type="password" value={oidcClientSecret}
              onChange={(e) => setOidcClientSecret(e.target.value)}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.oidcRequiredGroup}
            <input
              className="input" value={oidcRequiredGroup}
              onChange={(e) => setOidcRequiredGroup(e.target.value)}
            />
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.oidcRequiredGroupHint}</span>
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.loginBackground}
            <input
              ref={loginBackgroundInputRef} type="file" accept="image/*"
              onChange={(e) => e.target.files?.[0] && uploadLoginBackground(e.target.files[0])}
            />
          </label>
          {ssoError && <div style={{ color: "var(--color-danger)" }}>{ssoError}</div>}
          <button className="btn btn-primary" onClick={saveSso} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.saveSso}
          </button>
        </div>
      )}

      {templateProjects.length > 0 && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.defaultTemplate}</h2>
          <select
            className="input"
            value={org.default_template_project_id ?? ""}
            onChange={(e) => setDefaultTemplate(e.target.value)}
          >
            <option value="">{strings.projects.noTemplate}</option>
            {templateProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.users}</h2>
        <div className="row">
          <button className={`btn${userFilter === "stale" ? " btn-primary" : ""}`} onClick={() => applyUserFilter("stale")}>
            {strings.orgAdmin.filterStale}
          </button>
          <button className={`btn${userFilter === "no2fa" ? " btn-primary" : ""}`} onClick={() => applyUserFilter("no2fa")}>
            {strings.orgAdmin.filterNo2fa}
          </button>
          <button className={`btn${userFilter === "noaccess" ? " btn-primary" : ""}`} onClick={() => applyUserFilter("noaccess")}>
            {strings.orgAdmin.filterNoProjectAccess}
          </button>
          {userFilter && (
            <button className="btn" onClick={() => applyUserFilter("")}>
              {strings.orgAdmin.filterClear}
            </button>
          )}
        </div>
        <table>
          <thead>
            <tr>
              <th>{strings.orgAdmin.email}</th>
              <th>{strings.orgAdmin.name}</th>
              <th>{strings.orgAdmin.roles}</th>
              <th>{strings.orgAdmin.status}</th>
              <th>{strings.orgAdmin.lastLogin}</th>
              <th>{strings.orgAdmin.twoFactor}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id}>
                <td>{u.email}</td>
                <td>{u.display_name}</td>
                <td>{u.roles.map((r) => ORG_ROLE_LABEL[r]).join(", ")}</td>
                <td>
                  {u.is_archived
                    ? strings.orgAdmin.statusArchived
                    : u.is_active
                      ? strings.orgAdmin.statusActive
                      : strings.orgAdmin.statusDeactivated}
                </td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : strings.orgAdmin.never}</td>
                <td>{u.is_2fa_enabled ? strings.common.yes : strings.common.no}</td>
                <td>
                  <button
                    className="btn"
                    onClick={() => toggleDisplayNameLock(u)}
                    title={u.display_name_locked ? strings.orgAdmin.unlockDisplayName : strings.orgAdmin.lockDisplayName}
                    aria-label={u.display_name_locked ? strings.orgAdmin.unlockDisplayName : strings.orgAdmin.lockDisplayName}
                  >
                    {u.display_name_locked ? <Lock size={14} /> : <Unlock size={14} />}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          <input className="input" placeholder={strings.orgAdmin.email} value={newUserEmail} onChange={(e) => setNewUserEmail(e.target.value)} />
          <input className="input" placeholder={strings.orgAdmin.name} value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
          <input className="input" type="password" placeholder={strings.orgAdmin.password} value={newUserPassword} onChange={(e) => setNewUserPassword(e.target.value)} />
          <button className="btn btn-primary" onClick={createUser} disabled={!newUserEmail || !newUserName || !newUserPassword}>
            <Plus size={14} /> {strings.orgAdmin.newUser}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.groups}</h2>
        {groups.map((g) => (
          <div key={g.id} className="stack">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span>{g.name}</span>
              <span className="text-muted">{g.member_user_ids.length} members</span>
            </div>
            <div className="row">
              <input
                className="input"
                style={{ maxWidth: 280 }}
                placeholder={strings.admin.userId}
                value={groupMemberInputs[g.id] ?? ""}
                onChange={(e) => setGroupMemberInputs((m) => ({ ...m, [g.id]: e.target.value }))}
              />
              <button className="btn" onClick={() => addGroupMember(g.id)}>
                {strings.admin.addMember}
              </button>
            </div>
          </div>
        ))}
        <div className="row">
          <input className="input" placeholder={strings.admin.name} value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
          <button className="btn btn-primary" onClick={createGroup} disabled={!newGroupName}>
            <Plus size={14} /> {strings.orgAdmin.newGroup}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.resources}</h2>
        {resources.map((r) => (
          <div key={r.id} className="row" style={{ justifyContent: "space-between" }}>
            <a href={fileUrl(r.id)} target="_blank" rel="noreferrer">
              {r.filename}
            </a>
            <button className="btn btn-danger" onClick={() => deleteResource(r.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <input
          ref={resourceInputRef}
          type="file"
          onChange={(e) => e.target.files?.[0] && uploadResource(e.target.files[0])}
        />
        <span className="text-muted row">
          <Upload size={14} /> {strings.orgAdmin.resourcesHint}
        </span>
      </div>

      {advanced && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.advanced}</h2>
          <div className="row">
            <input
              className="input"
              placeholder={strings.orgAdmin.smtpHost}
              value={smtpHost}
              onChange={(e) => setSmtpHost(e.target.value)}
            />
            <input
              className="input"
              style={{ maxWidth: 120 }}
              placeholder={strings.orgAdmin.smtpPort}
              value={smtpPort}
              onChange={(e) => setSmtpPort(e.target.value)}
            />
          </div>
          <div className="row">
            <input
              className="input"
              placeholder={strings.orgAdmin.smtpUsername}
              value={smtpUsername}
              onChange={(e) => setSmtpUsername(e.target.value)}
            />
            <input
              className="input"
              type="password"
              placeholder={strings.orgAdmin.smtpPassword}
              value={smtpPassword}
              onChange={(e) => setSmtpPassword(e.target.value)}
            />
          </div>
          <label className="row">
            <input type="checkbox" checked={smtpUseTls} onChange={(e) => setSmtpUseTls(e.target.checked)} />
            {strings.orgAdmin.smtpUseTls}
          </label>

          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.patMaxLifetime}
            <input
              className="input"
              type="number"
              min={1}
              max={3650}
              style={{ maxWidth: 160 }}
              value={patMaxLifetimeDays}
              onChange={(e) => setPatMaxLifetimeDays(e.target.value)}
            />
            <span className="text-muted">{strings.orgAdmin.patMaxLifetimeHint}</span>
          </label>

          <div className="stack">
            <strong>{strings.orgAdmin.ssoMappings}</strong>
            {advanced.sso_group_mappings.map((m, idx) => (
              <div key={idx} className="row" style={{ justifyContent: "space-between" }}>
                <span>
                  {m.sso_group} <span className="badge">{ORG_ROLE_LABEL[m.org_role]}</span>
                </span>
                <button className="btn btn-danger" onClick={() => removeMapping(idx)}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="row">
              <input
                className="input"
                placeholder={strings.orgAdmin.ssoGroup}
                value={newMappingGroup}
                onChange={(e) => setNewMappingGroup(e.target.value)}
              />
              <select className="input" value={newMappingRole} onChange={(e) => setNewMappingRole(e.target.value as OrgRole)}>
                <option value="member">{ORG_ROLE_LABEL.member}</option>
                <option value="project_creator">{ORG_ROLE_LABEL.project_creator}</option>
                <option value="org_admin">{ORG_ROLE_LABEL.org_admin}</option>
              </select>
              <button className="btn" onClick={addMapping} disabled={!newMappingGroup}>
                <Plus size={14} /> {strings.orgAdmin.addMapping}
              </button>
            </div>
          </div>

          {advancedError && <div style={{ color: "var(--color-danger)" }}>{advancedError}</div>}
          <button className="btn btn-primary" onClick={saveAdvanced} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.saveAdvanced}
          </button>
        </div>
      )}

      {advanced && (
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.pats}</h2>

          {orgPats.length === 0 ? (
            <p className="text-muted">{strings.orgAdmin.patNone}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{strings.orgAdmin.patUser}</th>
                  <th>{strings.orgAdmin.patName}</th>
                  <th>{strings.orgAdmin.patExpires}</th>
                  <th>{strings.orgAdmin.patLastUsed}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orgPats.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.user_display_name} <span className="text-muted">({p.user_email})</span>
                    </td>
                    <td>
                      {p.name}
                      {p.other_org_count > 0 && (
                        <div className="text-muted">{strings.orgAdmin.patOtherOrgs.replace("{n}", String(p.other_org_count))}</div>
                      )}
                    </td>
                    <td>{new Date(p.expires_at).toLocaleDateString()}</td>
                    <td>{p.last_used_at ? new Date(p.last_used_at).toLocaleString() : strings.orgAdmin.never}</td>
                    <td>
                      <div className="row">
                        {p.other_org_count > 0 && (
                          <button className="btn" onClick={() => descopeOrgPat(p.id)}>
                            {strings.orgAdmin.patDescope}
                          </button>
                        )}
                        <button
                          className="btn btn-danger"
                          onClick={() => {
                            if (window.confirm(strings.orgAdmin.patRevokeOneConfirm)) revokeOrgPat(p.id);
                          }}
                        >
                          {strings.orgAdmin.patRevoke}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {orgPats.length > 0 && (
            <button className="btn btn-danger" onClick={revokeAllOrgPats} style={{ alignSelf: "flex-start" }}>
              {strings.orgAdmin.patRevokeAll}
            </button>
          )}
          {patBulkResult && <div style={{ color: "var(--color-accent)" }}>{patBulkResult}</div>}
        </div>
      )}
    </div>
  );
}
