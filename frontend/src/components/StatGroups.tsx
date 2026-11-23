/**
 * Module: components/StatGroups
 *
 * The standard way to show many figures at once: a responsive grid of small cards, one per group (typically one per
 * source: a report, an entity, a module), each with a heading and measure-name / value rows.
 *
 * Anatomy of a card: the group title; a "Needs attention · n" badge (or "No gaps") when any figure is a `gap`; then one
 * row per figure, measure name left and value right-aligned. A non-zero `gap` value shows in a warning pill with
 * screen-reader text ("needs attention"); a zero gap is muted; plain figures stay ordinary text. A figure with `to` or
 * `onActivate` makes its whole row interactive (see `StatFigureLabel`).
 *
 * Use it instead of `StatBar` for more than 8 figures, labels past about 28 characters, or figures from several sources;
 * use `MetricTile` when each figure must link to a filtered list. Columns are
 * `repeat(auto-fill, minmax(min(100%, 17rem), 1fr))` with no media queries, cards stretch to equal height and labels
 * wrap. See docs/ux-style-guide.md ("Stat blocks") and `testing/statBlockGeometry.ts`.
 */
import { needsAttention } from "../utils/needsAttention";
import type { StatBarItem } from "./StatBar";
import { isInteractive } from "../utils/statFigureAction";
import { StatFigureLabel } from "./StatFigureLabel";
import { Badge } from "./Badge";

export interface StatGroup {
  key: string;
  /** Card heading, e.g. the source report's title. */
  title: string;
  items: StatBarItem[];
}

/**
 * @param groups The cards to show, in order. Empty renders nothing.
 */
export function StatGroups({ groups }: { groups: StatGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div className="stat-groups" data-stat-block="grouped">
      {groups.map((group) => {
        const attention = group.items.filter(needsAttention).length;
        return (
          <section key={group.key} className="card stat-group" aria-label={group.title}>
            <div className="stat-group-head">
              <h3 className="stat-group-title">{group.title}</h3>
              {group.items.some((i) => i.gap) && (
                <Badge tone={attention > 0 ? "warning" : "muted"}>
                  {attention > 0 ? `Needs attention · ${attention}` : "No gaps"}
                </Badge>
              )}
            </div>
            <dl className="stat-group-rows">
              {group.items.map((item, index) => (
                <div key={`${index}-${item.label}`} className={`stat-group-row${isInteractive(item) ? " stat-linked" : ""}`} data-stat-entry>
                  <dt>
                    <StatFigureLabel label={item.label} value={item.value} to={item.to} onActivate={item.onActivate} hint={item.hint} />
                  </dt>
                  <dd className={item.gap && !needsAttention(item) ? "text-muted" : undefined}>
                    {needsAttention(item) ? (
                      <Badge tone="warning">
                        {item.value}
                        <span className="sr-only"> needs attention</span>
                      </Badge>
                    ) : (
                      item.value
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
    </div>
  );
}
