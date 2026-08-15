import { Download, Lock, LogOut, Pencil, Plus, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type {
  ExternalUserPolicy,
  FileAsset,
  OrgAdvancedSettings,
  OrgGroup,
  OrgPersonalAccessToken,
  OrgProjectSummary,
  OrgReportDefaults,
  OrgRole,
  OrgSsoConfig,
  OrgUser,
  Organization,
  OutsideDomainUser,
  ProjectGroup,
  ProjectListItem,
  ReportChapter,
  ReportTemplate,
} from "../api/types";
import { ORG_ROLE_LABEL } from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import { RichTextEditor } from "../components/RichTextEditor";
import { Spinner } from "../components/Spinner";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";

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
  const [orgNameEdit, setOrgNameEdit] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
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

  const [advanced, setAdvanced] = useState<OrgAdvancedSettings | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [testEmailRecipient, setTestEmailRecipient] = useState("");
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  const [testEmailError, setTestEmailError] = useState<string | null>(null);
  const [testEmailSuccess, setTestEmailSuccess] = useState(false);
  const [newMappingGroup, setNewMappingGroup] = useState("");
  const [newMappingRole, setNewMappingRole] = useState<OrgRole>("member");
  const [advancedError, setAdvancedError] = useState<string | null>(null);
  const [userFilter, setUserFilter] = useState<"" | "stale" | "no2fa" | "noaccess">("");
  const [patMaxLifetimeDays, setPatMaxLifetimeDays] = useState("");
  const [require2fa, setRequire2fa] = useState(false);
  const [allowSelfSignup, setAllowSelfSignup] = useState(false);
  const [autoAcceptEmailDomain, setAutoAcceptEmailDomain] = useState("");
  const [externalUserPolicy, setExternalUserPolicy] = useState<ExternalUserPolicy>("disabled");
  const [outsideDomainUsers, setOutsideDomainUsers] = useState<OutsideDomainUser[] | null>(null);
  const [outsideDomainError, setOutsideDomainError] = useState<string | null>(null);
  const [orgPats, setOrgPats] = useState<OrgPersonalAccessToken[]>([]);
  const [patBulkResult, setPatBulkResult] = useState<string | null>(null);
  const [orgProjects, setOrgProjects] = useState<OrgProjectSummary[] | null>(null);
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [expandedProjectGroups, setExpandedProjectGroups] = useState<ProjectGroup[]>([]);

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
  const [newTemplateIntro, setNewTemplateIntro] = useState("");
  const [newTemplateChapters, setNewTemplateChapters] = useState<ReportChapter[]>([]);
  const [newTemplateAppendices, setNewTemplateAppendices] = useState<ReportChapter[]>([]);
  const [newTemplateChaptersPerComponent, setNewTemplateChaptersPerComponent] = useState(true);
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);

  const [useOwnAccentColor, setUseOwnAccentColor] = useState(false);
  const [accentColorInput, setAccentColorInput] = useState("#475569");
  const [headerTitleInput, setHeaderTitleInput] = useState("");
  const [emailFooterCompanyNameInput, setEmailFooterCompanyNameInput] = useState("");
  const [emailFooterWebsiteInput, setEmailFooterWebsiteInput] = useState("");
  const [emailFooterAddressInput, setEmailFooterAddressInput] = useState("");
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
    setOrgNameEdit(o.name);
    setUseOwnAccentColor(o.accent_color_hex != null);
    setAccentColorInput(o.accent_color_hex ?? "#475569");
    setHeaderTitleInput(o.header_title ?? "");
    setEmailFooterCompanyNameInput(o.email_footer_company_name ?? "");
    setEmailFooterWebsiteInput(o.email_footer_website ?? "");
    setEmailFooterAddressInput(o.email_footer_address ?? "");
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
      setRequire2fa(a.require_2fa);
      setAllowSelfSignup(a.allow_self_signup);
      setAutoAcceptEmailDomain(a.auto_accept_email_domain ?? "");
      setExternalUserPolicy(a.external_user_policy);
      setOrgPats(await api.get<OrgPersonalAccessToken[]>(`/api/v1/orgs/${orgId}/pats`));
      setOrgProjects(await api.get<OrgProjectSummary[]>(`/api/v1/orgs/${orgId}/projects`));
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

  async function toggleOutsideDomainUsers() {
    if (!orgId) return;
    if (outsideDomainUsers !== null) {
      setOutsideDomainUsers(null);
      return;
    }
    setOutsideDomainError(null);
    try {
      setOutsideDomainUsers(await api.get<OutsideDomainUser[]>(`/api/v1/orgs/${orgId}/users/outside-domain`));
    } catch (err) {
      setOutsideDomainError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function renameOrg() {
    if (!orgId || !orgNameEdit.trim() || !org || orgNameEdit === org.name) return;
    setRenameError(null);
    try {
      const updated = await api.put<Organization>(`/api/v1/orgs/${orgId}/name`, { name: orgNameEdit });
      setOrg(updated);
      setOrgNameEdit(updated.name);
    } catch (err) {
      setRenameError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function sendOrgTestEmail() {
    if (!orgId) return;
    setTestEmailError(null);
    setTestEmailSuccess(false);
    setSendingTestEmail(true);
    try {
      await api.post(`/api/v1/orgs/${orgId}/test-email`, testEmailRecipient ? { to_email: testEmailRecipient } : {});
      setTestEmailSuccess(true);
    } catch (err) {
      setTestEmailError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setSendingTestEmail(false);
    }
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
        require_2fa: require2fa,
        allow_self_signup: allowSelfSignup,
        auto_accept_email_domain: autoAcceptEmailDomain || null,
        external_user_policy: externalUserPolicy,
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

  async function toggleExpandedProject(projectId: string) {
    if (expandedProjectId === projectId) {
      setExpandedProjectId(null);
      return;
    }
    setExpandedProjectId(projectId);
    setExpandedProjectGroups(await api.get<ProjectGroup[]>(`/api/v1/projects/${projectId}/groups`));
  }

  async function addExpandedProjectGroupMember(groupId: string, userId: string) {
    if (!expandedProjectId) return;
    await api.post(`/api/v1/projects/${expandedProjectId}/groups/${groupId}/members`, { user_id: userId });
    setExpandedProjectGroups(await api.get<ProjectGroup[]>(`/api/v1/projects/${expandedProjectId}/groups`));
  }

  async function removeExpandedProjectGroupMember(groupId: string, userId: string) {
    if (!expandedProjectId) return;
    await api.delete(`/api/v1/projects/${expandedProjectId}/groups/${groupId}/members/${userId}`);
    setExpandedProjectGroups(await api.get<ProjectGroup[]>(`/api/v1/projects/${expandedProjectId}/groups`));
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

  async function addGroupMember(groupId: string, userId: string) {
    await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { user_id: userId });
    reload();
  }

  async function removeGroupMember(groupId: string, userId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${userId}`);
    reload();
  }

  const [logoUploading, setLogoUploading] = useState(false);
  const [logoUploaded, setLogoUploaded] = useState(false);
  const [logoError, setLogoError] = useState<string | null>(null);

  async function uploadLogo(file: File) {
    setLogoError(null);
    setLogoUploaded(false);
    setLogoUploading(true);
    try {
      await api.postFile(`/api/v1/orgs/${orgId}/logo`, file);
      await reload();
      setLogoUploaded(true);
    } catch (err) {
      setLogoError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setLogoUploading(false);
    }
  }

  async function saveBranding() {
    setBrandingError(null);
    try {
      await api.put<Organization>(`/api/v1/orgs/${orgId}/branding`, {
        accent_color_hex: useOwnAccentColor ? accentColorInput : null,
        header_title: headerTitleInput || null,
        email_footer_company_name: emailFooterCompanyNameInput || null,
        email_footer_website: emailFooterWebsiteInput || null,
        email_footer_address: emailFooterAddressInput || null,
      });
      reload();
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  const [loginBackgroundUploading, setLoginBackgroundUploading] = useState(false);
  const [loginBackgroundUploaded, setLoginBackgroundUploaded] = useState(false);
  const [loginBackgroundError, setLoginBackgroundError] = useState<string | null>(null);

  async function uploadLoginBackground(file: File) {
    setLoginBackgroundError(null);
    setLoginBackgroundUploaded(false);
    setLoginBackgroundUploading(true);
    try {
      await api.postFile(`/api/v1/orgs/${orgId}/login-background`, file);
      await reload();
      setLoginBackgroundUploaded(true);
    } catch (err) {
      setLoginBackgroundError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setLoginBackgroundUploading(false);
    }
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

  function resetTemplateForm() {
    setEditingTemplateId(null);
    setNewTemplateName("");
    setNewTemplateAccentColor("#475569");
    setNewTemplateIncludeCoverPage(true);
    setNewTemplateIncludeLogo(true);
    setNewTemplateFooterText("");
    setNewTemplateIntro("");
    setNewTemplateChapters([]);
    setNewTemplateAppendices([]);
    setNewTemplateChaptersPerComponent(true);
  }

  function startEditTemplate(tpl: ReportTemplate) {
    setEditingTemplateId(tpl.id);
    setNewTemplateName(tpl.name);
    setNewTemplateAccentColor(tpl.accent_color_hex);
    setNewTemplateIncludeCoverPage(tpl.include_cover_page);
    setNewTemplateIncludeLogo(tpl.include_logo);
    setNewTemplateFooterText(tpl.footer_text ?? "");
    setNewTemplateIntro(tpl.intro);
    setNewTemplateChapters(tpl.chapters);
    setNewTemplateAppendices(tpl.appendices);
    setNewTemplateChaptersPerComponent(tpl.chapters_per_component);
  }

  async function saveReportTemplate() {
    if (!newTemplateName) return;
    const payload = {
      name: newTemplateName,
      accent_color_hex: newTemplateAccentColor,
      include_cover_page: newTemplateIncludeCoverPage,
      include_logo: newTemplateIncludeLogo,
      footer_text: newTemplateFooterText || null,
      intro: newTemplateIntro,
      chapters: newTemplateChapters,
      appendices: newTemplateAppendices,
      chapters_per_component: newTemplateChaptersPerComponent,
    };
    if (editingTemplateId) {
      await api.put(`/api/v1/orgs/${orgId}/report-templates/${editingTemplateId}`, payload);
    } else {
      await api.post(`/api/v1/orgs/${orgId}/report-templates`, payload);
    }
    resetTemplateForm();
    reload();
  }

  async function deleteReportTemplate(templateId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/report-templates/${templateId}`);
    if (editingTemplateId === templateId) resetTemplateForm();
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

  const [exportingOrg, setExportingOrg] = useState(false);

  async function exportOrg() {
    if (!orgId || !org) return;
    setExportingOrg(true);
    try {
      const blob = await api.getForBlob(`/api/v1/orgs/${orgId}/export`);
      const safeName = org.name.replace(/[\\/"\r\n\t]/g, "") || "organization";
      downloadBlob(blob, `${safeName}-export.zip`);
    } finally {
      setExportingOrg(false);
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

  // sso_only and allow_self_signup are mutually exclusive (an org that only
  // accepts SSO logins can't also let people create native-password
  // accounts) — the backend already rejects saving this combination
  // (test_sso_only_enforcement.py), this just surfaces the conflict before
  // the round trip instead of only after a 422.
  const selfSignupConflict = allowSelfSignup && ssoOnly;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="stack" style={{ gap: "0.35rem" }}>
          <h1 style={{ margin: 0 }}>{org.name}</h1>
          {advanced && (
            <div className="row" style={{ gap: "0.4rem" }}>
              <input
                className="input"
                style={{ maxWidth: 280 }}
                value={orgNameEdit}
                onChange={(e) => setOrgNameEdit(e.target.value)}
                aria-label={strings.orgAdmin.rename}
                title={strings.orgAdmin.renameHint}
              />
              {orgNameEdit.trim() && orgNameEdit !== org.name && (
                <button className="btn" onClick={renameOrg} title={strings.orgAdmin.rename}>
                  <Pencil size={14} /> {strings.orgAdmin.rename}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="row">
          {org.logo_file_id && (
            <img src={fileUrl(org.logo_file_id)} alt={`${org.name} logo`} style={{ height: 40 }} />
          )}
          <button
            className="btn" onClick={exportOrg} disabled={exportingOrg}
            title="Downloads a self-contained .zip with this organisation's settings, members, report templates, and every project's full structure/history — re-importable as a new organisation from the server organisations page."
          >
            <Download size={14} /> {exportingOrg ? "Exporting…" : "Export organisation bundle"}
          </button>
          <button className="btn btn-danger" onClick={leaveOrg} title="Remove your own membership in this organisation">
            <LogOut size={14} /> Leave organisation
          </button>
        </div>
      </div>
      {renameError && <div style={{ color: "var(--color-danger)" }}>{renameError}</div>}
      {leaveError && <div style={{ color: "var(--color-danger)" }}>{leaveError}</div>}

      <CollapsibleSection sectionKey="orgAdmin.users" title={strings.orgAdmin.users} defaultCollapsed>
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
          {advanced?.auto_accept_email_domain && (
            <button
              className={`btn${outsideDomainUsers !== null ? " btn-primary" : ""}`}
              onClick={toggleOutsideDomainUsers}
            >
              {strings.orgAdmin.showOutsideDomainUsers}
            </button>
          )}
        </div>
        {outsideDomainError && <div style={{ color: "var(--color-danger)" }}>{outsideDomainError}</div>}
        {outsideDomainUsers !== null && (
          <div className="card stack">
            <strong>{strings.orgAdmin.outsideDomainUsers}</strong>
            <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.outsideDomainUsersHint}</p>
            {outsideDomainUsers.length === 0 ? (
              <p className="text-muted">{strings.orgAdmin.noOutsideDomainUsers}</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>{strings.orgAdmin.email}</th>
                    <th>{strings.orgAdmin.name}</th>
                  </tr>
                </thead>
                <tbody>
                  {outsideDomainUsers.map((u) => (
                    <tr key={u.user_id}>
                      <td>{u.email}</td>
                      <td>{u.display_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
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
      </CollapsibleSection>

      {orgProjects && (
        <CollapsibleSection sectionKey="orgAdmin.projects" title={strings.orgAdmin.projects} defaultCollapsed>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectsHint}</p>
          {orgProjects.map((p) => (
            <div key={p.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="row" style={{ gap: "0.5rem" }}>
                  {p.name}
                  {p.is_archived && <span className="badge">{strings.projects.archived}</span>}
                </span>
                <button className="btn" onClick={() => toggleExpandedProject(p.id)}>
                  {expandedProjectId === p.id ? strings.common.cancel : strings.orgAdmin.manageUsers}
                </button>
              </div>
              {expandedProjectId === p.id && (
                <div className="stack" style={{ paddingLeft: "1rem" }}>
                  {expandedProjectGroups.map((g) => {
                    const memberIds = new Set(g.member_user_ids);
                    const members = users.filter((u) => memberIds.has(u.user_id));
                    const nonMembers = users.filter((u) => !memberIds.has(u.user_id));
                    return (
                      <div key={g.id} className="stack">
                        <span>
                          {g.name} <span className="badge">{g.role}</span>
                        </span>
                        {members.length > 0 && (
                          <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                            {members.map((u) => (
                              <li key={u.user_id} style={{ listStyle: "disc" }}>
                                <span className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                                  <span>{u.display_name} <span className="text-muted">({u.email})</span></span>
                                  <button className="btn" onClick={() => removeExpandedProjectGroupMember(g.id, u.user_id)}>
                                    <Trash2 size={14} />
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        <UserAutocomplete
                          users={nonMembers}
                          placeholder={strings.admin.addMemberPlaceholder}
                          onSelect={(userId) => addExpandedProjectGroupMember(g.id, userId)}
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </CollapsibleSection>
      )}

      <CollapsibleSection sectionKey="orgAdmin.branding" title={strings.orgAdmin.branding} defaultCollapsed>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.logo}
          <input
            ref={logoInputRef}
            type="file"
            accept="image/*"
            disabled={logoUploading}
            onChange={(e) => e.target.files?.[0] && uploadLogo(e.target.files[0])}
          />
        </label>
        {logoUploading && <Spinner />}
        {logoError && <div style={{ color: "var(--color-danger)" }}>{logoError}</div>}
        {logoUploaded && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.logoUploaded}</div>}
        {org.logo_file_id && <img src={fileUrl(org.logo_file_id)} alt="" style={{ height: 40 }} />}
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
        <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)" }} />
        <h4 style={{ margin: 0 }}>{strings.orgAdmin.emailFooterTitle}</h4>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.orgAdmin.emailFooterHint}</p>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.emailFooterCompanyName}
          <input
            className="input"
            value={emailFooterCompanyNameInput} onChange={(e) => setEmailFooterCompanyNameInput(e.target.value)}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.emailFooterWebsite}
          <input
            className="input"
            value={emailFooterWebsiteInput} onChange={(e) => setEmailFooterWebsiteInput(e.target.value)}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.emailFooterAddress}
          <textarea
            className="input" rows={3}
            value={emailFooterAddressInput} onChange={(e) => setEmailFooterAddressInput(e.target.value)}
          />
        </label>
        {brandingError && <div style={{ color: "var(--color-danger)" }}>{brandingError}</div>}
        <button className="btn btn-primary" onClick={saveBranding} style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.saveBranding}
        </button>
      </CollapsibleSection>

      {orgReportDefaultsAvailable && (
      <CollapsibleSection sectionKey="orgAdmin.reportDefaults" title="Report Defaults" defaultCollapsed>
        <p className="text-muted" style={{ margin: 0 }}>
          Used as the default intro, body chapters, and appendices for any project in this organisation that
          hasn't set its own — see each project's Report Setup tab.
        </p>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span>Default intro</span>
          <RichTextEditor rows={3} value={orgReportIntro} onChange={setOrgReportIntro} organizationId={orgId} />
        </div>
        <ReportChapterListEditor
          label="Default body chapters" list={orgReportChapters} setList={setOrgReportChapters} organizationId={orgId}
        />
        <ReportChapterListEditor
          label="Default appendices" list={orgReportAppendices} setList={setOrgReportAppendices} organizationId={orgId}
        />
        <button className="btn btn-primary" onClick={saveOrgReportDefaults} style={{ alignSelf: "flex-start" }}>
          {strings.admin.saveSettings}
        </button>
      </CollapsibleSection>
      )}

      <CollapsibleSection sectionKey="orgAdmin.reportTemplates" title={strings.admin.reportTemplates} defaultCollapsed>
        {reportTemplates.map((tpl) => (
          <div key={tpl.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {tpl.name} <span className="badge" style={{ background: tpl.accent_color_hex }}>&nbsp;&nbsp;</span>
            </span>
            <div className="row" style={{ gap: "0.4rem" }}>
              <button className="btn" onClick={() => startEditTemplate(tpl)}>
                {strings.common.edit}
              </button>
              <button className="btn btn-danger" onClick={() => deleteReportTemplate(tpl.id)}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        <CollapsibleSection
          sectionKey="orgAdmin.reportTemplates.form"
          variant="plain"
          title={editingTemplateId ? strings.admin.editReportTemplate : strings.admin.newReportTemplate}
        >
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
          <div className="stack" style={{ gap: "0.25rem" }}>
            <span>{strings.admin.templateIntro}</span>
            <RichTextEditor rows={3} value={newTemplateIntro} onChange={setNewTemplateIntro} organizationId={orgId} />
          </div>
          <ReportChapterListEditor
            label={strings.admin.templateChapters} list={newTemplateChapters} setList={setNewTemplateChapters}
            organizationId={orgId}
          />
          <ReportChapterListEditor
            label={strings.admin.templateAppendices} list={newTemplateAppendices} setList={setNewTemplateAppendices}
            organizationId={orgId}
          />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.admin.templateContentHint}</span>
          <label className="row" style={{ gap: "0.4rem" }}>
            <input
              type="checkbox" checked={newTemplateChaptersPerComponent}
              onChange={(e) => setNewTemplateChaptersPerComponent(e.target.checked)}
            />
            {strings.admin.templateChaptersPerComponent}
          </label>
          <div className="row">
            <button className="btn btn-primary" onClick={saveReportTemplate} disabled={!newTemplateName}>
              <Plus size={14} /> {editingTemplateId ? strings.common.save : strings.admin.newReportTemplate}
            </button>
            {editingTemplateId && (
              <button className="btn" onClick={resetTemplateForm}>
                {strings.common.cancel}
              </button>
            )}
          </div>
        </CollapsibleSection>
      </CollapsibleSection>

      {ssoConfig && (
        <CollapsibleSection sectionKey="orgAdmin.sso" title={strings.orgAdmin.ssoConfig} defaultCollapsed>
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
              disabled={loginBackgroundUploading}
              onChange={(e) => e.target.files?.[0] && uploadLoginBackground(e.target.files[0])}
            />
          </label>
          {loginBackgroundUploading && <Spinner />}
          {loginBackgroundError && <div style={{ color: "var(--color-danger)" }}>{loginBackgroundError}</div>}
          {loginBackgroundUploaded && (
            <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.loginBackgroundUploaded}</div>
          )}
          {org.login_background_file_id && (
            <img src={fileUrl(org.login_background_file_id)} alt="" style={{ maxHeight: 100, borderRadius: 4 }} />
          )}
          {ssoError && <div style={{ color: "var(--color-danger)" }}>{ssoError}</div>}
          <button className="btn btn-primary" onClick={saveSso} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.saveSso}
          </button>
        </CollapsibleSection>
      )}

      {templateProjects.length > 0 && (
        <CollapsibleSection sectionKey="orgAdmin.defaultTemplate" title={strings.orgAdmin.defaultTemplate} defaultCollapsed>
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
        </CollapsibleSection>
      )}

      <CollapsibleSection sectionKey="orgAdmin.groups" title={strings.orgAdmin.groups} defaultCollapsed>
        {groups.map((g) => {
          const memberIds = new Set(g.member_user_ids);
          const members = users.filter((u) => memberIds.has(u.user_id));
          const nonMembers = users.filter((u) => !memberIds.has(u.user_id));
          return (
            <div key={g.id} className="stack">
              <span>{g.name}</span>
              {members.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {members.map((u) => (
                    <li key={u.user_id} style={{ listStyle: "disc" }}>
                      <span className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                        <span>
                          {u.display_name} <span className="text-muted">({u.email})</span>
                        </span>
                        <button className="btn" onClick={() => removeGroupMember(g.id, u.user_id)}>
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <UserAutocomplete
                users={nonMembers}
                placeholder={strings.admin.addMemberPlaceholder}
                onSelect={(userId) => addGroupMember(g.id, userId)}
              />
            </div>
          );
        })}
        <div className="row">
          <input className="input" placeholder={strings.admin.name} value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
          <button className="btn btn-primary" onClick={createGroup} disabled={!newGroupName}>
            <Plus size={14} /> {strings.orgAdmin.newGroup}
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="orgAdmin.resources" title={strings.orgAdmin.resources} defaultCollapsed>
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
      </CollapsibleSection>

      {advanced && (
        <CollapsibleSection sectionKey="orgAdmin.advanced" title={strings.orgAdmin.advanced} defaultCollapsed>
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

          <div className="stack" style={{ gap: "0.4rem" }}>
            <strong>{strings.orgAdmin.testEmail}</strong>
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.orgAdmin.testEmailHint}</span>
            <div className="row">
              <input
                className="input"
                type="email"
                placeholder={strings.orgAdmin.testEmailRecipientPlaceholder}
                value={testEmailRecipient}
                onChange={(e) => setTestEmailRecipient(e.target.value)}
              />
              <button className="btn" onClick={sendOrgTestEmail} disabled={!smtpHost || sendingTestEmail}>
                {sendingTestEmail ? strings.orgAdmin.testEmailSending : strings.orgAdmin.testEmail}
              </button>
            </div>
            {!smtpHost && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.testEmailNoSmtp}</span>}
            {testEmailError && <div style={{ color: "var(--color-danger)" }}>{testEmailError}</div>}
            {testEmailSuccess && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.testEmailSent}</div>}
          </div>

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

          <label className="row" style={{ gap: "0.6rem" }}>
            <ToggleSwitch checked={require2fa} onChange={setRequire2fa} label={strings.orgAdmin.require2fa} />
            <span className="stack" style={{ gap: 0 }}>
              {strings.orgAdmin.require2fa}
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.require2faHint}</span>
            </span>
          </label>

          <label className="row" style={{ gap: "0.6rem" }}>
            <ToggleSwitch checked={allowSelfSignup} onChange={setAllowSelfSignup} label={strings.orgAdmin.allowSelfSignup} />
            <span className="stack" style={{ gap: 0 }}>
              {strings.orgAdmin.allowSelfSignup}
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.allowSelfSignupHint}</span>
            </span>
          </label>

          {selfSignupConflict && (
            <div style={{ color: "var(--color-danger)" }}>{strings.orgAdmin.selfSignupSsoConflict}</div>
          )}

          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.autoAcceptEmailDomain}
            <input
              className="input"
              placeholder="acme.com"
              value={autoAcceptEmailDomain}
              onChange={(e) => setAutoAcceptEmailDomain(e.target.value)}
            />
            <span className="text-muted">{strings.orgAdmin.autoAcceptEmailDomainHint}</span>
          </label>

          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.orgAdmin.externalUserPolicy}
            <select
              className="input"
              value={externalUserPolicy}
              onChange={(e) => setExternalUserPolicy(e.target.value as ExternalUserPolicy)}
            >
              <option value="disabled">{strings.orgAdmin.externalUserPolicyDisabled}</option>
              <option value="org_domain_only">{strings.orgAdmin.externalUserPolicyDomainOnly}</option>
              <option value="anyone">{strings.orgAdmin.externalUserPolicyAnyone}</option>
            </select>
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
          <button
            className="btn btn-primary"
            onClick={saveAdvanced}
            disabled={selfSignupConflict}
            style={{ alignSelf: "flex-start" }}
          >
            {strings.orgAdmin.saveAdvanced}
          </button>
        </CollapsibleSection>
      )}

      {advanced && (
        <CollapsibleSection sectionKey="orgAdmin.pats" title={strings.orgAdmin.pats} defaultCollapsed>
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
        </CollapsibleSection>
      )}
    </div>
  );
}
