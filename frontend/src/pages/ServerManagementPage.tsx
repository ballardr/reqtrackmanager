import { useEffect, useRef, useState } from "react";

import { ApiError, api, fileUrl } from "../api/client";
import type { BulkRevokeResult, ServerSettings, SignupConfig, SignupMode, SystemUser } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { Tabs, tabPanelProps } from "../components/Tabs";
import { useOrgLabel, useOrgLabelPlural } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

type ReviewView = "orphaned" | "server_admins" | "all";

type AccessReviewConfirmKind = "deactivate" | "ban" | "grantServerAdmin" | "revokeServerAdmin";

function AccessReviewTab() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [view, setView] = useState<ReviewView>("orphaned");
  const [includeDeactivated, setIncludeDeactivated] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [patResult, setPatResult] = useState<string | null>(null);
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const { showToast } = useToast();
  // ConfirmDialog (Tier 1) state for the account/access actions below —
  // converted from `window.confirm` per the sixth-pass audit's
  // "Confirmation and feedback rollout, precisely" list.
  const [confirmAction, setConfirmAction] = useState<{ kind: AccessReviewConfirmKind; userId: string } | null>(null);
  const [revokeAllPatsOpen, setRevokeAllPatsOpen] = useState(false);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (view === "orphaned") params.set("no_org_membership", "true");
    if (view === "server_admins") params.set("is_server_admin", "true");
    if (!includeDeactivated) params.set("is_active", "true");
    return params;
  }

  async function loadUsers(offset: number, append: boolean) {
    const page = await api.getPage<SystemUser>(`/api/v1/system/users?${listParams(offset).toString()}`);
    setUsers((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    setUsers(null);
    await loadUsers(0, false);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, includeDeactivated]);

  async function runAction(action: () => Promise<void>, successMessage?: string) {
    setActionError(null);
    try {
      await action();
      await reload();
      if (successMessage) showToast(successMessage);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function deactivate(userId: string) {
    setConfirmAction({ kind: "deactivate", userId });
  }

  function reactivate(userId: string) {
    runAction(() => api.post(`/api/v1/system/users/${userId}/reactivate`), strings.system.reactivatedToast);
  }

  function ban(userId: string) {
    setConfirmAction({ kind: "ban", userId });
  }

  function unban(userId: string) {
    runAction(() => api.post(`/api/v1/system/users/${userId}/unban`), strings.system.unbannedToast);
  }

  function grantServerAdmin(userId: string) {
    setConfirmAction({ kind: "grantServerAdmin", userId });
  }

  function revokeServerAdmin(userId: string) {
    setConfirmAction({ kind: "revokeServerAdmin", userId });
  }

  function confirmPendingAction() {
    if (!confirmAction) return;
    const { kind, userId } = confirmAction;
    setConfirmAction(null);
    switch (kind) {
      case "deactivate":
        runAction(() => api.post(`/api/v1/system/users/${userId}/deactivate`), strings.system.deactivatedToast);
        break;
      case "ban":
        runAction(() => api.post(`/api/v1/system/users/${userId}/ban`), strings.system.bannedToast);
        break;
      case "grantServerAdmin":
        runAction(
          () => api.put(`/api/v1/system/users/${userId}/server-admin`, { is_server_admin: true }),
          strings.system.grantedServerAdminToast
        );
        break;
      case "revokeServerAdmin":
        runAction(
          () => api.put(`/api/v1/system/users/${userId}/server-admin`, { is_server_admin: false }),
          strings.system.revokedServerAdminToast
        );
        break;
    }
  }

  async function revokeAllPatsPlatformWide() {
    setRevokeAllPatsOpen(false);
    try {
      const result = await api.post<BulkRevokeResult>("/api/v1/system/pats/revoke-all");
      setPatResult(strings.system.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const confirmActionCopy: Record<AccessReviewConfirmKind, { title: string; message: string; confirmLabel: string }> = {
    deactivate: { title: strings.system.deactivateTitle, message: strings.system.deactivateConfirm, confirmLabel: strings.system.deactivate },
    ban: { title: strings.system.banTitle, message: strings.system.banConfirm(orgLabel), confirmLabel: strings.system.ban },
    grantServerAdmin: {
      title: strings.system.grantServerAdminTitle,
      message: strings.system.grantServerAdminConfirm(orgLabelPlural),
      confirmLabel: strings.system.grantServerAdmin,
    },
    revokeServerAdmin: {
      title: strings.system.revokeServerAdminTitle,
      message: strings.system.revokeServerAdminConfirm,
      confirmLabel: strings.system.revokeServerAdmin,
    },
  };

  return (
    <div className="stack">
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.system.users}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.system.usersHint(orgLabel)}</p>

        <div className="row" style={{ gap: "1rem", alignItems: "center" }}>
          <label className="row" style={{ gap: "0.4rem" }}>
            {strings.system.view}
            <select className="input" value={view} onChange={(e) => setView(e.target.value as ReviewView)}>
              <option value="orphaned">{strings.system.viewOrphaned}</option>
              <option value="server_admins">{strings.system.viewServerAdmins}</option>
              <option value="all">{strings.system.viewAll}</option>
            </select>
          </label>
          <label className="row" style={{ gap: "0.4rem" }}>
            <input
              type="checkbox"
              checked={includeDeactivated}
              onChange={(e) => setIncludeDeactivated(e.target.checked)}
            />
            {strings.system.includeDeactivated}
          </label>
        </div>

        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}

        {!users ? (
          <Spinner />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>{strings.system.email}</th>
                  <th>{strings.system.name}</th>
                  <th>{strings.system.organizations(orgLabelPlural)}</th>
                  <th>{strings.system.groups}</th>
                  <th>{strings.system.lastLogin}</th>
                  <th>{strings.system.created}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id}>
                    <td>{u.email}</td>
                    <td>{u.display_name}</td>
                    <td>
                      {u.organization_names.length > 0
                        ? u.organization_names.join(", ")
                        : u.organization_count > 0
                          ? strings.system.organizationCount(u.organization_count, orgLabel)
                          : strings.system.noOrganizations}
                    </td>
                    <td>{u.group_names.length > 0 ? u.group_names.join(", ") : "—"}</td>
                    <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : strings.system.never}</td>
                    <td>{new Date(u.created_at).toLocaleDateString()}</td>
                    <td>
                      <div className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
                        {u.is_banned && <span className="text-muted">{strings.system.bannedBadge}</span>}
                        {!u.is_active && !u.is_banned && <span className="text-muted">{strings.system.deactivated}</span>}
                        {u.is_server_admin && <span className="text-muted">{strings.system.serverAdminBadge}</span>}
                        {!u.has_org_membership &&
                          (u.is_active ? (
                            <button className="btn" onClick={() => deactivate(u.user_id)}>
                              {strings.system.deactivate}
                            </button>
                          ) : (
                            <button className="btn" onClick={() => reactivate(u.user_id)}>
                              {strings.system.reactivate}
                            </button>
                          ))}
                        {!u.has_org_membership &&
                          (u.is_banned ? (
                            <button className="btn" onClick={() => unban(u.user_id)}>
                              {strings.system.unban}
                            </button>
                          ) : (
                            <button className="btn btn-danger" onClick={() => ban(u.user_id)}>
                              {strings.system.ban}
                            </button>
                          ))}
                        {u.is_server_admin ? (
                          <button className="btn btn-danger" onClick={() => revokeServerAdmin(u.user_id)}>
                            {strings.system.revokeServerAdmin}
                          </button>
                        ) : (
                          <button className="btn" onClick={() => grantServerAdmin(u.user_id)}>
                            {strings.system.grantServerAdmin}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {users && <LoadMoreButton loaded={users.length} total={total} onClick={() => loadUsers(users.length, true)} />}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.system.patRevokeAll}</h2>
        <p className="text-muted">{strings.system.patRevokeAllHint(orgLabelPlural)}</p>
        <button className="btn btn-danger" onClick={() => setRevokeAllPatsOpen(true)} style={{ alignSelf: "flex-start" }}>
          {strings.system.patRevokeAll}
        </button>
        {patResult && <div style={{ color: "var(--color-accent)" }}>{patResult}</div>}
      </div>

      {confirmAction && (
        <ConfirmDialog
          title={confirmActionCopy[confirmAction.kind].title}
          message={confirmActionCopy[confirmAction.kind].message}
          confirmLabel={confirmActionCopy[confirmAction.kind].confirmLabel}
          onConfirm={confirmPendingAction}
          onCancel={() => setConfirmAction(null)}
        />
      )}
      {revokeAllPatsOpen && (
        <ConfirmDialog
          title={strings.system.patRevokeAllTitle}
          message={strings.system.patRevokeAllConfirm}
          confirmLabel={strings.system.patRevokeAll}
          onConfirm={revokeAllPatsPlatformWide}
          onCancel={() => setRevokeAllPatsOpen(false)}
        />
      )}
    </div>
  );
}

function PlatformBrandingTab() {
  const currentOrgLabel = useOrgLabel();
  const [settings, setSettings] = useState<ServerSettings | null>(null);
  const [accentColor, setAccentColor] = useState("#475569");
  const [headerTitle, setHeaderTitle] = useState("");
  const [orgLabelSingular, setOrgLabelSingular] = useState("");
  const [orgLabelPlural, setOrgLabelPlural] = useState("");
  const [emailFooterCompanyName, setEmailFooterCompanyName] = useState("");
  const [emailFooterWebsite, setEmailFooterWebsite] = useState("");
  const [emailFooterAddress, setEmailFooterAddress] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);

  async function reload() {
    const s = await api.get<ServerSettings>("/api/v1/system/branding");
    setSettings(s);
    setAccentColor(s.accent_color_hex);
    setHeaderTitle(s.default_header_title ?? "");
    setOrgLabelSingular(s.org_label_singular ?? "");
    setOrgLabelPlural(s.org_label_plural ?? "");
    setEmailFooterCompanyName(s.email_footer_company_name ?? "");
    setEmailFooterWebsite(s.email_footer_website ?? "");
    setEmailFooterAddress(s.email_footer_address ?? "");
  }

  useEffect(() => {
    reload();
  }, []);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await api.put("/api/v1/system/branding", {
        accent_color_hex: accentColor,
        default_header_title: headerTitle || null,
        org_label_singular: orgLabelSingular || null,
        org_label_plural: orgLabelPlural || null,
        email_footer_company_name: emailFooterCompanyName || null,
        email_footer_website: emailFooterWebsite || null,
        email_footer_address: emailFooterAddress || null,
      });
      setSaved(true);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
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
      await api.postFile("/api/v1/system/branding/logo", file);
      await reload();
      setLogoUploaded(true);
    } catch (err) {
      setLogoError(err instanceof Error ? err.message : strings.common.error);
    } finally {
      setLogoUploading(false);
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
      await api.postFile("/api/v1/system/branding/login-background", file);
      await reload();
      setLoginBackgroundUploaded(true);
    } catch (err) {
      setLoginBackgroundError(err instanceof Error ? err.message : strings.common.error);
    } finally {
      setLoginBackgroundUploading(false);
    }
  }

  if (!settings) return <Spinner />;

  return (
    <div className="card stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.serverSettings.hint(currentOrgLabel)}</p>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.logo}
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
      {logoUploaded && <div style={{ color: "var(--color-accent)" }}>{strings.serverSettings.logoUploaded}</div>}
      {settings.default_logo_file_id && (
        <img src={fileUrl(settings.default_logo_file_id)} alt="" style={{ height: 40 }} />
      )}
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.headerTitle}
        <input
          className="input" placeholder={strings.appName}
          value={headerTitle} onChange={(e) => setHeaderTitle(e.target.value)}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.headerTitleHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.orgLabelSingular}
        <input
          className="input" placeholder="organisation"
          value={orgLabelSingular} onChange={(e) => setOrgLabelSingular(e.target.value)}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.orgLabelSingularHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.orgLabelPlural}
        <input
          className="input" placeholder="Organisations"
          value={orgLabelPlural} onChange={(e) => setOrgLabelPlural(e.target.value)}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.orgLabelPluralHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.accentColor}
        <input
          type="color" value={accentColor} onChange={(e) => setAccentColor(e.target.value)}
          style={{ width: 60, height: 36, padding: 2 }}
        />
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.loginBackground}
        <input
          type="file"
          accept="image/*"
          disabled={loginBackgroundUploading}
          onChange={(e) => e.target.files?.[0] && uploadLoginBackground(e.target.files[0])}
        />
      </label>
      {loginBackgroundUploading && <Spinner />}
      {loginBackgroundError && <div style={{ color: "var(--color-danger)" }}>{loginBackgroundError}</div>}
      {loginBackgroundUploaded && (
        <div style={{ color: "var(--color-accent)" }}>{strings.serverSettings.loginBackgroundUploaded}</div>
      )}
      {settings.default_login_background_file_id && (
        <img src={fileUrl(settings.default_login_background_file_id)} alt="" style={{ maxHeight: 100, borderRadius: 4 }} />
      )}
      <hr style={{ width: "100%", border: "none", borderTop: "1px solid var(--color-border)" }} />
      <h3 style={{ margin: 0 }}>{strings.serverSettings.emailFooterTitle}</h3>
      <p className="text-muted" style={{ margin: 0 }}>{strings.serverSettings.emailFooterHint(currentOrgLabel)}</p>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.emailFooterCompanyName}
        <input
          className="input" placeholder={strings.appName}
          value={emailFooterCompanyName} onChange={(e) => setEmailFooterCompanyName(e.target.value)}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.emailFooterCompanyNameHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.emailFooterWebsite}
        <input
          className="input" value={emailFooterWebsite} onChange={(e) => setEmailFooterWebsite(e.target.value)}
        />
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.emailFooterAddress}
        <textarea
          className="input" rows={3} value={emailFooterAddress} onChange={(e) => setEmailFooterAddress(e.target.value)}
        />
      </label>
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
        {strings.serverSettings.save}
      </button>
      {saved && <div style={{ color: "var(--color-accent)" }}>{strings.serverSettings.saved}</div>}
    </div>
  );
}

