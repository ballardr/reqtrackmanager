/**
 * Module: components/WatchingGroupsPanel
 *
 * The groups watching one requirement or change request (users and groups on parity): everyone in a
 * watching group who can view the project is notified of the record's comments, alongside people who
 * subscribed themselves (`SubscribeButton`). Project managers and administrators add and remove groups
 * with a `PrincipalPicker` limited to organisation groups and the project's groups; everyone else sees
 * who is watching. Renders nothing for a reader when no group is watching, so an unwatched record stays
 * uncluttered.
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { api } from "../api/client";
import type { Principal, PrincipalRef } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { PrincipalBadge } from "./PrincipalBadge";
import { PrincipalPicker } from "./PrincipalPicker";

/**
 * @param recordPath API path of the record (`/api/v1/projects/{id}/requirements/{id}`); the panel appends `/watchers`.
 * @param organizationId The project's organisation, to list its groups.
 * @param projectId The record's project, to list its groups.
 * @param canManage Whether the viewer may add and remove watching groups (project manager or administrator).
 */
const strings = t();

export function WatchingGroupsPanel({
  recordPath, organizationId, projectId, canManage,
}: {
  recordPath: string;
  organizationId?: string;
  projectId: string;
  canManage: boolean;
}) {
  const { showToast } = useToast();
  const [groups, setGroups] = useState<Principal[] | null>(null);

  useEffect(() => {
    let active = true;
    api.get<Principal[]>(`${recordPath}/watchers`).then((list) => active && setGroups(list)).catch(() => active && setGroups([]));
    return () => {
      active = false;
    };
  }, [recordPath]);

  async function add(group: PrincipalRef | null) {
    if (!group) return;
    try {
      setGroups(await api.post<Principal[]>(`${recordPath}/watchers`, { group }));
      showToast(strings.watchers.added);
    } catch (err) {
      showToast(toErrorMessage(err, strings.watchers.addFailed), "error");
    }
  }

  async function remove(group: Principal) {
    try {
      setGroups(await api.delete<Principal[]>(`${recordPath}/watchers/${group.type}/${group.id}`));
      showToast(strings.watchers.removed);
    } catch (err) {
      showToast(toErrorMessage(err, strings.watchers.removeFailed), "error");
    }
  }

  if (groups === null || (!canManage && groups.length === 0)) return null;

  return (
    <div className="card stack" style={{ gap: "0.5rem" }} role="region" aria-label={strings.watchers.title}>
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.watchers.title}</h2>
      <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
        {strings.watchers.explanation}
      </p>
      {groups.length === 0 ? (
        <span className="text-muted">{strings.watchers.none}</span>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }} className="stack">
          {groups.map((group) => (
            <li key={`${group.type}:${group.id}`} className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
              <PrincipalBadge principal={group} />
              {canManage && (
                <button
                  type="button" className="btn" onClick={() => remove(group)} aria-label={`${strings.watchers.stopWatching}: ${group.label}`}
                >
                  <X />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <PrincipalPicker
          kinds={["org_group", "project_group"]} orgUsers={[]} organizationId={organizationId} projectId={projectId}
          value={null} onChange={add} ariaLabel="Add watching group" placeholder={strings.watchers.add}
        />
      )}
    </div>
  );
}
