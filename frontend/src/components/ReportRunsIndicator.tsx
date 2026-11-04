/**
 * Module: components/ReportRunsIndicator
 *
 * A clock with a count beside the notification bell in the top bar, shown while the person has background reports
 * waiting or being prepared. Its popover lists them (name, format, state, when asked) and nothing else: no download,
 * no delete and no history. A finished report is announced by a notification, which opens it (`ReportRunDialog`).
 *
 * Design decisions: it is the live count of the person's own in-progress runs, not a pinned notification, so it needs
 * no read/unread, e-mail or bell-count rules and is visible on every page. It hides at zero. Polling lives in
 * `useActiveReportRuns` (frequent while something is in progress, rare otherwise).
 *
 * Dependencies: `useActiveReportRuns`, `Popover`, `Tooltip`.
 */
import { Clock } from "lucide-react";
import { useRef, useState } from "react";

import { REPORT_RUN_STATUS_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useActiveReportRuns } from "../hooks/useActiveReportRuns";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

export function ReportRunsIndicator() {
  const strings = useStrings();
  const { runs } = useActiveReportRuns();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  if (runs.length === 0) return null;
  const label = strings.reportRuns.indicatorLabel(runs.length);

  return (
    <>
      <Tooltip label={label}>
        <button
          ref={triggerRef}
          type="button"
          className="btn"
          style={{ position: "relative" }}
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <Clock aria-hidden="true" />
          <span className="notification-count-badge" aria-hidden="true">{runs.length}</span>
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} fit title={strings.reportRuns.indicatorTitle} onClose={() => setOpen(false)}>
          <div className="stack" style={{ gap: "var(--space-2)" }}>
            <strong>{strings.reportRuns.indicatorTitle}</strong>
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {runs.map((run) => (
                <li key={run.id}>
                  <span>{run.layout_name}</span> <span className="text-muted">{run.format.toUpperCase()}</span>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {strings.reportRuns.rowStatus(REPORT_RUN_STATUS_LABEL[run.status], new Date(run.created_at).toLocaleTimeString())}
                  </div>
                </li>
              ))}
            </ul>
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>{strings.reportRuns.indicatorHint}</span>
          </div>
        </Popover>
      )}
    </>
  );
}
