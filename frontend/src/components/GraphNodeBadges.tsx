/**
 * Module: components/GraphNodeBadges
 *
 * The small buttons a consumer puts on a canvas node's corner (`GraphNodeBadge`): a sign that the node has something
 * more elsewhere (a state machine diagram, a sub-process, a glossary term) and one click to reach it.
 *
 * Responsibilities:
 * - Draw each badge as a real button (icon, optional count) named by its label, which is also its tooltip.
 * - A badge with one target calls it at once; a badge with several opens a small list (`Popover`) of buttons.
 * - Keep the canvas's own behaviour out of the way: a press, double-click or key on a badge never drags, selects or
 *   opens the node beneath it.
 *
 * Design decisions:
 * - A badge sits inside the node's frame, at its top left, so it never changes the node's size, never covers an attach
 *   point (the corner handles) and never meets a comment pin (top right corner). It is drawn beside the node's clipped
 *   body, not inside it, so a resize cannot cut it.
 * - It is a sibling of the box in the DOM, so Tab reaches it right after the box.
 * - Generic: nothing here knows what a badge means; the consumer supplies the icon, names and callbacks.
 *
 * Dependencies: `Popover`, `Tooltip`. It does not import `@xyflow/react`.
 */
import { useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";
import type { GraphNodeBadge } from "./GraphCanvas";

/** Stops a pointer or key event reaching the node (drag, select, open) and the pane (pan). */
function keep<E extends { stopPropagation: () => void }>(event: E) {
  event.stopPropagation();
}

/** One badge: a button, and the list it opens when it has several targets. */
function BadgeButton({ badge }: { badge: GraphNodeBadge }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const items = badge.items ?? [];

  const activate = (event: MouseEvent) => {
    event.stopPropagation();
    if (items.length > 1) setOpen((current) => !current);
    else if (items.length === 1) items[0].onSelect();
    else badge.onActivate?.();
  };
  const onKeyDown = (event: KeyboardEvent) => {
    // The node under the badge selects on Enter and Space and moves on the arrow keys; the badge handles its own keys.
    event.stopPropagation();
  };

  return (
    <>
      <Tooltip label={badge.label}>
        <button
          ref={anchor}
          type="button"
          className="graph-node-badge nodrag nopan"
          aria-label={badge.label}
          aria-haspopup={items.length > 1 ? "true" : undefined}
          aria-expanded={items.length > 1 ? open : undefined}
          onClick={activate}
          onDoubleClick={keep}
          onMouseDown={keep}
          onPointerDown={keep}
          onKeyDown={onKeyDown}
        >
          <span className="graph-node-badge-icon" aria-hidden="true">{badge.icon}</span>
          {badge.count !== undefined && badge.count > 0 && <span className="graph-node-badge-count">{badge.count}</span>}
        </button>
      </Tooltip>
      {open && items.length > 1 && (
        <Popover anchorRef={anchor} onClose={() => setOpen(false)} title={badge.label} fit>
          <ul className="graph-node-badge-list" aria-label={badge.label}>
            {items.map((item) => (
              <li key={item.id}>
                <button type="button" className="btn btn-sm" onClick={() => { setOpen(false); item.onSelect(); }}>{item.label}</button>
              </li>
            ))}
          </ul>
        </Popover>
      )}
    </>
  );
}

/**
 * @param badges The node's badges, left to right; nothing is drawn for none.
 */
export function GraphNodeBadges({ badges }: { badges: readonly GraphNodeBadge[] }) {
  if (badges.length === 0) return null;
  return (
    <div className="graph-node-badges nodrag nopan">
      {badges.map((badge) => <BadgeButton key={badge.id} badge={badge} />)}
    </div>
  );
}
