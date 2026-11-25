/**
 * Module: components/AnnouncementBanner
 *
 * The banner above the top bar of every signed-in page: the platform's active messages plus those of the
 * organisation the person is in (the open project's, else their only organisation).
 *
 * Loads the active notices and lets a person dismiss one; the dismissal is remembered in this browser only (a
 * per-viewer convenience that never reaches the server). A non-dismissible notice has no close control and shows
 * even if dismissed earlier. A failed load shows nothing.
 *
 * Design: the banner is sticky. Pinned chrome below it reads `--announcement-height`, which this component keeps
 * equal to its measured height (0px when empty), so a wrapped notice never covers the chrome.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { AnnouncementNotice } from "../api/types";
import { AnnouncementNotices } from "./AnnouncementNotices";

const DISMISSED_KEY = "announcements.dismissed";
/** Most dismissed ids remembered, so the stored list cannot grow without bound. */
const MAX_REMEMBERED = 100;

function readDismissed(): string[] {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function rememberDismissed(ids: string[]): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(ids.slice(-MAX_REMEMBERED)));
  } catch {
    /* storage unavailable: the notice shows again next time */
  }
}

/**
 * @param organizationId The organisation whose messages join the platform's; null for the platform's only.
 */
export function AnnouncementBanner({ organizationId }: { organizationId: string | null }) {
  const [notices, setNotices] = useState<AnnouncementNotice[]>([]);
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);

  useEffect(() => {
    let cancelled = false;
    const query = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
    api.get<AnnouncementNotice[]>(`/api/v1/announcements/active${query}`).then(
      (loaded) => { if (!cancelled) setNotices(Array.isArray(loaded) ? loaded : []); },
      () => { if (!cancelled) setNotices([]); },
    );
    return () => { cancelled = true; };
  }, [organizationId]);

  const dismiss = useCallback((id: string) => {
    setDismissed((current) => {
      const next = [...current.filter((existing) => existing !== id), id];
      rememberDismissed(next);
      return next;
    });
  }, []);

  const visible = notices.filter((notice) => !notice.dismissible || !dismissed.includes(notice.id));
  const shown = visible.length > 0;
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = document.documentElement;
    const element = bar.current;
    if (!shown || !element) {
      root.style.setProperty("--announcement-height", "0px");
      return;
    }
    const measure = () => root.style.setProperty("--announcement-height", `${element.offsetHeight}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.setProperty("--announcement-height", "0px");
    };
  }, [shown]);

  if (!shown) return null;
  return (
    <div ref={bar} className="announcement-bar">
      <AnnouncementNotices notices={visible} onDismiss={dismiss} showScope bar />
    </div>
  );
}
