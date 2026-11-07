/**
 * Module: components/AnnouncementsPanel
 *
 * Administration of announcements for one scope, shared by Server Management (the platform's messages) and
 * Organisation Admin (that organisation's). Lists each message with its severity, window, login-page flag and
 * status; an administrator can create, edit and delete a message and send it once as a notification.
 *
 * The server enforces scope and the text rules; its message is shown in the dialog. The send is a recorded,
 * one-time action, so it asks first and is replaced by a record of who it reached once done.
 */
import { Bell, Pencil, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { Announcement, AnnouncementWrite } from "../api/types";
import {
  ANNOUNCEMENT_SEVERITY_LABEL, ANNOUNCEMENT_SEVERITY_TONE, ANNOUNCEMENT_STATUS_LABEL, ANNOUNCEMENT_STATUS_TONE,
} from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { AnnouncementEditor } from "./AnnouncementEditor";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldHelp } from "./FieldHelp";

/** Where the panel reads and writes: the platform's messages, or one organisation's. */
export type AnnouncementScope = { kind: "server" } | { kind: "organisation"; organizationId: string };

function basePath(scope: AnnouncementScope): string {
  return scope.kind === "server" ? "/api/v1/system/announcements" : `/api/v1/orgs/${scope.organizationId}/announcements`;
}

/**
 * @param scope The scope to administer.
 */
export function AnnouncementsPanel({ scope }: { scope: AnnouncementScope }) {
  const strings = useStrings();
  const text = strings.announcements;
  const run = useMutation();
  const { showToast } = useToast();
  const [items, setItems] = useState<Announcement[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Announcement | "new" | null>(null);
  const [removing, setRemoving] = useState<Announcement | null>(null);
  const [sending, setSending] = useState<Announcement | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const path = basePath(scope);

  const reload = useCallback(async () => {
    try {
      setItems((await api.get<{ items: Announcement[] }>(path)).items);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, text.loadFailed));
    }
  }, [path, text.loadFailed]);

  useLoadOnChange(reload, [path]);

  async function save(values: AnnouncementWrite) {
    setSaveError(null);
    const existing = editing !== "new" ? editing : null;
    const verb = existing ? "save" : "create";
    try {
      if (existing) await api.put(`${path}/${existing.id}`, values);
      else await api.post(path, values);
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.mutation.failure(verb, text.noun)));
      return;
    }
    showToast(strings.mutation.success(text.noun, strings.mutation.past[verb]));
    setEditing(null);
    await reload();
  }

  async function remove(item: Announcement) {
    setRemoving(null);
    if (await run(() => api.delete(`${path}/${item.id}`), "delete", text.noun)) await reload();
  }

  async function send(item: Announcement) {
    setSending(null);
    const messages = { success: text.sentToast, failure: strings.mutation.failure("send", text.notificationNoun) };
    if (await run(() => api.post(`${path}/${item.id}/notify`, {}), messages)) await reload();
  }

  const windowText = (item: Announcement) => {
    const from = item.starts_at ? new Date(item.starts_at).toLocaleString() : null;
    const until = item.ends_at ? new Date(item.ends_at).toLocaleString() : null;
    if (from && until) return text.range(from, until);
    if (from) return text.from(from);
    if (until) return text.until(until);
    return text.always;
  };

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!items) return null;
  const audience = scope.kind === "server" ? text.audienceServer : text.audienceOrganisation;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-primary" onClick={() => { setSaveError(null); setEditing("new"); }}>{text.newMessage}</button>
      </div>
      {items.length === 0 ? (
        <div className="text-muted">{text.noMessages}</div>
      ) : (
        <table className="table" aria-label={text.heading}>
          <thead>
            <tr>
              <th>{text.title}</th>
              <th>{text.severity}</th>
              <th>{text.window}</th>
              <th>{text.status}</th>
              <th>
                <span className="field-caption">
                  <span>{text.sendNotification}</span>
                  <FieldHelp label={text.sendNotification} help={strings.help.announcementNotify} />
                </span>
              </th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} data-announcement-id={item.id}>
                <td>
                  <strong>{item.title}</strong>
                  {item.body && <div className="text-muted" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.body}</div>}
                </td>
                <td><Badge tone={ANNOUNCEMENT_SEVERITY_TONE[item.severity]}>{ANNOUNCEMENT_SEVERITY_LABEL[item.severity]}</Badge></td>
                <td>
                  <div>{windowText(item)}</div>
                  {item.show_on_login && <Badge>{text.onLoginBadge}</Badge>}
                </td>
                <td><Badge tone={ANNOUNCEMENT_STATUS_TONE[item.status]}>{ANNOUNCEMENT_STATUS_LABEL[item.status]}</Badge></td>
                <td>
                  {item.notified_at ? (
                    <span className="text-muted">{text.sentTo(item.notified_count ?? 0, new Date(item.notified_at).toLocaleString())}</span>
                  ) : (
                    <button
                      className="btn" disabled={item.status === "ended"} aria-label={text.sendAria(item.title)}
                      onClick={() => setSending(item)}
                    >
                      <Bell /> {text.sendNotification}
                    </button>
                  )}
                </td>
                <td>
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button
                      className="btn" aria-label={text.editAria(item.title)} title={text.editAria(item.title)}
                      onClick={() => { setSaveError(null); setEditing(item); }}
                    >
                      <Pencil />
                    </button>
                    <button className="btn btn-danger" aria-label={text.deleteAria(item.title)} title={text.deleteAria(item.title)} onClick={() => setRemoving(item)}>
                      <Trash2 />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing !== null && (
        <AnnouncementEditor
          announcement={editing === "new" ? null : editing} organisationScope={scope.kind === "organisation"}
          error={saveError} onCancel={() => setEditing(null)} onSave={save}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={text.deleteTitle(removing.title)} message={text.deleteBody} confirmLabel={strings.common.delete}
          onConfirm={() => remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
      {sending && (
        <ConfirmDialog
          title={text.sendTitle(sending.title)} message={text.sendBody(audience)} confirmLabel={text.sendConfirm}
          onConfirm={() => send(sending)} onCancel={() => setSending(null)}
        />
      )}
    </div>
  );
}
