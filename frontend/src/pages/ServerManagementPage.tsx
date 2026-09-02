import { Ban, ShieldMinus, ShieldPlus, Upload, UserCheck, UserX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, api, fileUrl } from "../api/client";
import type { BulkRevokeResult, ServerSettings, SignupConfig, SignupMode, SystemUser } from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { FileUploadTrigger } from "../components/FileUploadTrigger";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { cycleSort, type SortState } from "../components/SortableHeader";
import { Spinner } from "../components/Spinner";
import { useOrgLabel, useOrgLabelPlural } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

type ReviewView = "orphaned" | "server_admins" | "all";

type AccessReviewConfirmKind = "deactivate" | "ban" | "grantServerAdmin" | "revokeServerAdmin";

/** Sortable columns of the Access Review `DirectoryTable` (Phase E,
 * follow-up UX batch, 2026-08-31) — mirrors `list_org_users`'s own
 * `sort`/`order` contract; `created_at` is the one addition `/system/users`
 * needed beyond that (Org Users has no "Created" column). */
type SystemUserSortKey = "display_name" | "email" | "last_login_at" | "created_at";

function AccessReviewTab() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [view, setView] = useState<ReviewView>("orphaned");
  const [includeDeactivated, setIncludeDeactivated] = useState(false);
  const [search, setSearch] = useState("");
  // Column-header sorting (Phase E) — this table is backend-paginated
  // (`PAGE_SIZE`/`LoadMoreButton`), so sorting has to be honoured
  // server-side, same reasoning as Org Admin's Users table.
  const [sort, setSort] = useState<SortState<SystemUserSortKey> | null>(null);
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
    if (search) params.set("search", search);
    if (sort) {
      params.set("sort", sort.key);
      params.set("order", sort.direction);
    }
    return params;
  }

  async function loadUsers(offset: number, append: boolean) {
    const page = await api.getPage<SystemUser>(`/api/v1/system/users?${listParams(offset).toString()}`);
    setUsers((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    // Deliberately doesn't reset `users` to `null` first (unlike the old
    // pre-Phase-E implementation): the search box now lives inside the
    // same `.side-grid`/`FilterPanel` this list renders, so nulling `users`
    // on every keystroke would unmount the input mid-type (and drop focus)
    // rather than just refresh the rows — same reasoning Org Admin's Users
    // table's `loadUsers` already follows (`null` is only ever the initial,
    // pre-first-fetch state, shown once via the `!users` Spinner guard
    // below). Rows simply stay as-is until the new page resolves.
    await loadUsers(0, false);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, includeDeactivated, search, sort]);

  function applySort(key: SystemUserSortKey) {
    setSort(cycleSort(sort, key));
  }

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

  // Rebuilt on the shared `DirectoryTable` (Phase 0) inside the standard
  // `.side-grid` + `FilterPanel` layout every other directory in this app
  // now uses — replacing the old bare `<table>` + inline filter-control row
  // (2026-08-31, Phase E, follow-up UX batch — see docs/decisions.md).
  // `view`/`includeDeactivated` behave identically to before, just hosted
  // as a `FilterField`/`FilterCheckbox`; `search` and column-header sorting
  // are new (see `list_system_users`'s own docstring for the backend side).
  const usersColumns: DirectoryColumn<SystemUser>[] = [
    { key: "email", label: strings.system.email, sortable: true, render: (u) => u.email },
    { key: "display_name", label: strings.system.name, sortable: true, render: (u) => u.display_name },
    {
      // Comma-joined names have no natural order — not sortable, per style
      // guide "Pattern: sortable column header".
      key: "organizations", label: strings.system.organizations(orgLabelPlural),
      render: (u) =>
        u.organization_names.length > 0
          ? u.organization_names.join(", ")
          : u.organization_count > 0
            ? strings.system.organizationCount(u.organization_count, orgLabel)
            : strings.system.noOrganizations,
    },
    {
      key: "groups", label: strings.system.groups,
      render: (u) => (u.group_names.length > 0 ? u.group_names.join(", ") : "—"),
    },
    {
      key: "last_login_at", label: strings.system.lastLogin, sortable: true,
      render: (u) => (u.last_login_at ? new Date(u.last_login_at).toLocaleString() : strings.system.never),
    },
    {
      key: "created_at", label: strings.system.created, sortable: true,
      render: (u) => new Date(u.created_at).toLocaleDateString(),
    },
    {
      // Consolidated behind one `ActionMenu` (style guide "Pattern: action
      // menu") — up to three secondary, non-primary actions (deactivate/
      // reactivate, ban/unban, grant/revoke server admin) previously sat
      // side by side as separate always-visible buttons on the same row,
      // the exact "two-or-more secondary actions" shape the pattern exists
      // for. Status badges stay outside the menu, visible at a glance.
      key: "actions", label: "",
      render: (u) => (
        <div className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
          {u.is_banned && <span className="text-muted">{strings.system.bannedBadge}</span>}
          {!u.is_active && !u.is_banned && <span className="text-muted">{strings.system.deactivated}</span>}
          {u.is_server_admin && <span className="text-muted">{strings.system.serverAdminBadge}</span>}
          {!u.has_org_membership && (
            <ActionMenu
              triggerLabel={strings.system.usersActionsFor(u.display_name)}
              items={[
                u.is_active
                  ? { label: strings.system.deactivate, icon: <UserX size={14} />, onSelect: () => deactivate(u.user_id) }
                  : { label: strings.system.reactivate, icon: <UserCheck size={14} />, onSelect: () => reactivate(u.user_id) },
                u.is_banned
                  ? { label: strings.system.unban, icon: <Ban size={14} />, onSelect: () => unban(u.user_id) }
                  : { label: strings.system.ban, icon: <Ban size={14} />, onSelect: () => ban(u.user_id) },
                u.is_server_admin
                  ? { label: strings.system.revokeServerAdmin, icon: <ShieldMinus size={14} />, onSelect: () => revokeServerAdmin(u.user_id) }
                  : { label: strings.system.grantServerAdmin, icon: <ShieldPlus size={14} />, onSelect: () => grantServerAdmin(u.user_id) },
              ]}
            />
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="stack">
      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.system.users}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{strings.system.usersHint(orgLabel)}</p>

        {actionError && <div style={{ color: "var(--color-danger)" }}>{actionError}</div>}

        {!users ? (
          <Spinner />
        ) : (
          // `FilterPanel` renders as a full-width bar ABOVE the table
          // (`layout="top"`), not the standard `.side-grid` side layout —
          // this table is wide (columns include email, name, role, project
          // access, actions), and a 240px side sidebar visibly crowded it
          // (follow-up UX fix; see docs/decisions.md and
          // docs/ux-style-guide.md's "Pattern: filter panel placement —
          // side vs. top").
          <div className="stack">
            <FilterPanel
              layout="top"
              sectionKey="serverAccessReviewFilters"
              search={search}
              onSearchChange={setSearch}
              searchPlaceholder={strings.system.searchUsers}
            >
              <FilterField label={strings.system.view}>
                <select className="input" value={view} onChange={(e) => setView(e.target.value as ReviewView)}>
                  <option value="orphaned">{strings.system.viewOrphaned}</option>
                  <option value="server_admins">{strings.system.viewServerAdmins}</option>
                  <option value="all">{strings.system.viewAll}</option>
                </select>
              </FilterField>
              <FilterCheckbox
                label={strings.system.includeDeactivated}
                checked={includeDeactivated}
                onChange={setIncludeDeactivated}
              />
            </FilterPanel>
            <DirectoryTable
              ariaLabel={strings.system.users}
              columns={usersColumns}
              rows={users}
              rowKey={(u) => u.user_id}
              sort={sort}
              onSort={(key) => applySort(key as SystemUserSortKey)}
              total={total}
              onLoadMore={() => loadUsers(users.length, true)}
              emptyState={<p className="text-muted">{strings.system.noUsersFound}</p>}
            />
          </div>
        )}
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
  // Guards the branding fields above against `reload()` — also called
  // from `uploadLogo`/`uploadLoginBackground` below, not just this
  // component's own mount/save. If a background upload's own reload() is
  // still in flight when the user edits and saves a text field right
  // after starting that upload, its response clobbers the edit back to
  // the last-saved value before Save is even clicked. Same real,
  // CI-reproducible race as OrgAdminPage.tsx's advancedDirtyRef — see its
  // own comment and docs/decisions.md.
  const brandingDirtyRef = useRef(false);

  async function reload() {
    const s = await api.get<ServerSettings>("/api/v1/system/branding");
    setSettings(s);
    if (!brandingDirtyRef.current) {
      setAccentColor(s.accent_color_hex);
      setHeaderTitle(s.default_header_title ?? "");
      setOrgLabelSingular(s.org_label_singular ?? "");
      setOrgLabelPlural(s.org_label_plural ?? "");
      setEmailFooterCompanyName(s.email_footer_company_name ?? "");
      setEmailFooterWebsite(s.email_footer_website ?? "");
      setEmailFooterAddress(s.email_footer_address ?? "");
    }
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
      brandingDirtyRef.current = false;
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
      <div className="stack" style={{ gap: "0.25rem" }}>
        <label htmlFor="platform-logo-input">{strings.serverSettings.logo}</label>
        <FileUploadTrigger id="platform-logo-input" accept="image/*" disabled={logoUploading} onSelect={uploadLogo}>
          <Upload size={14} /> {strings.common.chooseFile}
        </FileUploadTrigger>
      </div>
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
          value={headerTitle} onChange={(e) => {
            brandingDirtyRef.current = true;
            setHeaderTitle(e.target.value);
          }}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.headerTitleHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.orgLabelSingular}
        <input
          className="input" placeholder="organisation"
          value={orgLabelSingular} onChange={(e) => {
            brandingDirtyRef.current = true;
            setOrgLabelSingular(e.target.value);
          }}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.orgLabelSingularHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.orgLabelPlural}
        <input
          className="input" placeholder="Organisations"
          value={orgLabelPlural} onChange={(e) => {
            brandingDirtyRef.current = true;
            setOrgLabelPlural(e.target.value);
          }}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.orgLabelPluralHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.accentColor}
        <input
          type="color" value={accentColor} onChange={(e) => {
            brandingDirtyRef.current = true;
            setAccentColor(e.target.value);
          }}
          style={{ width: 60, height: 36, padding: 2 }}
        />
      </label>
      <div className="stack" style={{ gap: "0.25rem" }}>
        <label htmlFor="platform-login-background-input">{strings.serverSettings.loginBackground}</label>
        <FileUploadTrigger
          id="platform-login-background-input"
          accept="image/*"
          disabled={loginBackgroundUploading}
          onSelect={uploadLoginBackground}
        >
          <Upload size={14} /> {strings.common.chooseFile}
        </FileUploadTrigger>
      </div>
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
          value={emailFooterCompanyName} onChange={(e) => {
            brandingDirtyRef.current = true;
            setEmailFooterCompanyName(e.target.value);
          }}
        />
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.serverSettings.emailFooterCompanyNameHint}</span>
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.emailFooterWebsite}
        <input
          className="input" value={emailFooterWebsite} onChange={(e) => {
            brandingDirtyRef.current = true;
            setEmailFooterWebsite(e.target.value);
          }}
        />
      </label>
      <label className="stack" style={{ gap: "0.25rem" }}>
        {strings.serverSettings.emailFooterAddress}
        <textarea
          className="input" rows={3} value={emailFooterAddress} onChange={(e) => {
            brandingDirtyRef.current = true;
            setEmailFooterAddress(e.target.value);
          }}
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
 * The 4 resource-menu groups Server Admin's previous 4-tab bar was
 * converted into. Each key is also the route segment under
 * `/server/management/:group?` (App.tsx), so a group selection is a real
 * navigation, not client-only state. An unrecognised or absent `:group`
 * (including the bare `/server/management` used by every existing link
 * into this page) falls back to "accessReview".
 *
 * Converted from `Tabs` to `ResourceMenu` for cross-page consistency with
 * the other admin-tier pages (Org Admin, Project Admin, Preferences) —
 * a deliberate reversal of the original per-page ≤5-groups Tabs-vs-
 * ResourceMenu call, since this page never exceeded 5 tabs on its own.
 * See `docs/ux-style-guide.md` Principle 1 and `docs/decisions.md`.
 */
type ServerManagementGroupKey = "accessReview" | "branding" | "signup" | "email";

const SERVER_MANAGEMENT_GROUP_KEYS: ServerManagementGroupKey[] = ["accessReview", "branding", "signup", "email"];

/**
 * Server-admin console: access review (C-A-13), platform-wide branding
 * defaults, and the public sign-up mode — previously two separate nav
 * entries, now consolidated here since all are the same kind of
 * "deployment-wide, not any one organisation's" setting.
 * `/server/organisations` (every org on the deployment, with create/
 * disable/delete) stays a separate page — its own row-per-org table
 * doesn't fit alongside these groups.
 */
export function ServerManagementPage() {
  const { group: groupParam } = useParams<{ group?: string }>();

  const activeGroup: ServerManagementGroupKey = SERVER_MANAGEMENT_GROUP_KEYS.includes(
    groupParam as ServerManagementGroupKey
  )
    ? (groupParam as ServerManagementGroupKey)
    : "accessReview";

  const groups: ResourceMenuGroupDef<ServerManagementGroupKey>[] = [
    { key: "accessReview", label: strings.orgAdmin.accessReview, href: "/server/management/accessReview" },
    { key: "branding", label: strings.serverSettings.title, href: "/server/management/branding" },
    { key: "signup", label: strings.signupSettings.title, href: "/server/management/signup" },
    { key: "email", label: strings.system.emailTab, href: "/server/management/email" },
  ];

  return (
    <div className="stack">
      <ResourceMenu
        title={strings.nav.serverManagement}
        ariaLabel={strings.system.sectionsNav}
        groups={groups}
        active={activeGroup}
      >
        {activeGroup === "accessReview" && <AccessReviewTab />}
        {activeGroup === "branding" && <PlatformBrandingTab />}
        {activeGroup === "signup" && <SignupModeTab />}
        {activeGroup === "email" && <TestEmailTab />}
      </ResourceMenu>
    </div>
  );
}
