import { Ban, Eye, KeyRound, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { BulkRevokeResult, GrantableServerRole, ServerRole, SystemUser } from "../api/types";
import { SERVER_ROLE_LABEL } from "../api/types";
import { ActionMenu } from "../components/ActionMenu";
import { AddUserMenu } from "../components/AddUserMenu";
import { Badge } from "../components/Badge";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { DirectoryTable } from "../components/DirectoryTable";
import { ForceCredentialResetModal } from "../components/ForceCredentialResetModal";
import { FieldHelp } from "../components/FieldHelp";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { FilterSelect } from "../components/FilterSelect";
import { Modal } from "../components/Modal";
import { PersonalDataPolicyPanel } from "../components/PersonalDataPolicyPanel";
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import { ResourceMenu } from "../components/ResourceMenu";
import { SendPasswordResetDialog } from "../components/SendPasswordResetDialog";
import { cycleSort, type SortState } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { useOrgLabel, useOrgLabelPlural } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { AddUserModal, type AddUserMode } from "./AddUserModal";
import { AnnouncementsPanel } from "../components/AnnouncementsPanel";
import { PoliciesPanel } from "../components/PoliciesPanel";
import { ServerModulesTab } from "./ServerModulesTab";
import { ServerReportFontsTab } from "./ServerReportFontsTab";
import { FileUploadsTab, PlatformBrandingTab, ServerDetailsTab, SignupModeTab, TestEmailTab } from "./ServerSettingsGroups";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useServerAccess } from "../hooks/useServerAccess";

const strings = t();

const PAGE_SIZE = 30;

/** The server roles in the order the assignment dialog lists them. */
const SERVER_ROLE_ORDER: ServerRole[] = [
  "server_admin", "module_administrator", "subscription_manager", "subscription_removal_authority",
];

type ReviewView = "orphaned" | "server_admins" | "all";

type AccessReviewConfirmKind =
  | "deactivate"
  | "ban"
  | "forceReset"
  | "grantServerAdmin"
  | "revokeServerAdmin"
  | "grantServerRole"
  | "revokeServerRole";

/** Sortable columns of the Access Review `DirectoryTable` — mirrors `list_org_users`'s own
 * `sort`/`order` contract; `created_at` is the one addition `/system/users`
 * needed beyond that (Org Users has no "Created" column). */
type SystemUserSortKey = "display_name" | "email" | "last_login_at" | "created_at";