function TestEmailTab() {
  const [recipient, setRecipient] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function send() {
    setError(null);
    setSuccess(false);
    setSending(true);
    try {
      await api.post("/api/v1/system/test-email", recipient ? { to_email: recipient } : {});
      setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.common.error);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="card stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.system.testEmailHint}</p>
      <div className="row">
        <input
          className="input"
          type="email"
          placeholder={strings.system.testEmailRecipientPlaceholder}
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
        />
        <button className="btn btn-primary" onClick={send} disabled={sending}>
          {sending ? strings.system.testEmailSending : strings.system.testEmail}
        </button>
      </div>
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      {success && <div style={{ color: "var(--color-accent)" }}>{strings.system.testEmailSent}</div>}
    </div>
  );
}

function SignupModeTab() {
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const [config, setConfig] = useState<SignupConfig | null>(null);
  const [mode, setMode] = useState<SignupMode>("disabled");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const c = await api.get<SignupConfig>("/api/v1/system/signup-config");
    setConfig(c);
    setMode(c.signup_mode);
  }

  useEffect(() => {
    reload();
  }, []);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await api.put("/api/v1/system/signup-config", { signup_mode: mode });
      setSaved(true);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.common.error);
    }
  }

  if (!config) return <Spinner />;

  return (
    <div className="card stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.signupSettings.hint}</p>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.signupSettings.mode}
        <select className="input" value={mode} onChange={(e) => setMode(e.target.value as SignupMode)}>
          <option value="disabled">{strings.signupSettings.modeDisabled}</option>
          <option value="always_on">{strings.signupSettings.modeAlwaysOn(orgLabel)}</option>
          <option value="org_specified">{strings.signupSettings.modeOrgSpecified(orgLabel)}</option>
        </select>
      </label>
      {mode === "org_specified" && (
        <p className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.signupSettings.modeOrgSpecifiedHint(orgLabelPlural)}</p>
      )}
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
        {strings.signupSettings.save}
      </button>
      {saved && <div style={{ color: "var(--color-accent)" }}>{strings.signupSettings.saved}</div>}
    </div>
  );
}

