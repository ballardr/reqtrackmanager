/**
 * Module: components/LoginAnnouncements
 *
 * The announcements shown on the login pages. Loads the active, login-flagged messages (the platform's, plus
 * the organisation's on that organisation's branded page) without signing in, and renders them above the form.
 *
 * Responsibilities: one unauthenticated read per page view; show nothing, and never an error, when it fails or
 * returns nothing (the login form must stay usable when the messages cannot be loaded).
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AnnouncementNotice } from "../api/types";
import { AnnouncementNotices } from "./AnnouncementNotices";

/**
 * @param organizationSlug The branded login page's organisation slug; omit on the plain login page.
 */
export function LoginAnnouncements({ organizationSlug }: { organizationSlug?: string }) {
  const [notices, setNotices] = useState<AnnouncementNotice[]>([]);
  useEffect(() => {
    let cancelled = false;
    const query = organizationSlug ? `?organization_slug=${encodeURIComponent(organizationSlug)}` : "";
    api.get<AnnouncementNotice[]>(`/api/v1/announcements/login${query}`).then(
      (loaded) => { if (!cancelled) setNotices(Array.isArray(loaded) ? loaded : []); },
      () => { /* the form still works without the messages */ },
    );
    return () => { cancelled = true; };
  }, [organizationSlug]);
  return <AnnouncementNotices notices={notices} />;
}
