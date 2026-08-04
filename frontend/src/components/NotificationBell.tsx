import { Bell } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Notification } from "../api/types";
import { t } from "../i18n/strings";
import { Tooltip } from "./Tooltip";

const strings = t();

/** Notification centre (C-N-02): a bell icon with unread count and a dropdown list. */
export function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);

  async function reload() {
    const list = await api.get<Notification[]>("/api/v1/notifications");
    setNotifications(list);
  }

  useEffect(() => {
    reload();
    const interval = setInterval(reload, 30_000);
    return () => clearInterval(interval);
  }, []);

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  async function markRead(id: string) {
    await api.post(`/api/v1/notifications/${id}/read`);
    reload();
  }

  async function markAllRead() {
    await api.post("/api/v1/notifications/read-all");
    reload();
  }

  return (
    <div style={{ position: "relative" }}>
      <Tooltip label={strings.notifications.title}>
        <button className="btn" onClick={() => setOpen((v) => !v)} aria-label={strings.notifications.title}>
          <Bell size={16} />
          {unreadCount > 0 && <span className="badge">{unreadCount}</span>}
        </button>
      </Tooltip>
      {open && (
        <div
          className="card stack"
          style={{ position: "absolute", right: 0, top: "2.5rem", width: 320, maxHeight: 400, overflowY: "auto", zIndex: 10 }}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{strings.notifications.title}</strong>
            <button className="btn" onClick={markAllRead}>
              {strings.notifications.markAllRead}
            </button>
          </div>
          {notifications.length === 0 && <p className="text-muted">{strings.notifications.empty}</p>}
          {notifications.map((n) => (
            <div
              key={n.id}
              className="card"
              style={{ cursor: "pointer", opacity: n.read_at ? 0.6 : 1 }}
              onClick={() => !n.read_at && markRead(n.id)}
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
    </div>
  );
}
