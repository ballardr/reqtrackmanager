/**
 * Module: components/AnnouncementNotices
 *
 * The list of active announcements as a reader sees it: on the login pages (no sign-in yet) and as the banner
 * above the signed-in page. One component for both so the two cannot drift.
 *
 * Responsibilities: show each notice's title and message as plain text (never HTML, markup or links: the login
 * page is the most exposed place to put text, and an organisation administrator writes some of it), mark its
 * severity by colour, icon and text, and optionally offer Dismiss (never for a message that is not dismissible). A critical notice is announced to assistive technology as an alert.
 */
import { X } from "lucide-react";

import type { AnnouncementNotice } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { AnnouncementSeverityMark } from "./AnnouncementSeverityMark";
import { Badge } from "./Badge";

/**
 * @param notices The active notices, most severe first.
 * @param onDismiss Called with a notice's id when its Dismiss control is used; omit where a notice cannot be dismissed (the login pages). A notice that is not dismissible never shows the control.
 * @param showScope Labels each notice Platform or Organisation, for a list that mixes the two.
 * @param bar Draws each notice as a full-width strip with a tinted background (the banner above the top bar) instead of a card.
 */
export function AnnouncementNotices({
  notices, onDismiss, showScope, bar,
}: {
  notices: AnnouncementNotice[];
  onDismiss?: (id: string) => void;
  showScope?: boolean;
  bar?: boolean;
}) {
  const strings = useStrings().announcements;
  if (notices.length === 0) return null;
  return (
    <section className="stack" aria-label={strings.region} style={{ gap: bar ? 0 : "var(--space-2)" }}>
      {notices.map((notice) => (
        <div
          key={notice.id} className={`announcement announcement--${notice.severity}${bar ? " announcement--bar" : ""}`}
          role={notice.severity === "critical" ? "alert" : "status"} data-announcement-id={notice.id}
        >
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
            <div className="stack announcement__text" style={{ gap: "var(--space-1)" }}>
              <div className="row" style={{ gap: "var(--space-2)" }}>
                <AnnouncementSeverityMark severity={notice.severity} />
                {showScope && <Badge>{notice.scope === "server" ? strings.scopeServer : strings.scopeOrganisation}</Badge>}
                <strong>{notice.title}</strong>
              </div>
              {notice.body && <p className="announcement__body">{notice.body}</p>}
            </div>
            {onDismiss && notice.dismissible && (
              <button
                type="button" className="btn btn-sm" aria-label={strings.dismissAria(notice.title)} title={strings.dismiss}
                onClick={() => onDismiss(notice.id)}
              >
                <X />
              </button>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
