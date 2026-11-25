import { useMutation } from "../hooks/useMutation";
import { Bell } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { Notification } from "../api/types";
import { notificationOpenPath } from "../modules/notificationTargets";
import { t } from "../i18n/strings";
import { Tooltip } from "./Tooltip";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useLoadOnChange } from "../hooks/useLoadOnChange";

const strings = t();

/** Notification centre (C-N-02): a bell icon with unread count and a dropdown list. */
export function NotificationBell() {
  const run = useMutation();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  async function reload() {
    const list = await api.get<Notification[]>("/api/v1/notifications");
    setNotifications(list);
  }

  useLoadOnChange(reload, [], { intervalMs: 30_000 });

  // The dropdown renders in the header, outside the routed content, so nothing else closes it on navigation.
  useResetOnChange([location.pathname], () => setOpen(false));

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  async function markRead(id: string) {
    if (!(await run(() => api.post(`/api/v1/notifications/${id}/read`), { failure: "Could not mark read." }))) return;
    reload();
  }

  function openNotification(n: Notification) {
    if (!n.read_at) markRead(n.id);
    setOpen(false);
    navigate(notificationOpenPath(n));
  }

  async function markAllRead() {
    if (!(await run(() => api.post("/api/v1/notifications/read-all"), { failure: "Could not mark all read." }))) return;
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
          <Bell />
          {unreadCount > 0 && (
            <span className="notification-count-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
          )}
        </button>
      </Tooltip>
      {open && (
        <div
          className="card stack notification-dropdown scroll-region"
          style={{
            position: "absolute", right: 0, top: "2.5rem", width: 320, maxHeight: 400, zIndex: 10,
            // The empty state is one header and one line; the card's normal padding and stack gap leave too much
            // bare space around it, so both are tightened for that case.
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
              onClick={() => openNotification(n)}
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
