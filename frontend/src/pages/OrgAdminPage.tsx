import { ArrowDown, ArrowUp, Download, Lock, LogOut, Pencil, Plus, Trash2, Unlock, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useOrgLabel, useOrgLabelCapitalized, useOrgLabelPlural } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import type {
  ExternalUserPolicy,
  FileAsset,
  LinkTypeDefinition,
  MergeConflict,
  OrgAdvancedSettings,
  OrgGroup,
  OrgMergePreviewResult,
  OrgMergeResult,
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
  ProjectStatusDefinition,
  ReportChapter,
  ReportTemplate,
  ScimTokenCreated,
  ScimTokenStatus,
} from "../api/types";
import { ORG_ROLE_LABEL } from "../api/types";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ImportConflictPanel } from "../components/ImportConflictPanel";
import { OverridePill } from "../components/OverridePill";
import { Popover } from "../components/Popover";
import { ReportChapterListEditor } from "../components/ReportChapterListEditor";
import { RichTextEditor } from "../components/RichTextEditor";
import { Spinner } from "../components/Spinner";
import { ToggleSwitch } from "../components/ToggleSwitch";
import { UserAutocomplete } from "../components/UserAutocomplete";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";
import { defaultResolutions } from "../utils/mergeConflicts";

const strings = t();

/**
 * Organisation administration: users (C-U-01), groups (C-U-08), shared
 * resource files (C-M-03), the organisation logo (U-C-02), the default
 * template project used for new projects (C-E-04), the org's definable
 * project statuses (Project Statuses section — the status list every
 * project in this org picks from), and the org's definable, bidirectional
 * requirement link types (Link Types section — each type stores both a
 * forward and reverse display name, since a link renders differently
 * depending on which requirement it's viewed from; see
 * `docs/decisions.md`). Both of the latter two share the same
 * rename/reorder/delete-with-reassignment contract as custom fields, with
 * one addition: deleting a status/link type currently in use 409s with a
 * server-supplied count, at which point a reassignment picker (rather than
 * a plain confirm) lets the admin move existing references to another
 * status/type before the delete retries.
 */