function AccessReviewTab() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [view, setView] = useState<ReviewView>("orphaned");
  const [includeDeactivated, setIncludeDeactivated] = useState(false);
  const [search, setSearch] = useState("");
  // Column-header sorting — this table is backend-paginated
  // (`PAGE_SIZE`/`LoadMoreButton`), so sorting has to be honoured
  // server-side, same reasoning as Org Admin's Users table.
  const [sort, setSort] = useState<SortState<SystemUserSortKey> | null>(null);
  const orgLabel = useOrgLabel();
  const orgLabelPlural = useOrgLabelPlural();
  const { showToast } = useToast();
  // ConfirmDialog (Tier 1) state for the account/access actions below —
  // converted from `window.confirm` per the sixth-pass audit's
  // "Confirmation and feedback rollout, precisely" list.
  const [confirmAction, setConfirmAction] = useState<{ kind: AccessReviewConfirmKind; userId: string; role?: GrantableServerRole } | null>(null);
  const [revokeAllPatsOpen, setRevokeAllPatsOpen] = useState(false);
  const [addUserMode, setAddUserMode] = useState<AddUserMode | null>(null);
  // Password reset: one person's emailed link (Tier 1 dialog) and the wide "force a credential reset" dialog.
  const [resetLinkUser, setResetLinkUser] = useState<SystemUser | null>(null);
  const [forceResetOpen, setForceResetOpen] = useState(false);
  // The full groups list and the server-
  // roles toggles both moved off the row (an unbounded joined string and an
  // always-visible dropdown respectively) into modals opened from the row's
  // `ActionMenu`. Tracked by id, not the `SystemUser` object itself, so the
  // modal re-derives its content from the current `users` state below —
  // otherwise a role toggle inside the modal would keep showing the
  // pre-toggle checked state after `reload()` refreshes `users`.
  const [viewGroupsUserId, setViewGroupsUserId] = useState<string | null>(null);
  const [assignRolesUserId, setAssignRolesUserId] = useState<string | null>(null);
  // Per-row "show all N" expansion for the Organisations column (mirrors
  // Org Admin's "View access" panel `expandedAccessProjectIds` — see
  // `docs/ux-style-guide.md`'s "Pattern: role display").
  const [expandedOrgUserIds, setExpandedOrgUserIds] = useState<Set<string>>(new Set());

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

  // Applies only the newest load's response: switching the view and then
  // re-typing a search fires two loads, and the older one could land last
  // (found 2026-10-05).
  const beginLoad = useRequestSequence();

  async function loadUsers(offset: number, append: boolean) {
    const isLatest = beginLoad();
    const page = await api.getPage<SystemUser>(`/api/v1/system/users?${listParams(offset).toString()}`);
    if (!isLatest()) return;
    setUsers((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    // Deliberately doesn't reset `users` to `null` first (unlike the old
    // implementation): the search box now lives inside the
    // same `.side-grid`/`FilterPanel` this list renders, so nulling `users`
    // on every keystroke would unmount the input mid-type (and drop focus)
    // rather than just refresh the rows — same reasoning Org Admin's Users
    // table's `loadUsers` already follows (`null` is only ever the initial,
    // pre-first-fetch state, shown once via the `!users` Spinner guard
    // below). Rows simply stay as-is until the new page resolves.
    await loadUsers(0, false);
  }

  useLoadOnChange(reload, [view, includeDeactivated, search, sort]);

  function applySort(key: SystemUserSortKey) {
    setSort(cycleSort(sort, key));
  }

  function toggleExpandedOrgs(userId: string) {
    setExpandedOrgUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  }

  async function runAction(action: () => Promise<void>, successMessage?: string) {
    try {
      await action();
      await reload();
      if (successMessage) showToast(successMessage);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /** After "Add user": toast, and for a created account list it (all users, filtered to its email) so the new row is in view. */
  function userAdded(email: string, mode: AddUserMode) {
    showToast(mode === "invite" ? strings.system.addUserInvited(email) : strings.system.addUserCreated(email));
    if (mode === "password") {
      setView("all");
      setSearch(email);
    }
  }

  function deactivate(userId: string) {
    setConfirmAction({ kind: "deactivate", userId });
  }

  function reactivate(userId: string) {
    runAction(
      () => api.post(`/api/v1/system/users/${userId}/status`, { action: "reactivate" }),
      strings.system.reactivatedToast
    );
  }

  function ban(userId: string) {
    setConfirmAction({ kind: "ban", userId });
  }

  function unban(userId: string) {
    runAction(() => api.post(`/api/v1/system/users/${userId}/status`, { action: "unban" }), strings.system.unbannedToast);
  }

  function forceReset(userId: string) {
    setConfirmAction({ kind: "forceReset", userId });
  }

  function grantServerAdmin(userId: string) {
    setConfirmAction({ kind: "grantServerAdmin", userId });
  }

  function revokeServerAdmin(userId: string) {
    setConfirmAction({ kind: "revokeServerAdmin", userId });
  }

  function grantServerRole(userId: string, role: GrantableServerRole) {
    setConfirmAction({ kind: "grantServerRole", userId, role });
  }

  function revokeServerRole(userId: string, role: GrantableServerRole) {
    setConfirmAction({ kind: "revokeServerRole", userId, role });
  }

  function confirmPendingAction() {
    if (!confirmAction) return;
    const { kind, userId, role } = confirmAction;
    setConfirmAction(null);
    switch (kind) {
      case "deactivate":
        runAction(
          () => api.post(`/api/v1/system/users/${userId}/status`, { action: "deactivate" }),
          strings.system.deactivatedToast
        );
        break;
      case "ban":
        runAction(() => api.post(`/api/v1/system/users/${userId}/status`, { action: "ban" }), strings.system.bannedToast);
        break;
      case "forceReset":
        runAction(
          () => api.post("/api/v1/system/credentials/force-reset", { scope: "user", user_id: userId, reset_2fa: false, send_links: true }),
          strings.passwordReset.forceActionToast
        );
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
      case "grantServerRole":
        if (role) {
          runAction(
            () => api.post(`/api/v1/system/users/${userId}/server-roles`, { role }),
            strings.system.serverRoleCopy[role].granted
          );
        }
        break;
      case "revokeServerRole":
        if (role) {
          runAction(
            () => api.delete(`/api/v1/system/users/${userId}/server-roles/${role}`),
            strings.system.serverRoleCopy[role].revoked
          );
        }
        break;
    }
  }

  async function revokeAllPatsPlatformWide() {
    setRevokeAllPatsOpen(false);
    try {
      const result = await api.post<BulkRevokeResult>("/api/v1/system/pats/revoke-all");
      showToast(strings.system.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const confirmActionCopy: Record<AccessReviewConfirmKind, { title: string; message: string; confirmLabel: string }> = {
    deactivate: { title: strings.system.deactivateTitle, message: strings.system.deactivateConfirm, confirmLabel: strings.system.deactivate },
    ban: { title: strings.system.banTitle, message: strings.system.banConfirm(orgLabel), confirmLabel: strings.system.ban },
    forceReset: {
      title: strings.passwordReset.forceActionTitle,
      message: strings.passwordReset.forceActionMessage,
      confirmLabel: strings.passwordReset.forceActionConfirm,
    },
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
    grantServerRole: {
      title: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].grantTitle : "",
      message: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].grantConfirm : "",
      confirmLabel: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].grant : "",
    },
    revokeServerRole: {
      title: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].revokeTitle : "",
      message: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].revokeConfirm : "",
      confirmLabel: confirmAction?.role ? strings.system.serverRoleCopy[confirmAction.role].revoke : "",
    },
  };

  // Rebuilt on the shared `DirectoryTable` inside the standard
  // `.side-grid` + `FilterPanel` layout every other directory in this app
  // now uses — replacing the old bare `<table>` + inline filter-control row
  // (docs/decisions.md).
  // `view`/`includeDeactivated` behave identically to before, just hosted
  // as a `FilterField`/`FilterCheckbox`; `search` and column-header sorting
  // are new (see `list_system_users`'s own docstring for the backend side).
  const usersColumns: DirectoryColumn<SystemUser>[] = [
    { key: "email", label: strings.system.email, sortable: true, render: (u) => u.email },
    { key: "display_name", label: strings.system.name, sortable: true, render: (u) => u.display_name },
    {
      // Comma-joined names have no natural order — not sortable, per style
      // guide "Pattern: sortable column header".
      // Joining every org name unconditionally became unreadable
      // for a user in many orgs — per the user's own ask, orgs stay inline
      // (typically far fewer than groups) but gain a "show all N" toggle
      // past 2, mirroring Org Admin's "View access" panel role-expansion
      // pattern rather than moving to a modal like Groups below.
      key: "organizations", label: strings.system.organizations(orgLabelPlural),
      render: (u) => {
        if (u.organization_names.length === 0) {
          return u.organization_count > 0
            ? strings.system.organizationCount(u.organization_count, orgLabel)
            : strings.system.noOrganizations;
        }
        const expanded = expandedOrgUserIds.has(u.user_id);
        const canExpand = u.organization_names.length > 2;
        const shownNames = expanded || !canExpand ? u.organization_names : u.organization_names.slice(0, 2);
        return (
          <span className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }}>
            <span>{shownNames.join(", ")}</span>
            {canExpand && (
              <button type="button" className="btn btn-sm" onClick={() => toggleExpandedOrgs(u.user_id)}>
                {expanded
                  ? strings.system.showFewerOrganizations
                  : strings.system.showAllOrganizations(u.organization_names.length)}
              </button>
            )}
          </span>
        );
      },
    },
    {
      // Groups have no cap the way orgs
      // effectively do, so instead of an inline "show all" toggle (which
      // could still push the row very wide) the full list moved to a
      // modal off this row's `ActionMenu` ("View groups") — this column
      // now shows only a short summary.
      key: "groups", label: strings.system.groups,
      render: (u) => {
        if (u.group_names.length === 0) return "—";
        const shown = u.group_names.slice(0, 2).join(", ");
        return u.group_names.length > 2 ? `${shown}, ${strings.system.groupsMore(u.group_names.length - 2)}` : shown;
      },
    },
    {
      key: "status", label: strings.system.status,
      render: (u) =>
        u.is_banned ? (
          <Badge tone="danger">{strings.system.bannedBadge}</Badge>
        ) : !u.is_active ? (
          <Badge tone="warning">{strings.system.deactivated}</Badge>
        ) : (
          <Badge tone="accent">{strings.system.statusActive}</Badge>
        ),
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
      // menu"). The menu itself now
      // renders for every row, not just org-less ones — "Assign server
      // roles" (moved here from the old always-visible "Server roles"
      // `MultiSelectDropdown` column) and "View
      // groups" apply regardless of org membership (I-M-08: a server admin
      // can hold an organisation of their own). Deactivate/reactivate and
      // ban/unban stay scoped to org-less accounts only — that gate was
      // protecting those two specific actions, not the menu as a whole, so
      // it moves to the item list rather than being removed outright. The
      // old standalone "Server admin" badge stays dropped: the row's other
      // visible state already shows the same fact, so a separate badge
      // would just duplicate it. Banned/deactivated badges stay outside the
      // menu, visible at a glance.
      key: "actions", label: "",
      render: (u) => (
        <div className="row" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
          <ActionMenu
            triggerLabel={strings.system.usersActionsFor(u.display_name)}
            items={[
              { label: strings.system.assignServerRoles, icon: <ShieldCheck size={14} />, onSelect: () => setAssignRolesUserId(u.user_id) },
              { label: strings.passwordReset.sendLinkAction, icon: <KeyRound size={14} />, onSelect: () => setResetLinkUser(u) },
              { label: strings.passwordReset.forceActionConfirm, icon: <KeyRound size={14} />, onSelect: () => forceReset(u.user_id) },
              ...(u.group_names.length > 0
                ? [{ label: strings.system.viewGroups, icon: <Eye size={14} />, onSelect: () => setViewGroupsUserId(u.user_id) }]
                : []),
              ...(!u.has_org_membership
                ? [
                    u.is_active
                      ? { label: strings.system.deactivate, icon: <UserX size={14} />, onSelect: () => deactivate(u.user_id) }
                      : { label: strings.system.reactivate, icon: <UserCheck size={14} />, onSelect: () => reactivate(u.user_id) },
                    u.is_banned
                      ? { label: strings.system.unban, icon: <Ban size={14} />, onSelect: () => unban(u.user_id) }
                      : { label: strings.system.ban, icon: <Ban size={14} />, onSelect: () => ban(u.user_id) },
                  ]
                : []),
            ]}
          />
        </div>
      ),
    },
  ];

  const viewGroupsUser = users?.find((u) => u.user_id === viewGroupsUserId) ?? null;
  const assignRolesUser = users?.find((u) => u.user_id === assignRolesUserId) ?? null;

  return (
    <div className="stack">
      <CollapsibleSection
        sectionKey="serverManagement.users" title={strings.system.users} help={strings.system.usersHint(orgLabel)} collapsible={false}
      >
        <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap", gap: "var(--space-3)" }}>
          <button className="btn" onClick={() => setForceResetOpen(true)}>{strings.passwordReset.forceOpen}</button>
          <AddUserMenu onInvite={() => setAddUserMode("invite")} onNewUser={() => setAddUserMode("password")} />
        </div>

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
              <FilterSelect
                label={strings.system.view}
                value={view}
                onChange={setView}
                options={[{ value: "orphaned", label: strings.system.viewOrphaned }, { value: "server_admins", label: strings.system.viewServerAdmins }, { value: "all", label: strings.system.viewAll }]}
              />
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
      </CollapsibleSection>

      <CollapsibleSection
        sectionKey="serverManagement.tokens" title={strings.system.patRevokeAll} help={strings.system.patRevokeAllHint(orgLabelPlural)} collapsible={false}
      >
        <button className="btn btn-danger" onClick={() => setRevokeAllPatsOpen(true)} style={{ alignSelf: "flex-start" }}>
          {strings.system.patRevokeAll}
        </button>
      </CollapsibleSection>

      {addUserMode && <AddUserModal mode={addUserMode} onClose={() => setAddUserMode(null)} onCreated={userAdded} />}
      {resetLinkUser && (
        <SendPasswordResetDialog
          userName={resetLinkUser.display_name}
          endpoint={`/api/v1/system/users/${resetLinkUser.user_id}/password-reset`}
          onClose={() => setResetLinkUser(null)}
        />
      )}
      {forceResetOpen && <ForceCredentialResetModal onClose={() => setForceResetOpen(false)} onDone={() => void reload()} />}
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
          message={strings.system.patRevokeAllConfirm(strings.system.patRevokeAllTyped)}
          confirmLabel={strings.system.patRevokeAll}
          requireTypedText={strings.system.patRevokeAllTyped}
          onConfirm={revokeAllPatsPlatformWide}
          onCancel={() => setRevokeAllPatsOpen(false)}
        />
      )}
      {viewGroupsUser && (
        <Modal title={strings.system.groupsModalTitle(viewGroupsUser.display_name)} onClose={() => setViewGroupsUserId(null)}>
          {viewGroupsUser.group_names.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>{strings.system.noGroups}</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {viewGroupsUser.group_names.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          )}
        </Modal>
      )}
      {assignRolesUser && (
        // Checkboxes rendered directly rather than via `MultiSelectDropdown`
        // (which OrgAdminPage's own Roles column uses inline in a table
        // cell): this modal is already the "opened" state, so a second,
        // nested disclosure control (a dropdown-in-a-modal) would just add
        // an extra click with no benefit — see docs/decisions.md, Platform
        // review 2026-09.
        <Modal
          title={strings.system.assignServerRolesModalTitle(assignRolesUser.display_name)}
          onClose={() => setAssignRolesUserId(null)}
        >
          <div
            role="group"
            aria-label={strings.system.serverRolesFor(assignRolesUser.display_name)}
            className="stack"
            style={{ gap: "0.6rem" }}
          >
            {SERVER_ROLE_ORDER.map((role) => {
              const checked = role === "server_admin" ? assignRolesUser.is_server_admin : assignRolesUser.server_roles.includes(role);
              const roleLabel = SERVER_ROLE_LABEL[role];
              return (
                <div key={role} className="row" style={{ gap: "var(--space-3)" }}>
                  <label className="row" style={{ gap: "var(--space-3)" }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      aria-label={
                        checked
                          ? strings.system.revokeServerRole(roleLabel, assignRolesUser.display_name)
                          : strings.system.grantServerRole(roleLabel, assignRolesUser.display_name)
                      }
                      onChange={() =>
                        role === "server_admin"
                          ? checked
                            ? revokeServerAdmin(assignRolesUser.user_id)
                            : grantServerAdmin(assignRolesUser.user_id)
                          : checked
                            ? revokeServerRole(assignRolesUser.user_id, role)
                            : grantServerRole(assignRolesUser.user_id, role)
                      }
                    />
                    {roleLabel}
                  </label>
                  <FieldHelp
                    label={roleLabel}
                    help={role === "server_admin" ? strings.system.serverAdminRoleHelp : strings.system.serverRoleCopy[role].help}
                  />
                </div>
              );
            })}
          </div>
        </Modal>
      )}
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
type ServerManagementGroupKey = "accessReview" | "signup" | "branding" | "details" | "reportFonts" | "files" | "policies" | "personalDataExport" | "email" | "messages" | "modules";

const SERVER_MANAGEMENT_GROUP_KEYS: ServerManagementGroupKey[] = ["accessReview", "signup", "branding", "details", "reportFonts", "files", "policies", "personalDataExport", "email", "messages", "modules"];

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
  const access = useServerAccess();

  // "Data policy" is now the published document; the export rule this group held was renamed, so an older address
  // or bookmark lands on the renamed group.
  if (groupParam === "dataPolicy") return <Navigate to="/server/management/personalDataExport" replace />;

  const requestedGroup: ServerManagementGroupKey = SERVER_MANAGEMENT_GROUP_KEYS.includes(
    groupParam as ServerManagementGroupKey
  )
    ? (groupParam as ServerManagementGroupKey)
    : "accessReview";

  // Flat list ordered by relatedness: people and access, appearance, data handling, communication, then modules.
  const allGroups: ResourceMenuGroupDef<ServerManagementGroupKey>[] = [
    { key: "accessReview", label: strings.system.users, href: "/server/management/accessReview" },
    { key: "signup", label: strings.signupSettings.title, href: "/server/management/signup" },
    { key: "branding", label: strings.serverSettings.title, href: "/server/management/branding" },
    { key: "details", label: strings.serverSettings.detailsTitle, href: "/server/management/details" },
    { key: "reportFonts", label: strings.reportFonts.title, href: "/server/management/reportFonts" },
    { key: "files", label: strings.fileUploads.title, href: "/server/management/files" },
    { key: "policies", label: strings.policies.heading, href: "/server/management/policies" },
    { key: "personalDataExport", label: strings.personalDataPolicy.groupTitle, href: "/server/management/personalDataExport" },
    { key: "email", label: strings.system.emailTab, href: "/server/management/email" },
    { key: "messages", label: strings.announcements.heading, href: "/server/management/messages" },
    { key: "modules", label: strings.serverModules.title, href: "/server/management/modules" },
  ];
  // Only the sections this person may use, from the server's own answer: every group needs the server
  // administrator except Modules, which a Module administrator or Platform subscription manager also uses.
  const groups = allGroups.filter((g) =>
    access?.can_administer_server ? true : g.key === "modules" && !!access?.can_manage_entitlements
  );
  if (access === null) return <Spinner />;
  if (groups.length === 0) {
    return (
      <div className="card stack" role="alert">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.nav.serverManagement}</h2>
        <p>{strings.system.accessDenied}</p>
        <Link to="/" className="btn" style={{ alignSelf: "flex-start" }}>{strings.system.accessDeniedHome}</Link>
      </div>
    );
  }

  // A group the person may not use falls back to the first one they may (the server refuses its data anyway); the
  // address is replaced so it names the group shown.
  const activeGroup = groups.some((g) => g.key === requestedGroup) ? requestedGroup : groups[0].key;
  if (groupParam !== undefined && groupParam !== activeGroup) {
    return <Navigate to={`/server/management/${activeGroup}`} replace />;
  }

  return (
    <div className="stack">
      <ResourceMenu
        title={strings.nav.serverManagement}
        ariaLabel={strings.system.sectionsNav}
        groups={groups}
        active={activeGroup}
      >
        {activeGroup === "accessReview" && <AccessReviewTab />}
        {activeGroup === "signup" && <SignupModeTab />}
        {activeGroup === "branding" && <PlatformBrandingTab />}
        {activeGroup === "details" && <ServerDetailsTab />}
        {activeGroup === "reportFonts" && <ServerReportFontsTab />}
        {activeGroup === "files" && <FileUploadsTab />}
        {activeGroup === "policies" && (
          <CollapsibleSection sectionKey="serverManagement.policies" title={strings.policies.heading} collapsible={false}>
            <PoliciesPanel scope={{ kind: "server" }} />
          </CollapsibleSection>
        )}
        {activeGroup === "personalDataExport" && (
          <CollapsibleSection
            sectionKey="serverManagement.personalData" title={strings.personalDataPolicy.groupTitle}
            help={strings.personalDataPolicy.serverHint} collapsible={false}
          >
            <PersonalDataPolicyPanel scope={{ kind: "server" }} />
          </CollapsibleSection>
        )}
        {activeGroup === "email" && <TestEmailTab />}
        {activeGroup === "messages" && (
          <CollapsibleSection sectionKey="serverManagement.messages" title={strings.announcements.heading} collapsible={false}>
            <AnnouncementsPanel scope={{ kind: "server" }} />
          </CollapsibleSection>
        )}
        {activeGroup === "modules" && <ServerModulesTab />}
      </ResourceMenu>
    </div>
  );
}
