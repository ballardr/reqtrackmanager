import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { BulkRevokeResult, SystemUser } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

type ReviewView = "orphaned" | "server_admins" | "all";

/** Server-admin access review (C-A-13): by default, enabled users who
 * belong to no organisation and therefore have no project access either
 * (server admins excluded — see `orphanedUsersHint`); a "Show" filter
 * repurposes the same list to review the server-admin roster, or every
 * user in the deployment (needed to find someone to grant server admin to
 * in the first place). Also hosts the platform-wide Personal Access Token
 * incident-response reset. */
export function ServerAccessReviewPage() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);
  const [view, setView] = useState<ReviewView>("orphaned");
  const [includeDeactivated, setIncludeDeactivated] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [patResult, setPatResult] = useState<string | null>(null);

  async function reload() {
    const params = new URLSearchParams();
    if (view === "orphaned") params.set("no_org_membership", "true");
    if (view === "server_admins") params.set("is_server_admin", "true");
    if (!includeDeactivated) params.set("is_active", "true");
    const result = await api.get<SystemUser[]>(`/api/v1/system/users?${params.toString()}`);
    setUsers(result);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, includeDeactivated]);

  async function runAction(action: () => Promise<void>) {
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function deactivate(userId: string) {
    if (!window.confirm(strings.system.deactivateConfirm)) return;
    runAction(() => api.post(`/api/v1/system/users/${userId}/deactivate`));
  }

  function reactivate(userId: string) {
    runAction(() => api.post(`/api/v1/system/users/${userId}/reactivate`));
  }

  function grantServerAdmin(userId: string) {
    if (!window.confirm(strings.system.grantServerAdminConfirm)) return;
    runAction(() => api.put(`/api/v1/system/users/${userId}/server-admin`, { is_server_admin: true }));
  }

  function revokeServerAdmin(userId: string) {
    if (!window.confirm(strings.system.revokeServerAdminConfirm)) return;
    runAction(() => api.put(`/api/v1/system/users/${userId}/server-admin`, { is_server_admin: false }));
  }

  async function revokeAllPatsPlatformWide() {
    if (!window.confirm(strings.system.patRevokeAllConfirm)) return;
    const result = await api.post<BulkRevokeResult>("/api/v1/system/pats/revoke-all");
    setPatResult(strings.system.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
  }

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.system.orphanedUsers}</h1>
      <p className="text-muted">{strings.system.orphanedUsersHint}</p>

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
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>{strings.system.email}</th>
                <th>{strings.system.name}</th>
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
                  <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : strings.system.never}</td>
                  <td>{new Date(u.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
                      {!u.is_active && <span className="text-muted">{strings.system.deactivated}</span>}
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

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.system.patRevokeAll}</h2>
        <p className="text-muted">{strings.system.patRevokeAllHint}</p>
        <button className="btn btn-danger" onClick={revokeAllPatsPlatformWide} style={{ alignSelf: "flex-start" }}>
          {strings.system.patRevokeAll}
        </button>
        {patResult && <div style={{ color: "var(--color-accent)" }}>{patResult}</div>}
      </div>
    </div>
  );
}
