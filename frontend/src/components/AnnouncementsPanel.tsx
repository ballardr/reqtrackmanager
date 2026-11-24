/**
 * Module: components/AnnouncementsPanel
 *
 * Administration of announcements for one scope, shared by Server Management (platform messages) and Organisation
 * Admin (that organisation's). Lists each message with title and status always, severity and window by default, and
 * login-page flag, dismissibility and the send action on request (column chooser), in current (active and
 * scheduled) and previous (ended) views with a search over both; create, edit, duplicate, delete, and send once
 * as a notification.
 *
 * The server enforces scope and text rules and its message is shown in the dialog. The send is a recorded,
 * one-time action: it asks first and is replaced by a record of who it reached.
 */
import { Bell, Copy, Pencil, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import type { Announcement, AnnouncementWrite } from "../api/types";
import { ANNOUNCEMENT_SEVERITY_LABEL, ANNOUNCEMENT_STATUS_LABEL, ANNOUNCEMENT_STATUS_TONE } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { useOptionalColumns } from "../hooks/useOptionalColumns";
import { instantOf, sortRows } from "../utils/sortRows";
import { AnnouncementEditor } from "./AnnouncementEditor";
import { AnnouncementSeverityMark } from "./AnnouncementSeverityMark";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import type { DirectoryColumn } from "./DirectoryTable";
import { DirectoryTable } from "./DirectoryTable";
import { FieldHelp } from "./FieldHelp";
import { TextField } from "./FormFields";
import { InlineMessage } from "./InlineMessage";
import { cycleSort, type SortState } from "./sortState";
import { Tabs, tabPanelProps } from "./Tabs";
import { MarkdownView } from "./MarkdownView";

type View = "current" | "previous";

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
  const [duplicating, setDuplicating] = useState<Announcement | null>(null);
  const [view, setView] = useState<View>("current");
  const [search, setSearch] = useState("");
  const [removing, setRemoving] = useState<Announcement | null>(null);
  const [sending, setSending] = useState<Announcement | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState | null>(null);
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
    const existing = editing !== "new" && editing !== null ? editing : null;
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
    setDuplicating(null);
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

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (items ?? []).filter((item) => (item.status === "ended") === (view === "previous")
      && (needle === "" || `${item.title}\n${item.body}`.toLowerCase().includes(needle)));
  }, [items, view, search]);

  const columns: DirectoryColumn<Announcement>[] = [
    {
      key: "title", label: text.title, sortable: true,
      render: (item) => (
        <>
          <strong>{item.title}</strong>
          {item.body && <MarkdownView className="text-muted" text={item.body} />}
        </>
      ),
    },
    { key: "severity", label: text.severity, sortable: true, optional: true, render: (item) => <AnnouncementSeverityMark severity={item.severity} showLabel /> },
    { key: "window", label: text.window, sortable: true, optional: true, render: (item) => windowText(item) },
    { key: "login", label: text.loginColumn, sortable: true, optional: true, defaultHidden: true, render: (item) => (item.show_on_login ? strings.common.yes : strings.common.no) },
    { key: "dismissible", label: text.dismissibleColumn, sortable: true, optional: true, defaultHidden: true, render: (item) => (item.dismissible ? strings.common.yes : strings.common.no) },
    { key: "status", label: text.status, sortable: true, render: (item) => <Badge tone={ANNOUNCEMENT_STATUS_TONE[item.status]}>{ANNOUNCEMENT_STATUS_LABEL[item.status]}</Badge> },
    {
      key: "notify", sortable: true, optional: true, defaultHidden: true,
      label: text.sendNotification,
      headerAction: <FieldHelp label={text.sendNotification} help={strings.help.announcementNotify} />,
      render: (item) =>
        item.notified_at ? (
          <span className="text-muted">{text.sentTo(item.notified_count ?? 0, new Date(item.notified_at).toLocaleString())}</span>
        ) : (
          <button className="btn" disabled={item.status === "ended"} aria-label={text.sendAria(item.title)} onClick={() => setSending(item)}>
            <Bell /> {text.sendNotification}
          </button>
        ),
    },
    {
      key: "actions", label: "",
      render: (item) => (
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button
            className="btn" aria-label={text.duplicateAria(item.title)} title={text.duplicate}
            onClick={() => { setSaveError(null); setDuplicating(item); setEditing("new"); }}
          >
            <Copy />
          </button>
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
      ),
    },
  ];

  const chosen = useOptionalColumns("announcements", columns);

  if (loadError) return <InlineMessage>{loadError}</InlineMessage>;
  if (!items) return null;

  const audience = scope.kind === "server" ? text.audienceServer : text.audienceOrganisation;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        {chosen.chooser}
        <button className="btn btn-primary" onClick={() => { setSaveError(null); setDuplicating(null); setEditing("new"); }}>{text.newMessage}</button>
      </div>
      {items.length === 0 ? (
        <div className="text-muted">{text.noMessages}</div>
      ) : (
        <>
        <Tabs
          idPrefix="announcement-views" active={view} onChange={setView}
          tabs={[{ key: "current", label: text.current }, { key: "previous", label: text.previous }]}
        />
        <div {...tabPanelProps("announcement-views", view)} className="stack">
        <TextField helpNotNeeded label={text.searchLabel} value={search} onChange={setSearch} inputProps={{ type: "search" }} />
        {shown.length === 0 ? (
          <div className="text-muted">{search.trim() !== "" ? text.noMatches : view === "previous" ? text.noPrevious : text.noMessages}</div>
        ) : (
        <DirectoryTable
          ariaLabel={text.heading}
          columns={chosen.columns}
          rows={sortRows(shown, sort, {
            title: (item) => item.title,
            severity: (item) => ANNOUNCEMENT_SEVERITY_LABEL[item.severity],
            window: (item) => item.starts_at ?? null,
            login: (item) => (item.show_on_login ? 1 : 0),
            dismissible: (item) => (item.dismissible ? 1 : 0),
            notify: (item) => instantOf(item.notified_at),
            status: (item) => ANNOUNCEMENT_STATUS_LABEL[item.status],
          })}
          rowKey={(item) => item.id}
          sort={sort}
          onSort={(key) => setSort(cycleSort(sort, key))}
          emptyState={null}
        />
        )}
        </div>
        </>
      )}
      {editing !== null && (
        <AnnouncementEditor
          announcement={editing === "new" ? null : editing} duplicateOf={duplicating} organisationScope={scope.kind === "organisation"}
          error={saveError} onCancel={() => { setEditing(null); setDuplicating(null); }} onSave={save}
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