/**
 * Server-admin console, tabbed like Project admin: access review (C-A-13),
 * platform-wide branding defaults, and the public sign-up mode — previously
 * two separate nav entries, now three tabs consolidated here since all are
 * the same kind of "deployment-wide, not any one organisation's" setting.
 * `/server/organisations` (every org on the deployment, with create/
 * disable/delete) stays a separate page — its own row-per-org table
 * doesn't fit a tab alongside these.
 */
export function ServerManagementPage() {
  const [tab, setTab] = useState<"accessReview" | "branding" | "signup" | "email">("accessReview");

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "accessReview", label: strings.orgAdmin.accessReview },
    { key: "branding", label: strings.serverSettings.title },
    { key: "signup", label: strings.signupSettings.title },
    { key: "email", label: strings.system.emailTab },
  ];

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.nav.serverManagement}</h1>

      <Tabs idPrefix="server-management-tabs" tabs={tabs} active={tab} onChange={setTab} />

      {tab === "accessReview" && (
        <div {...tabPanelProps("server-management-tabs", "accessReview")}>
          <AccessReviewTab />
        </div>
      )}
      {tab === "branding" && (
        <div {...tabPanelProps("server-management-tabs", "branding")}>
          <PlatformBrandingTab />
        </div>
      )}
      {tab === "signup" && (
        <div {...tabPanelProps("server-management-tabs", "signup")}>
          <SignupModeTab />
        </div>
      )}
      {tab === "email" && (
        <div {...tabPanelProps("server-management-tabs", "email")}>
          <TestEmailTab />
        </div>
      )}
    </div>
  );
}
