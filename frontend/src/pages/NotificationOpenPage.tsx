/**
 * Module: pages/NotificationOpenPage
 *
 * `/notifications/:notificationId`, the one address every notification link opens (bell, list, email and
 * digest). It loads the notification, marks it read and navigates to the page its type declares
 * (`resolveNotificationTarget`); when no page applies or access has ended it shows the full message.
 *
 * Design decisions: the browser resolves the target with one function for every surface, so module page
 * addresses are not copied onto the server and an email link cannot drift from the bell. Navigation
 * replaces this page in the history so Back skips the redirect; sign-in is the protected-route flow.
 */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { NotificationDetail } from "../api/types";
import { Spinner } from "../components/Spinner";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { t } from "../i18n/strings";
import { resolveNotificationTarget } from "../modules/notificationTargets";

const strings = t();

export function NotificationOpenPage() {
  const { notificationId = "" } = useParams();
  const navigate = useNavigate();
  const [notification, setNotification] = useState<NotificationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const loaded = await api.get<NotificationDetail>(`/api/v1/notifications/${notificationId}`);
      // Reading it is idempotent; a failure to record it must not stop the person reaching the page.
      if (!loaded.read_at) await api.post(`/api/v1/notifications/${notificationId}/read`).catch(() => undefined);
      const target = loaded.subject_available ? resolveNotificationTarget(loaded) : null;
      if (target) {
        navigate(target, { replace: true });
        return;
      }
      setNotification(loaded);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? strings.notifications.notFound : toErrorMessage(err, strings.notifications.loadFailed));
    }
  }
  useLoadOnChange(load, [notificationId]);

  if (error) {
    return (
      <div className="stack">
        <p role="alert">{error}</p>
        <Link to="/notifications" className="btn" style={{ alignSelf: "flex-start" }}>{strings.notifications.viewAll}</Link>
      </div>
    );
  }
  if (!notification) return <Spinner />;

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{notification.title}</h1>
      <div className="card stack">
        {!notification.subject_available && <p role="status">{strings.notifications.subjectUnavailable}</p>}
        {notification.body && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{notification.body}</p>}
        <div className="text-muted" style={{ fontSize: "0.85rem" }}>{new Date(notification.created_at).toLocaleString()}</div>
      </div>
      <Link to="/notifications" className="btn" style={{ alignSelf: "flex-start" }}>{strings.notifications.viewAll}</Link>
    </div>
  );
}
