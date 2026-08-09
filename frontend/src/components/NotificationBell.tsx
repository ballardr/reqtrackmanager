import { Bell } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { api } from "../api/client";
import type { Notification } from "../api/types";
import { t } from "../i18n/strings";
import { Tooltip } from "./Tooltip";

const strings = t();

/** Notification centre (C-N-02): a bell icon with unread count and a dropdown list. */
export function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const location = useLocation();

  async function reload() {
    const list = await api.get<Notification[]>("/api/v1/notifications");
    setNotifications(list);
  }

  useEffect(() => {
    reload();
    const interval = setInterval(reload, 30_000);
    return () => clearInterval(interval);
  }, []);

  // The dropdown previously stayed open across navigation (it's rendered
  // in the header, outside the routed content, so nothing else was ever
  // telling it to close) — closing it on every route change matches how a
  // popover is expected to behave everywhere else in the app.
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

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
        <button
          className="btn"
          style={{ position: "relative" }}
          onClick={() => setOpen((v) => !v)}
          title={strings.notifications.title}
          aria-label={strings.notifications.title}
        >
          <Bell size={16} />
          {unreadCount > 0 && (
            <span className="notification-count-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
          )}
        </button>
      </Tooltip>
      {open && (
        <div
          className="card stack"
          style={{
            position: "absolute", right: 0, top: "2.5rem", width: 320, maxHeight: 400, overflowY: "auto", zIndex: 10,
            // The empty state is just a header + one line of text — the
            // card's normal 1rem padding plus the stack gap around it
            // read as a lot of bare space for that little content, so
            // both are tightened specifically for that case.
            padding: notifications.length === 0 ? "0.6rem 0.75rem" : undefined,
            gap: notifications.length === 0 ? "0.4rem" : undefined,
          }}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{strings.notifications.title}</strong>
            {unreadCount > 0 && (
              <button className="btn" onClick={markAllRead}>
                {strings.notifications.markAllRead}
              </button>
            )}
          </div>
          {notifications.length === 0 && (
            <p className="text-muted" style={{ margin: 0 }}>{strings.notifications.empty}</p>
          )}
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
          <Link to="/notifications" className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setOpen(false)}>
            {strings.notifications.viewAll}
          </Link>
        </div>
      )}
    </div>
  );
}
