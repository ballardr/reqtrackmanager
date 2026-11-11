/**
 * Module: components/DeliveryTimeline
 *
 * The timeline view of the delivery plan: one horizontal bar per stage or component track on a shared date axis, with a
 * marker for today. The table beside it (`ComponentTracksList`, `StagePlanTable`) is the accessible alternative and says
 * the same things in words.
 *
 * Responsibilities:
 * - Position each row's expected range as an outlined bar, fill it by progress (workflow phases completed), and draw the
 *   recorded actual range as a thin solid line beneath it; a row with no dates shows "No dates set" and no bar.
 * - Draw month ticks and today across the rows from `utils/deliveryPlan.timelineBounds`.
 * - Name each row for assistive technology in one sentence (phase, progress, dates, overdue); the bars are decorative.
 *
 * Design decisions: plain CSS positioning, no chart library; an overdue row carries a text badge and an icon as well as
 * the colour, so colour is never the only cue. Nothing is inferred for a row without dates.
 */
import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { dayNumber, formatDay, timelineBounds, type DeliveryRow } from "../utils/deliveryPlan";
import { localToday } from "../utils/localDate";
import { Badge } from "./Badge";

/** A row with the names the timeline shows for it. */
export interface TimelineItem {
  row: DeliveryRow;
  /** The first line of the label (the component, or the stage for a stage row). */
  title: string;
  /** The second line (the stage of a track), muted. */
  subtitle?: string;
}

/** The first day of each month (or each few months for a long span) inside `[from, to]`, for the axis. */
function monthTicks(from: number, to: number): number[] {
  const step = Math.max(1, Math.ceil(Math.round((to - from) / 30) / 10));
  const start = new Date(from * 86_400_000);
  const ticks: number[] = [];
  let index = 0;
  for (let months = start.getUTCFullYear() * 12 + start.getUTCMonth() + 1; ; months += 1) {
    const day = Date.UTC(Math.floor(months / 12), months % 12, 1) / 86_400_000;
    if (day > to) break;
    if (index % step === 0) ticks.push(day);
    index += 1;
  }
  return ticks;
}

/**
 * @param items The rows to draw, in display order.
 * @param today The viewer's calendar day; defaults to `localToday()` (tests pass a fixed day).
 * @param actions Optional control for one row (for example a move or schedule button), shown after its label.
 */
export function DeliveryTimeline({
  items, today = localToday(), actions,
}: { items: TimelineItem[]; today?: string; actions?: (item: TimelineItem) => ReactNode }) {
  const t = useStrings().deliveryPlan;
  const bounds = timelineBounds(items.map((i) => i.row), today);
  if (items.length === 0) return null;
  if (!bounds) return <p className="text-muted">{t.timelineNoDates}</p>;
  const span = bounds.to - bounds.from;
  const at = (day: string) => `${((dayNumber(day) - bounds.from) / span) * 100}%`;
  const width = (from: string, to: string) => `${Math.max(((dayNumber(to) - dayNumber(from) + 1) / span) * 100, 0.6)}%`;
  const todayLeft = at(today);
  const ticks = monthTicks(bounds.from, bounds.to);

  return (
    <div className="delivery-timeline" role="list" aria-label={t.timelineAria}>
      <div className="delivery-timeline-row delivery-timeline-axis" aria-hidden="true">
        <div />
        <div className="delivery-timeline-track">
          {ticks.map((tick) => (
            <span key={tick} className="delivery-timeline-tick" style={{ left: `${((tick - bounds.from) / span) * 100}%` }}>
              {new Date(tick * 86_400_000).toLocaleDateString(undefined, { month: "short", year: "2-digit", timeZone: "UTC" })}
            </span>
          ))}
          <span className="delivery-timeline-today-label" style={{ left: todayLeft }}>{t.today}</span>
        </div>
      </div>
      {items.map((item) => {
        const { row } = item;
        const hasExpected = row.expectedFrom !== null && row.expectedTo !== null;
        const hasActual = row.actualFrom !== null;
        const actualEnd = row.actualTo ?? today;
        return (
          <div key={row.key} className="delivery-timeline-row" role="listitem">
            <div className="delivery-timeline-label">
              <span>
                <strong>{item.title}</strong>
                {item.subtitle && <span className="text-muted"> · {item.subtitle}</span>}
              </span>
              <span className="row" style={{ gap: "var(--space-2)" }}>
                {row.notApplicable ? <Badge>{t.notApplicable}</Badge> : <Badge tone={row.completed ? "accent" : "info"}>{row.phaseName}</Badge>}
                {row.overdue && <Badge tone="danger"><TriangleAlert aria-hidden="true" size={12} /> {t.overdue}</Badge>}
                {actions?.(item)}
              </span>
              <span className="sr-only">
                {t.rowSummary(
                  item.title, item.subtitle ?? null, row.phaseName, t.progress(row.completedPhases, row.totalPhases),
                  hasExpected ? t.expectedRange(formatDay(row.expectedFrom as string), formatDay(row.expectedTo as string)) : null, row.overdue,
                )}
              </span>
            </div>
            <div className="delivery-timeline-track" aria-hidden="true">
              <span className="delivery-timeline-today" style={{ left: todayLeft }} />
              {!row.notApplicable && hasExpected && (
                <span
                  className={`delivery-timeline-bar${row.overdue ? " delivery-timeline-bar-overdue" : ""}`}
                  style={{ left: at(row.expectedFrom as string), width: width(row.expectedFrom as string, row.expectedTo as string) }}
                >
                  <span className="delivery-timeline-fill" style={{ width: `${Math.round(row.progress * 100)}%` }} />
                </span>
              )}
              {!row.notApplicable && hasActual && (
                <span
                  className="delivery-timeline-actual"
                  style={{ left: at(row.actualFrom as string), width: width(row.actualFrom as string, actualEnd < (row.actualFrom as string) ? (row.actualFrom as string) : actualEnd) }}
                />
              )}
              {!row.notApplicable && !hasExpected && !hasActual && <span className="delivery-timeline-nodates text-muted">{t.noDates}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
