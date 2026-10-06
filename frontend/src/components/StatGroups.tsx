/**
 * Module: components/StatGroups
 *
 * The standard way to show many figures at once: a responsive grid of small
 * cards, one per group (typically one per source: a report, an entity, a
 * module), each with a heading and measure-name / value rows. Born in the
 * Context & Strategy summary report, where 25 figures from nine reports could
 * not be shown as a flat row of tiles.
 *
 * Anatomy of a card: the group title; a "Needs attention · n" badge (or "No
 * gaps") when any of its figures is a `gap`; then one row per figure, with the
 * measure name on the left and the value right-aligned. A `gap` figure that is
 * non-zero shows its value in a warning pill with screen-reader text ("needs
 * attention"); a zero gap is muted; plain figures stay as ordinary text.
 *
 * Use it instead of `StatBar` when there are more than 8 figures, labels run
 * past about 28 characters, or the figures come from several sources and
 * deserve a heading. Use `MetricTile` instead when each figure must link to a
 * filtered list. Columns are `repeat(auto-fill, minmax(min(100%, 17rem), 1fr))`
 * with no media queries, so it also works in a narrow pane; cards in a grid
 * row stretch to equal height, and labels wrap rather than truncate. See
 * docs/ux-style-guide.md ("Stat blocks") and `testing/statBlockGeometry.ts`.
 */
import { needsAttention } from "../utils/needsAttention";
import type { StatBarItem } from "./StatBar";

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
                <span className={`badge badge--${attention > 0 ? "warning" : "muted"}`}>
                  {attention > 0 ? `Needs attention · ${attention}` : "No gaps"}
                </span>
              )}
            </div>
            <dl className="stat-group-rows">
              {group.items.map((item, index) => (
                <div key={`${index}-${item.label}`} className="stat-group-row" data-stat-entry>
                  <dt>{item.label}</dt>
                  <dd className={item.gap && !needsAttention(item) ? "text-muted" : undefined}>
                    {needsAttention(item) ? (
                      <span className="badge badge--warning">
                        {item.value}
                        <span className="sr-only"> needs attention</span>
                      </span>
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
