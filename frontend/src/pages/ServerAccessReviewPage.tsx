import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { BulkRevokeResult, SystemUser } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Server-admin access review (C-A-13): enabled users who belong to no
 * organisation and therefore have no project access either, plus the
 * platform-wide Personal Access Token incident-response reset. */
export function ServerAccessReviewPage() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);
  const [patResult, setPatResult] = useState<string | null>(null);

  useEffect(() => {
    api.get<SystemUser[]>("/api/v1/system/users?no_org_membership=true").then(setUsers);
  }, []);

  async function revokeAllPatsPlatformWide() {
    if (!window.confirm(strings.system.patRevokeAllConfirm)) return;
    const result = await api.post<BulkRevokeResult>("/api/v1/system/pats/revoke-all");
    setPatResult(strings.system.patRevokeAllResult.replace("{n}", String(result.revoked_count)));
  }

  if (!users) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{strings.system.orphanedUsers}</h1>
      <p className="text-muted">{strings.system.orphanedUsersHint}</p>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>{strings.system.email}</th>
              <th>{strings.system.name}</th>
              <th>{strings.system.lastLogin}</th>
              <th>{strings.system.created}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id}>
                <td>{u.email}</td>
                <td>{u.display_name}</td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : strings.system.never}</td>
                <td>{new Date(u.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