export function OrgAdminPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const orgLabelPlural = useOrgLabelPlural();
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

  // --- Project statuses (C-G-XX) ---------------------------------------
  const [projectStatuses, setProjectStatuses] = useState<ProjectStatusDefinition[]>([]);
  const [newStatusName, setNewStatusName] = useState("");
  const [statusNameEdits, setStatusNameEdits] = useState<Record<string, string>>({});
  const [deletingStatusId, setDeletingStatusId] = useState<string | null>(null);
  const [statusInUseMessage, setStatusInUseMessage] = useState<string | null>(null);
  const [reassignStatusTo, setReassignStatusTo] = useState("");
  const [projectStatusError, setProjectStatusError] = useState<string | null>(null);

  // --- Requirement link types (C-G-09) ---------------------------------
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[]>([]);
  const [newLinkTypeForward, setNewLinkTypeForward] = useState("");
  const [newLinkTypeReverse, setNewLinkTypeReverse] = useState("");
  const [linkTypeEdits, setLinkTypeEdits] = useState<Record<string, { forward: string; reverse: string }>>({});
  const [deletingLinkTypeId, setDeletingLinkTypeId] = useState<string | null>(null);
  const [linkTypeInUseMessage, setLinkTypeInUseMessage] = useState<string | null>(null);
  const [reassignLinkTypeTo, setReassignLinkTypeTo] = useState("");
  const [linkTypeError, setLinkTypeError] = useState<string | null>(null);

  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupPopoverOpen, setNewGroupPopoverOpen] = useState(false);
  const newGroupTriggerRef = useRef<HTMLButtonElement>(null);

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

  const [scimStatus, setScimStatus] = useState<ScimTokenStatus | null>(null);
  const [scimGeneratedToken, setScimGeneratedToken] = useState<string | null>(null);
  const [scimError, setScimError] = useState<string | null>(null);

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
    let statuses: ProjectStatusDefinition[], linkTypeList: LinkTypeDefinition[];
    try {
      [o, g, r, projects, templates, statuses, linkTypeList] = await Promise.all([
        api.get<Organization>(`/api/v1/orgs/${orgId}`),
        api.get<OrgGroup[]>(`/api/v1/orgs/${orgId}/groups`),
        api.get<FileAsset[]>(`/api/v1/orgs/${orgId}/resources`),
        api.get<ProjectListItem[]>("/api/v1/projects?archived=false"),
        api.get<ReportTemplate[]>(`/api/v1/orgs/${orgId}/report-templates`),
        api.get<ProjectStatusDefinition[]>(`/api/v1/orgs/${orgId}/project-statuses`),
        api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${orgId}/link-types`),
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
    setProjectStatuses(statuses);
    setLinkTypes(linkTypeList);
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
      setScimStatus(await api.get<ScimTokenStatus>(`/api/v1/orgs/${orgId}/scim-token`));
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
    if (!orgId || !window.confirm(strings.orgAdmin.patDescopeConfirm(orgLabel, orgLabelPlural))) return;
    await api.post(`/api/v1/orgs/${orgId}/pats/${patId}/descope`);
    setOrgPats((current) => current.filter((p) => p.id !== patId));
  }

  async function revokeAllOrgPats() {
    if (!orgId || !window.confirm(strings.orgAdmin.patRevokeAllConfirm(orgLabel, orgLabelPlural))) return;
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

  async function addProjectStatus() {
    if (!newStatusName.trim() || !orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/project-statuses`, { name: newStatusName });
    setNewStatusName("");
    reload();
  }

  async function moveProjectStatus(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/orgs/${orgId}/project-statuses/${id}/move`, { direction });
    reload();
  }

  async function renameProjectStatus(id: string, name: string) {
    setProjectStatusError(null);
    try {
      await api.patch(`/api/v1/orgs/${orgId}/project-statuses/${id}`, { name });
      setStatusNameEdits((m) => {
        const next = { ...m };
        delete next[id];
        return next;
      });
      reload();
    } catch (err) {
      setProjectStatusError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  /** Attempts a plain delete first (no `reassign_to_id`) per §4.0's server
   * contract: a 204 means done; a 409 means the status is in use, at which
   * point the reassignment picker opens showing the server's own count
   * message rather than a generic one. */
  async function attemptDeleteProjectStatus(id: string) {
    setProjectStatusError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/project-statuses/${id}`);
      reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDeletingStatusId(id);
        setStatusInUseMessage(err.message);
      } else {
        setProjectStatusError(err instanceof Error ? err.message : strings.common.error);
      }
    }
  }

  async function confirmDeleteProjectStatus(id: string) {
    if (!reassignStatusTo) return;
    setProjectStatusError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/project-statuses/${id}?reassign_to_id=${reassignStatusTo}`);
      setDeletingStatusId(null);
      setStatusInUseMessage(null);
      setReassignStatusTo("");
      reload();
    } catch (err) {
      setProjectStatusError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function addLinkType() {
    if (!newLinkTypeForward.trim() || !newLinkTypeReverse.trim() || !orgId) return;
    await api.post(`/api/v1/orgs/${orgId}/link-types`, {
      forward_name: newLinkTypeForward, reverse_name: newLinkTypeReverse,
    });
    setNewLinkTypeForward("");
    setNewLinkTypeReverse("");
    reload();
  }

  async function moveLinkType(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/orgs/${orgId}/link-types/${id}/move`, { direction });
    reload();
  }

  async function renameLinkType(id: string, forwardName: string, reverseName: string) {
    setLinkTypeError(null);
    try {
      await api.patch(`/api/v1/orgs/${orgId}/link-types/${id}`, { forward_name: forwardName, reverse_name: reverseName });
      setLinkTypeEdits((m) => {
        const next = { ...m };
        delete next[id];
        return next;
      });
      reload();
    } catch (err) {
      setLinkTypeError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function attemptDeleteLinkType(id: string) {
    setLinkTypeError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/link-types/${id}`);
      reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDeletingLinkTypeId(id);
        setLinkTypeInUseMessage(err.message);
      } else {
        setLinkTypeError(err instanceof Error ? err.message : strings.common.error);
      }
    }
  }

  async function confirmDeleteLinkType(id: string) {
    if (!reassignLinkTypeTo) return;
    setLinkTypeError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/link-types/${id}?reassign_to_id=${reassignLinkTypeTo}`);
      setDeletingLinkTypeId(null);
      setLinkTypeInUseMessage(null);
      setReassignLinkTypeTo("");
      reload();
    } catch (err) {
      setLinkTypeError(err instanceof Error ? err.message : strings.common.error);
    }
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
    try {
      await api.post(`/api/v1/orgs/${orgId}/groups`, { name: newGroupName });
      setNewGroupName("");
      setNewGroupPopoverOpen(false);
      showToast(strings.orgAdmin.groupCreated);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function addGroupMember(groupId: string, userId: string) {
    await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { user_id: userId });
    reload();
  }

  async function removeGroupMember(groupId: string, userId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${userId}`);
    reload();
  }

  const [nestSelections, setNestSelections] = useState<Record<string, string>>({});
  const [nestErrors, setNestErrors] = useState<Record<string, string | null>>({});

  async function addNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    setNestErrors((prev) => ({ ...prev, [groupId]: null }));
    try {
      await api.post(`/api/v1/orgs/${orgId}/groups/${groupId}/members`, { member_org_group_id: memberOrgGroupId });
      setNestSelections((prev) => ({ ...prev, [groupId]: "" }));
      reload();
    } catch (err) {
      setNestErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
  }

  async function removeNestedGroupMember(groupId: string, memberOrgGroupId: string) {
    await api.delete(`/api/v1/orgs/${orgId}/groups/${groupId}/members/${memberOrgGroupId}`);
    reload();
  }

  const [idpSyncEdits, setIdpSyncEdits] = useState<Record<string, string>>({});
  const [idpSyncErrors, setIdpSyncErrors] = useState<Record<string, string | null>>({});

  async function saveIdpSync(groupId: string, value: string) {
    setIdpSyncErrors((prev) => ({ ...prev, [groupId]: null }));
    try {
      await api.patch(`/api/v1/orgs/${orgId}/groups/${groupId}`, { idp_synced_group_name: value.trim() || null });
      setIdpSyncEdits((prev) => {
        const next = { ...prev };
        delete next[groupId];
        return next;
      });
      reload();
    } catch (err) {
      setIdpSyncErrors((prev) => ({ ...prev, [groupId]: err instanceof ApiError ? err.message : strings.common.error }));
    }
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
      showToast(strings.orgAdmin.brandingSaved);
      reload();
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
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

  async function regenerateScimToken() {
    setScimError(null);
    try {
      const created = await api.post<ScimTokenCreated>(`/api/v1/orgs/${orgId}/scim-token`);
      setScimGeneratedToken(created.token);
      setScimStatus({ enabled: true, token_prefix: created.token_prefix });
    } catch (err) {
      setScimError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  async function revokeScimToken() {
    setScimError(null);
    try {
      await api.delete(`/api/v1/orgs/${orgId}/scim-token`);
      setScimGeneratedToken(null);
      setScimStatus({ enabled: false, token_prefix: null });
    } catch (err) {
      setScimError(err instanceof ApiError ? err.message : strings.common.error);
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

  const [importMergeFile, setImportMergeFile] = useState<File | null>(null);
  const [importMergeConflicts, setImportMergeConflicts] = useState<MergeConflict[] | null>(null);
  const [importMergeResolutions, setImportMergeResolutions] = useState<Record<string, string>>({});
  const [importMergePreviewing, setImportMergePreviewing] = useState(false);
  const [importMergeSubmitting, setImportMergeSubmitting] = useState(false);
  const [importMergeError, setImportMergeError] = useState<string | null>(null);
  const [importMergeResult, setImportMergeResult] = useState<OrgMergeResult | null>(null);

  async function previewImportMerge() {
    if (!orgId || !importMergeFile) return;
    setImportMergeError(null);
    setImportMergeResult(null);
    setImportMergePreviewing(true);
    try {
      const result = await api.postFile<OrgMergePreviewResult>(`/api/v1/orgs/${orgId}/import/preview`, importMergeFile);
      setImportMergeConflicts(result.conflicts);
      setImportMergeResolutions(defaultResolutions(result.conflicts));
    } catch (err) {
      setImportMergeError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setImportMergePreviewing(false);
    }
  }

  async function confirmImportMerge() {
    if (!orgId || !importMergeFile) return;
    setImportMergeError(null);
    setImportMergeSubmitting(true);
    try {
      const result = await api.postFile<OrgMergeResult>(`/api/v1/orgs/${orgId}/import/merge`, importMergeFile, {
        resolutions: JSON.stringify(importMergeResolutions),
      });
      setImportMergeResult(result);
      setImportMergeFile(null);
      setImportMergeConflicts(null);
      setImportMergeResolutions({});
      reload();
    } catch (err) {
      setImportMergeError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setImportMergeSubmitting(false);
    }
  }

  function cancelImportMerge() {
    setImportMergeFile(null);
    setImportMergeConflicts(null);
    setImportMergeResolutions({});
    setImportMergeError(null);
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
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.serverOrgs.disabled}</h2>
          <p className="text-muted">{loadError}</p>
          {enableError && <div style={{ color: "var(--color-danger)" }}>{enableError}</div>}
          <button className="btn btn-primary" onClick={enableThisOrg} disabled={enabling} style={{ alignSelf: "flex-start" }}>
            {strings.serverOrgs.enable}
          </button>
        </div>
        <Link to="/orgs" className="btn" style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
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
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
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
        <h1 style={{ margin: 0 }}>{degradedOrgName ?? strings.orgAdmin.organizations(orgLabelPlural)}</h1>
        <div className="card stack">
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.orgAdmin.notAMemberTitle(orgLabel)}</h2>
          <p className="text-muted">{strings.orgAdmin.notAMemberHint}</p>
          {joinError && <div style={{ color: "var(--color-danger)" }}>{joinError}</div>}
          <button className="btn btn-primary" onClick={joinAsAdmin} disabled={joining} style={{ alignSelf: "flex-start" }}>
            {strings.orgAdmin.joinAsAdmin(orgLabel)}
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
          {bootstrapCreated && <div style={{ color: "var(--color-accent)" }}>{strings.orgAdmin.initialAdminCreated(orgLabel)}</div>}
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
          {strings.orgAdmin.backToOrganizations(orgLabelPlural)}
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
                title={strings.orgAdmin.renameHint(orgLabel)}
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
            title={`Downloads a self-contained .zip with this ${orgLabel}'s settings, members, report templates, and every project's full structure/history — re-importable as a new ${orgLabel} from the server ${orgLabelPlural.toLowerCase()} page.`}
          >
            <Download size={14} /> {exportingOrg ? "Exporting…" : `Export ${orgLabel} bundle`}
          </button>
          <button className="btn btn-danger" onClick={leaveOrg} title={`Remove your own membership in this ${orgLabel}`}>
            <LogOut size={14} /> Leave {orgLabel}
          </button>
        </div>
      </div>
      {renameError && <div style={{ color: "var(--color-danger)" }}>{renameError}</div>}
      {leaveError && <div style={{ color: "var(--color-danger)" }}>{leaveError}</div>}

      <CollapsibleSection sectionKey="orgAdmin.importMerge" title={strings.importMerge.action(orgLabel)} defaultCollapsed>
        <p className="text-muted" style={{ margin: 0 }}>{strings.importMerge.hint(orgLabel)}</p>
        {!importMergeConflicts && !importMergeResult && (
          <div className="stack">
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.importMerge.chooseFile}
              <input
                type="file" accept=".zip,application/zip"
                onChange={(e) => setImportMergeFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <button
              className="btn btn-primary" onClick={previewImportMerge}
              disabled={!importMergeFile || importMergePreviewing} style={{ alignSelf: "flex-start" }}
            >
              <Upload size={14} /> {importMergePreviewing ? strings.importMerge.previewing : strings.importMerge.preview}
            </button>
          </div>
        )}
        {importMergeConflicts && !importMergeResult && (
          <div className="stack">
            {importMergeConflicts.length === 0 ? (
              <p>{strings.importMerge.noConflicts}</p>
            ) : (
              <ImportConflictPanel
                conflicts={importMergeConflicts}
                resolutions={importMergeResolutions}
                onResolutionChange={(id, value) => setImportMergeResolutions((r) => ({ ...r, [id]: value }))}
              />
            )}
            <div className="row">
              <button
                className="btn btn-primary" onClick={confirmImportMerge} disabled={importMergeSubmitting}
              >
                {importMergeSubmitting ? strings.importMerge.importing : strings.importMerge.confirmImport}
              </button>
              <button className="btn" onClick={cancelImportMerge} disabled={importMergeSubmitting}>
                {strings.importMerge.cancel}
              </button>
            </div>
          </div>
        )}
        {importMergeResult && (
          <div className="card stack">
            <strong>{strings.importMerge.resultTitle}</strong>
            <ul style={{ margin: 0 }}>
              <li>{strings.importMerge.projectsImported(importMergeResult.projects_imported)}</li>
              <li>{strings.importMerge.projectsSkipped(importMergeResult.projects_skipped)}</li>
              <li>{strings.importMerge.reportTemplatesImported(importMergeResult.report_templates_imported)}</li>
              <li>{strings.importMerge.reportTemplatesOverwritten(importMergeResult.report_templates_overwritten)}</li>
            </ul>
            {importMergeResult.warnings.length > 0 && (
              <ul style={{ margin: 0, color: "var(--color-warning, #b58900)" }}>
                {importMergeResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
            <button className="btn" onClick={() => setImportMergeResult(null)} style={{ alignSelf: "flex-start" }}>
              {strings.common.close}
            </button>
          </div>
        )}
        {importMergeError && <div style={{ color: "var(--color-danger)" }}>{importMergeError}</div>}
      </CollapsibleSection>

      <CollapsibleSection sectionKey="orgAdmin.users" title={strings.orgAdmin.users(orgLabelCap)} defaultCollapsed>
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
            <strong>{strings.orgAdmin.outsideDomainUsers(orgLabel)}</strong>
            <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.outsideDomainUsersHint(orgLabel)}</p>
            {outsideDomainUsers.length === 0 ? (
              <p className="text-muted">{strings.orgAdmin.noOutsideDomainUsers(orgLabel)}</p>
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
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectsHint(orgLabel)}</p>
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
                                  <button
                                    className="btn"
                                    title={strings.admin.removeMember(u.display_name)}
                                    aria-label={strings.admin.removeMember(u.display_name)}
                                    onClick={() => removeExpandedProjectGroupMember(g.id, u.user_id)}
                                  >
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

      <CollapsibleSection sectionKey="orgAdmin.projectStatuses" title={strings.orgAdmin.projectStatuses} defaultCollapsed>
        <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.projectStatusesHint}</p>
        {projectStatusError && <div style={{ color: "var(--color-danger)" }}>{projectStatusError}</div>}
        {projectStatuses.map((s, idx) => {
          const nameEdit = statusNameEdits[s.id] ?? s.name;
          const otherStatuses = projectStatuses.filter((other) => other.id !== s.id);
          return (
            <div key={s.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <input
                    className="input" style={{ maxWidth: 220 }} value={nameEdit}
                    onChange={(e) => setStatusNameEdits((m) => ({ ...m, [s.id]: e.target.value }))}
                  />
                  {nameEdit !== s.name && nameEdit.trim() && (
                    <button
                      className="btn"
                      title={strings.admin.rename}
                      aria-label={strings.admin.rename}
                      onClick={() => renameProjectStatus(s.id, nameEdit)}
                    >
                      <Pencil size={14} />
                    </button>
                  )}
                </div>
                <div className="row">
                  <button
                    className="btn"
                    disabled={idx === 0}
                    title={strings.common.up}
                    aria-label={strings.common.up}
                    onClick={() => moveProjectStatus(s.id, "up")}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    className="btn"
                    disabled={idx === projectStatuses.length - 1}
                    title={strings.common.down}
                    aria-label={strings.common.down}
                    onClick={() => moveProjectStatus(s.id, "down")}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    className="btn btn-danger"
                    disabled={otherStatuses.length === 0}
                    title={otherStatuses.length === 0 ? strings.admin.deleteLastOneHint : strings.orgAdmin.deleteProjectStatus}
                    aria-label={otherStatuses.length === 0 ? strings.admin.deleteLastOneHint : strings.orgAdmin.deleteProjectStatus}
                    onClick={() => attemptDeleteProjectStatus(s.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {deletingStatusId === s.id && (
                <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                  <span>{statusInUseMessage}</span>
                  <span>{strings.admin.reassignExistingTo}</span>
                  <select className="input" style={{ maxWidth: 220 }} value={reassignStatusTo} onChange={(e) => setReassignStatusTo(e.target.value)}>
                    <option value="">—</option>
                    {otherStatuses.map((other) => (
                      <option key={other.id} value={other.id}>{other.name}</option>
                    ))}
                  </select>
                  <button className="btn btn-danger" disabled={!reassignStatusTo} onClick={() => confirmDeleteProjectStatus(s.id)}>
                    {strings.admin.confirmDelete}
                  </button>
                  <button className="btn" onClick={() => { setDeletingStatusId(null); setStatusInUseMessage(null); setReassignStatusTo(""); }}>
                    {strings.common.cancel}
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <div className="row">
          <input
            className="input" placeholder={strings.admin.name} value={newStatusName}
            onChange={(e) => setNewStatusName(e.target.value)}
          />
          <button className="btn btn-primary" onClick={addProjectStatus} disabled={!newStatusName.trim()}>
            <Plus size={14} /> {strings.orgAdmin.newProjectStatus}
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="orgAdmin.linkTypes" title={strings.orgAdmin.linkTypes} defaultCollapsed>
        <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.linkTypesHint}</p>
        {linkTypeError && <div style={{ color: "var(--color-danger)" }}>{linkTypeError}</div>}
        {linkTypes.map((lt, idx) => {
          const edit = linkTypeEdits[lt.id] ?? { forward: lt.forward_name, reverse: lt.reverse_name };
          const dirty = edit.forward !== lt.forward_name || edit.reverse !== lt.reverse_name;
          const otherLinkTypes = linkTypes.filter((other) => other.id !== lt.id);
          return (
            <div key={lt.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <input
                    className="input" style={{ maxWidth: 200 }} aria-label={strings.orgAdmin.forwardName} value={edit.forward}
                    onChange={(e) => setLinkTypeEdits((m) => ({ ...m, [lt.id]: { ...edit, forward: e.target.value } }))}
                  />
                  <input
                    className="input" style={{ maxWidth: 200 }} aria-label={strings.orgAdmin.reverseName} value={edit.reverse}
                    onChange={(e) => setLinkTypeEdits((m) => ({ ...m, [lt.id]: { ...edit, reverse: e.target.value } }))}
                  />
                  {dirty && edit.forward.trim() && edit.reverse.trim() && (
                    <button
                      className="btn"
                      title={strings.admin.rename}
                      aria-label={strings.admin.rename}
                      onClick={() => renameLinkType(lt.id, edit.forward, edit.reverse)}
                    >
                      <Pencil size={14} />
                    </button>
                  )}
                </div>
                <div className="row">
                  <button
                    className="btn"
                    disabled={idx === 0}
                    title={strings.common.up}
                    aria-label={strings.common.up}
                    onClick={() => moveLinkType(lt.id, "up")}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    className="btn"
                    disabled={idx === linkTypes.length - 1}
                    title={strings.common.down}
                    aria-label={strings.common.down}
                    onClick={() => moveLinkType(lt.id, "down")}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    className="btn btn-danger"
                    disabled={otherLinkTypes.length === 0}
                    title={otherLinkTypes.length === 0 ? strings.admin.deleteLastOneHint : strings.orgAdmin.deleteLinkType}
                    aria-label={otherLinkTypes.length === 0 ? strings.admin.deleteLastOneHint : strings.orgAdmin.deleteLinkType}
                    onClick={() => attemptDeleteLinkType(lt.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {deletingLinkTypeId === lt.id && (
                <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                  <span>{linkTypeInUseMessage}</span>
                  <span>{strings.admin.reassignExistingTo}</span>
                  <select className="input" style={{ maxWidth: 220 }} value={reassignLinkTypeTo} onChange={(e) => setReassignLinkTypeTo(e.target.value)}>
                    <option value="">—</option>
                    {otherLinkTypes.map((other) => (
                      <option key={other.id} value={other.id}>{other.forward_name}</option>
                    ))}
                  </select>
                  <button className="btn btn-danger" disabled={!reassignLinkTypeTo} onClick={() => confirmDeleteLinkType(lt.id)}>
                    {strings.admin.confirmDelete}
                  </button>
                  <button className="btn" onClick={() => { setDeletingLinkTypeId(null); setLinkTypeInUseMessage(null); setReassignLinkTypeTo(""); }}>
                    {strings.common.cancel}
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <div className="row">
          <input
            className="input" placeholder={strings.orgAdmin.forwardName} value={newLinkTypeForward}
            onChange={(e) => setNewLinkTypeForward(e.target.value)}
          />
          <input
            className="input" placeholder={strings.orgAdmin.reverseName} value={newLinkTypeReverse}
            onChange={(e) => setNewLinkTypeReverse(e.target.value)}
          />
          <button
            className="btn btn-primary" onClick={addLinkType}
            disabled={!newLinkTypeForward.trim() || !newLinkTypeReverse.trim()}
          >
            <Plus size={14} /> {strings.orgAdmin.newLinkType}
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection sectionKey="orgAdmin.branding" title={strings.orgAdmin.branding} defaultCollapsed>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.logo(orgLabel)}
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
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <label htmlFor="org-header-title">{strings.orgAdmin.headerTitle}</label>
            <OverridePill custom={org.header_title != null} onReset={() => setHeaderTitleInput("")} />
          </span>
          <input
            id="org-header-title"
            className="input" placeholder={strings.appName}
            value={headerTitleInput} onChange={(e) => setHeaderTitleInput(e.target.value)}
          />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.headerTitleHint}</span>
        </div>
        <label className="row">
          <input type="checkbox" checked={useOwnAccentColor} onChange={(e) => setUseOwnAccentColor(e.target.checked)} />
          {strings.orgAdmin.useOwnAccentColor(orgLabel)}
        </label>
        {useOwnAccentColor && (
          <input
            type="color" value={accentColorInput} onChange={(e) => setAccentColorInput(e.target.value)}
            style={{ width: 60, height: 36, padding: 2 }}
          />
        )}
        <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)" }} />
        <h4 style={{ margin: 0 }}>{strings.orgAdmin.emailFooterTitle}</h4>
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.orgAdmin.emailFooterHint(orgLabel)}</p>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <label htmlFor="org-email-footer-company">{strings.orgAdmin.emailFooterCompanyName}</label>
            <OverridePill custom={org.email_footer_company_name != null} onReset={() => setEmailFooterCompanyNameInput("")} />
          </span>
          <input
            id="org-email-footer-company"
            className="input"
            value={emailFooterCompanyNameInput} onChange={(e) => setEmailFooterCompanyNameInput(e.target.value)}
          />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <label htmlFor="org-email-footer-website">{strings.orgAdmin.emailFooterWebsite}</label>
            <OverridePill custom={org.email_footer_website != null} onReset={() => setEmailFooterWebsiteInput("")} />
          </span>
          <input
            id="org-email-footer-website"
            className="input"
            value={emailFooterWebsiteInput} onChange={(e) => setEmailFooterWebsiteInput(e.target.value)}
          />
        </div>
        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
            <label htmlFor="org-email-footer-address">{strings.orgAdmin.emailFooterAddress}</label>
            <OverridePill custom={org.email_footer_address != null} onReset={() => setEmailFooterAddressInput("")} />
          </span>
          <textarea
            id="org-email-footer-address"
            className="input" rows={3}
            value={emailFooterAddressInput} onChange={(e) => setEmailFooterAddressInput(e.target.value)}
          />
        </div>
        {brandingError && <div style={{ color: "var(--color-danger)" }}>{brandingError}</div>}
        <button className="btn btn-primary" onClick={saveBranding} style={{ alignSelf: "flex-start" }}>
          {strings.orgAdmin.saveBranding}
        </button>
      </CollapsibleSection>

      {orgReportDefaultsAvailable && (
      <CollapsibleSection sectionKey="orgAdmin.reportDefaults" title="Report Defaults" defaultCollapsed>
        <p className="text-muted" style={{ margin: 0 }}>
          Used as the default intro, body chapters, and appendices for any project in this {orgLabel} that
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
              <button
                className="btn btn-danger"
                title={strings.orgAdmin.deleteReportTemplate(tpl.name)}
                aria-label={strings.orgAdmin.deleteReportTemplate(tpl.name)}
                onClick={() => deleteReportTemplate(tpl.id)}
              >
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
              {strings.admin.includeLogo(orgLabel)}
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
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.admin.templateContentHint(orgLabel)}</span>
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
              {strings.orgAdmin.slugHint(orgLabel).replace("{slug}", slugInput || "…")}
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

      {scimStatus && (
        <CollapsibleSection sectionKey="orgAdmin.scim" title={strings.orgAdmin.scimProvisioning} defaultCollapsed>
          <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.scimHint}</p>
          <div className="row">
            <span>
              {scimStatus.enabled
                ? strings.orgAdmin.scimEnabledWithPrefix(scimStatus.token_prefix ?? "")
                : strings.orgAdmin.scimDisabled}
            </span>
          </div>
          {scimGeneratedToken && (
            <div className="stack" style={{ gap: "0.25rem" }}>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.scimTokenShownOnce}</span>
              <input className="input" readOnly value={scimGeneratedToken} onFocus={(e) => e.target.select()} />
            </div>
          )}
          {scimError && <div style={{ color: "var(--color-danger)" }}>{scimError}</div>}
          <div className="row">
            <button className="btn btn-primary" onClick={regenerateScimToken}>
              {scimStatus.enabled ? strings.orgAdmin.scimRegenerate : strings.orgAdmin.scimGenerate}
            </button>
            {scimStatus.enabled && (
              <button className="btn btn-danger" onClick={revokeScimToken}>
                {strings.orgAdmin.scimRevoke}
              </button>
            )}
          </div>
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

      <CollapsibleSection sectionKey="orgAdmin.groups" title={strings.orgAdmin.groups(orgLabelCap)} defaultCollapsed>
        <button
          ref={newGroupTriggerRef}
          className="btn btn-primary"
          style={{ alignSelf: "flex-start" }}
          onClick={() => setNewGroupPopoverOpen((o) => !o)}
        >
          <Plus size={14} /> {strings.orgAdmin.newGroup}
        </button>
        {newGroupPopoverOpen && (
          <Popover
            anchorRef={newGroupTriggerRef}
            title={strings.orgAdmin.newGroup}
            onClose={() => setNewGroupPopoverOpen(false)}
          >
            <label className="stack" style={{ gap: "0.25rem" }}>
              {strings.admin.name}
              <input
                className="input"
                placeholder={strings.orgAdmin.groupNamePlaceholder}
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newGroupName) createGroup();
                }}
              />
            </label>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setNewGroupPopoverOpen(false)}>
                {strings.common.cancel}
              </button>
              <button className="btn btn-primary" onClick={createGroup} disabled={!newGroupName}>
                {strings.common.create}
              </button>
            </div>
          </Popover>
        )}
        {groups.map((g) => {
          const memberIds = new Set(g.member_user_ids);
          const members = users.filter((u) => memberIds.has(u.user_id));
          const nonMembers = users.filter((u) => !memberIds.has(u.user_id));
          const nestedGroupIds = new Set(g.member_org_group_ids);
          const nestedGroups = groups.filter((og) => nestedGroupIds.has(og.id));
          const nestableGroups = groups.filter((og) => og.id !== g.id && !nestedGroupIds.has(og.id));
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
                        <button
                          className="btn"
                          title={strings.admin.removeMember(u.display_name)}
                          aria-label={strings.admin.removeMember(u.display_name)}
                          onClick={() => removeGroupMember(g.id, u.user_id)}
                        >
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
              {nestedGroups.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {nestedGroups.map((og) => (
                    <li key={og.id} style={{ listStyle: "circle" }}>
                      <span className="row" style={{ justifyContent: "space-between", gap: "0.5rem" }}>
                        <span>{strings.orgAdmin.nestedGroupLabel(og.name)}</span>
                        <button
                          className="btn"
                          title={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                          aria-label={strings.admin.removeNestedGroup(strings.orgAdmin.nestedGroupLabel(og.name))}
                          onClick={() => removeNestedGroupMember(g.id, og.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {nestableGroups.length > 0 && (
                <div className="row">
                  <select
                    className="input"
                    value={nestSelections[g.id] ?? ""}
                    onChange={(e) => setNestSelections((prev) => ({ ...prev, [g.id]: e.target.value }))}
                  >
                    <option value="">{strings.orgAdmin.addNestedGroup}</option>
                    {nestableGroups.map((og) => (
                      <option key={og.id} value={og.id}>
                        {og.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn"
                    disabled={!nestSelections[g.id]}
                    title={strings.orgAdmin.addNestedGroup}
                    aria-label={strings.orgAdmin.addNestedGroup}
                    onClick={() => addNestedGroupMember(g.id, nestSelections[g.id])}
                  >
                    <Plus size={14} />
                  </button>
                </div>
              )}
              {nestErrors[g.id] && <div style={{ color: "var(--color-danger)" }}>{nestErrors[g.id]}</div>}
              <label className="row" style={{ gap: "0.25rem" }}>
                {strings.orgAdmin.idpSyncedGroupName}
                <input
                  className="input"
                  placeholder={strings.orgAdmin.idpSyncedGroupNamePlaceholder}
                  value={idpSyncEdits[g.id] ?? g.idp_synced_group_name ?? ""}
                  onChange={(e) => setIdpSyncEdits((prev) => ({ ...prev, [g.id]: e.target.value }))}
                />
                <button className="btn" onClick={() => saveIdpSync(g.id, idpSyncEdits[g.id] ?? g.idp_synced_group_name ?? "")}>
                  {strings.orgAdmin.saveIdpSync}
                </button>
              </label>
              {idpSyncErrors[g.id] && <div style={{ color: "var(--color-danger)" }}>{idpSyncErrors[g.id]}</div>}
            </div>
          );
        })}
      </CollapsibleSection>

      <CollapsibleSection sectionKey="orgAdmin.resources" title={strings.orgAdmin.resources} defaultCollapsed>
        {resources.map((r) => (
          <div key={r.id} className="row" style={{ justifyContent: "space-between" }}>
            <a href={fileUrl(r.id)} target="_blank" rel="noreferrer">
              {r.filename}
            </a>
            <button
              className="btn btn-danger"
              title={strings.orgAdmin.deleteResource(r.filename)}
              aria-label={strings.orgAdmin.deleteResource(r.filename)}
              onClick={() => deleteResource(r.id)}
            >
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
          <Upload size={14} /> {strings.orgAdmin.resourcesHint(orgLabel)}
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
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.orgAdmin.testEmailHint(orgLabel)}</span>
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
            <span className="text-muted">{strings.orgAdmin.patMaxLifetimeHint(orgLabel)}</span>
          </label>

          <label className="row" style={{ gap: "0.6rem" }}>
            <ToggleSwitch checked={require2fa} onChange={setRequire2fa} label={strings.orgAdmin.require2fa} />
            <span className="stack" style={{ gap: 0 }}>
              {strings.orgAdmin.require2fa}
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.require2faHint(orgLabel)}</span>
            </span>
          </label>

          <label className="row" style={{ gap: "0.6rem" }}>
            <ToggleSwitch checked={allowSelfSignup} onChange={setAllowSelfSignup} label={strings.orgAdmin.allowSelfSignup} />
            <span className="stack" style={{ gap: 0 }}>
              {strings.orgAdmin.allowSelfSignup}
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.orgAdmin.allowSelfSignupHint(orgLabel)}</span>
            </span>
          </label>

          {selfSignupConflict && (
            <div style={{ color: "var(--color-danger)" }}>{strings.orgAdmin.selfSignupSsoConflict(orgLabel)}</div>
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
              <option value="disabled">{strings.orgAdmin.externalUserPolicyDisabled(orgLabel)}</option>
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
                <button
                  className="btn btn-danger"
                  title={strings.orgAdmin.removeSsoMapping(m.sso_group)}
                  aria-label={strings.orgAdmin.removeSsoMapping(m.sso_group)}
                  onClick={() => removeMapping(idx)}
                >
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
            <p className="text-muted">{strings.orgAdmin.patNone(orgLabel)}</p>
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
                        <div className="text-muted">{strings.orgAdmin.patOtherOrgs(p.other_org_count, orgLabelPlural)}</div>
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
              {strings.orgAdmin.patRevokeAll(orgLabel)}
            </button>
          )}
          {patBulkResult && <div style={{ color: "var(--color-accent)" }}>{patBulkResult}</div>}
        </CollapsibleSection>
      )}
    </div>
  );
}
