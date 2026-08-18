import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Notification } from "../api/types";
import { notificationLink } from "../api/types";
import { FilterCheckbox, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

/**
 * Full notification history (C-N-02): searchable, lazy-loaded page beyond
 * the header bell's small unbounded dropdown — meant for catching up after
 * being away a while (e.g. an account that doesn't log in often), where
 * loading every notification ever received up front would be wasteful.
 */
export function NotificationsPage() {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<Notification[] | null>(null);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (unreadOnly) params.set("unread_only", "true");
    return params;
  }

  async function load(offset: number, append: boolean) {
    const page = await api.getPage<Notification>(`/api/v1/notifications?${listParams(offset).toString()}`);
    setNotifications((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  useEffect(() => {
    setNotifications(null);
    load(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, unreadOnly]);

  async function markRead(id: string) {
    await api.post(`/api/v1/notifications/${id}/read`);
    setNotifications((prev) => (prev ? prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)) : prev));
  }

  async function markAllRead() {
    await api.post("/api/v1/notifications/read-all");
    load(0, false);
  }

  function openNotification(n: Notification) {
    if (!n.read_at) markRead(n.id);
    const link = notificationLink(n);
    if (link) navigate(link);
  }

  const unreadCount = notifications?.filter((n) => !n.read_at).length ?? 0;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.notifications.title}</h1>
        {unreadCount > 0 && (
          <button className="btn btn-primary" onClick={markAllRead}>
            {strings.notifications.markAllRead}
          </button>
        )}
      </div>

      <div className="side-grid">
        <div className="stack">
          <input
            className="input"
            style={{ maxWidth: 320 }}
            placeholder={strings.notifications.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {!notifications && <Spinner />}
          {notifications && notifications.length === 0 && <p className="text-muted">{strings.notifications.empty}</p>}
          {notifications && notifications.length > 0 && (
            <div className="stack">
              {notifications.map((n) => (
                <div
                  key={n.id}
                  className="card"
                  style={{ cursor: notificationLink(n) ? "pointer" : "default", opacity: n.read_at ? 0.7 : 1 }}
                  onClick={() => openNotification(n)}
                >
                  <div style={{ fontWeight: n.read_at ? 400 : 700 }}>{n.title}</div>
                  {n.body && <div className="text-muted" style={{ fontSize: "0.85rem" }}>{n.body}</div>}
                  <div className="text-muted" style={{ fontSize: "0.75rem" }}>
                    {new Date(n.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
          {notifications && (
            <LoadMoreButton loaded={notifications.length} total={total} onClick={() => load(notifications.length, true)} />
          )}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterCheckbox label={strings.notifications.unreadOnly} checked={unreadOnly} onChange={setUnreadOnly} />
        </FilterPanel>
      </div>
    </div>
  );
}
