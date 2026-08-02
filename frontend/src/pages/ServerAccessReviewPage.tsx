import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { SystemUser } from "../api/types";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Server-admin access review (C-A-13): enabled users who belong to no
 * organisation and therefore have no project access either. */
export function ServerAccessReviewPage() {
  const [users, setUsers] = useState<SystemUser[] | null>(null);

  useEffect(() => {
    api.get<SystemUser[]>("/api/v1/system/users?no_org_membership=true").then(setUsers);
  }, []);

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
    </div>
  );
}
