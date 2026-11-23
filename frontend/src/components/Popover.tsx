import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

import { useDialogA11y } from "./dialogA11y";
import { DialogSlotContext } from "./dialogSlots";

const VIEWPORT_MARGIN_PX = 8;
const VERTICAL_GAP_PX = 6.4; // 0.4rem
const HORIZONTAL_GAP_PX = 6.4; // 0.4rem
const MATCH_ANCHOR_MIN_WIDTH_PX = 280;
// A `matchAnchor` panel opens below its field whenever the room there is this much (or all of its height): scrolling
// inside a usable panel is better than flipping above and covering the fields that sit over the anchor.
const MATCH_ANCHOR_USABLE_ROOM_PX = 240;
const CARET_INSET_PX = 14;

/**
 * A small anchored panel for a one- or two-field create flow, the other half of style guide Principle 3 beside
 * `SidePanel` (`docs/ux-style-guide.md`, "Pattern: create panels, popovers, and one door for bulk"). It has no
 * header chrome (callers supply the whole body, typically ending in a Cancel/submit row that calls `onClose`) and no
 * backdrop, so nav and page content stay interactive around it. Callers hold `onClose` as "set open to false" and
 * pass a stable `anchorRef`.
 *
 * Positioning: portalled to `document.body` and measured with `getBoundingClientRect` (as `Tooltip`) so a scrollable
 * ancestor cannot clip it, flipped above the anchor when there is no room below. The position is applied directly to
 * the DOM node in the layout effect, not through React state: an extra render before the focus-management effect
 * races it and leaves focus on the page. It is re-measured when the window or an ancestor scrolls or resizes and
 * when the content changes size (scrolling its own content is ignored); content that does not fit the roomier side
 * is capped to the room and scrolls inside.
 *
 * It is click-triggered and interactive: focus moves in on open and is trapped (`dialogA11y.ts`, shared with
 * `Modal`/`SidePanel`), and it closes on Escape or a press outside itself and its anchor. A dialog opened from the
 * popover's own content (a confirmation) is a portal after it, so a press there is not "outside". A popover clears
 * any enclosing dialog's header slots, so a `FormActions` inside it keeps its buttons in the popover.
 *
 * - `fit` sizes the panel to its content instead of the fixed 280px (up to the viewport width less a margin,
 *   `.popover-bubble`'s `max-width`), for a menu whose longest label would clip.
 * - `placement="side"` opens to the right of the anchor with top edges level, for a small (+) button whose panel
 *   should not cover its field; it opens below when the width does not fit.
 * - `menu` gives the look of an action menu (`ActionMenuList`): tighter padding, soft shadow and a caret pointing at
 *   the anchor (hidden while the panel is capped and scrolling).
 * - `matchAnchor` opens like a native select list: left edge on the anchor's and at least as wide (never under
 *   280px), for an anchor that is a form control. Content takes the width given and must set no minimum of its own,
 *   or it runs out of the bubble. The panel stays below the field, scrolling inside, while at least 240px of room
 *   is there. `maxWidth` (pixels) caps the width for a very wide field such as one spanning a dialog.
 * - `flush` removes the padding and hides overflow: the content is a fixed header above one `ScrollRegion` that
 *   meets the panel's border and corners and shrinks and scrolls when room is short. Without `flush` a capped panel
 *   scrolls as a whole, as a `ScrollRegion`.
 */
export function Popover({
  anchorRef,
  onClose,
  title,
  fit = false,
  matchAnchor = false,
  maxWidth,
  placement = "below",
  menu = false,
  flush = false,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  title: string;
  fit?: boolean;
  matchAnchor?: boolean;
  maxWidth?: number;
  placement?: "below" | "side";
  menu?: boolean;
  flush?: boolean;
  children: ReactNode;
}) {
  const bubbleRef = useRef<HTMLDivElement>(null);
  useDialogA11y(bubbleRef, onClose);

  useLayoutEffect(() => {
    function measure() {
      const anchor = anchorRef.current;
      const bubble = bubbleRef.current;
      if (!anchor || !bubble) return;
      // Measure the content's natural height, not a height capped by an earlier pass. Clearing the cap
      // clamps the scroll offset to 0, so it is put back below once the cap is applied again.
      const scrolled = bubble.scrollTop;
      bubble.style.maxHeight = "";
      bubble.classList.remove("scroll-region");
      const anchorRect = anchor.getBoundingClientRect();
      if (matchAnchor) bubble.style.width = `${Math.max(MATCH_ANCHOR_MIN_WIDTH_PX, Math.min(anchorRect.width, maxWidth ?? Infinity))}px`;
      const bubbleRect = bubble.getBoundingClientRect();

      let left = matchAnchor ? anchorRect.left : anchorRect.right - bubbleRect.width;
      left = Math.max(VIEWPORT_MARGIN_PX, Math.min(left, window.innerWidth - bubbleRect.width - VIEWPORT_MARGIN_PX));

      // `side`: to the right of the anchor, top edges level, when the whole width fits there; otherwise it
      // falls back to opening below like any other popover.
      const sideRoom = window.innerWidth - anchorRect.right - HORIZONTAL_GAP_PX - VIEWPORT_MARGIN_PX;
      const beside = placement === "side" && bubbleRect.width <= sideRoom;

      // Open on the side with room for the whole bubble, else on the roomier side, capped to that room
      // and scrolling inside, so every control in it can be reached however low the anchor sits.
      const spaceBelow = window.innerHeight - anchorRect.bottom - VERTICAL_GAP_PX - VIEWPORT_MARGIN_PX;
      const spaceAbove = anchorRect.top - VERTICAL_GAP_PX - VIEWPORT_MARGIN_PX;
      const usableBelow = matchAnchor && spaceBelow >= Math.min(bubbleRect.height, MATCH_ANCHOR_USABLE_ROOM_PX);
      const below = bubbleRect.height <= spaceBelow || spaceBelow >= spaceAbove || usableBelow;
      const room = Math.max(0, beside ? window.innerHeight - 2 * VIEWPORT_MARGIN_PX : below ? spaceBelow : spaceAbove);
      const height = Math.min(bubbleRect.height, room);
      if (bubbleRect.height > room) {
        bubble.style.maxHeight = `${room}px`;
        if (!flush) {
          bubble.classList.add("scroll-region");
          bubble.scrollTop = scrolled;
        }
      }
      let top: number;
      if (beside) {
        left = anchorRect.right + HORIZONTAL_GAP_PX;
        top = Math.max(VIEWPORT_MARGIN_PX, Math.min(anchorRect.top, window.innerHeight - VIEWPORT_MARGIN_PX - height));
      } else {
        top = below ? anchorRect.bottom + VERTICAL_GAP_PX : anchorRect.top - height - VERTICAL_GAP_PX;
      }

      bubble.style.top = `${top}px`;
      bubble.style.left = `${left}px`;
      if (menu) {
        // The caret sits under the middle of the anchor, kept clear of the panel's rounded corners.
        const caretX = Math.max(CARET_INSET_PX, Math.min(anchorRect.left + anchorRect.width / 2 - left, bubbleRect.width - CARET_INSET_PX));
        bubble.style.setProperty("--popover-caret-x", `${caretX}px`);
        bubble.dataset.side = beside ? "end" : below ? "below" : "above";
      }
      bubble.style.visibility = "visible";
    }
    measure();
    // The bubble is `position: fixed`, so it must follow its anchor when any ancestor scrolls (the page
    // scrolls inside a container, not the window) and when its own content changes size.
    const observer = new ResizeObserver(measure);
    if (bubbleRef.current) observer.observe(bubbleRef.current);
    window.addEventListener("resize", measure);
    // Scrolling the popover's own content (wheel, or focus moving to an entry below the fold) must not
    // re-measure: the anchor has not moved, and re-measuring would undo the scroll.
    const onScroll = (e: Event) => {
      if (e.target instanceof Node && bubbleRef.current?.contains(e.target)) return;
      measure();
    };
    window.addEventListener("scroll", onScroll, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [anchorRef, matchAnchor, maxWidth, placement, menu, flush]);

  useEffect(() => {
    // Capture-phase `pointerdown`: React Flow's pane and nodes (d3-zoom, d3-drag) stop `mousedown` before it bubbles
    // to the document, so a bubble-phase listener never sees a click on a diagram. A document capture listener runs
    // before them, and `pointerdown` is not suppressed with the compatibility mouse events.
    function onPointerDown(e: PointerEvent) {
      const target = e.target as Node;
      if (bubbleRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      // A dialog, panel or popover opened from this one's content (a confirmation) is a portal that follows this
      // one among the body's children, so a press in it, including on its backdrop, is not "outside".
      let top: Node | null = target;
      while (top && top.parentNode !== document.body) top = top.parentNode;
      if (top && bubbleRef.current && bubbleRef.current.compareDocumentPosition(top) & Node.DOCUMENT_POSITION_FOLLOWING) return;
      onClose();
      // The press then moves focus to whatever it landed on (the page body when that is not focusable), after the
      // popover's own unmount has returned it to the anchor; put it back on the anchor unless it landed on a control.
      window.setTimeout(() => {
        if (document.activeElement === document.body) anchorRef.current?.focus();
      }, 0);
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [anchorRef, onClose]);

  return createPortal(
    <div
      ref={bubbleRef}
      className={`card stack popover-bubble${menu ? " popover-menu" : ""}${flush ? " popover-flush" : ""}`}
      role="dialog"
      aria-label={title}
      tabIndex={-1}
      style={{
        position: "fixed",
        // The same layer as Modal and SidePanel, so whichever opened last is on top (DOM order): a popover opened
        // inside a dialog sits over it, and a confirm dialog opened from a popover sits over the popover.
        zIndex: 1100,
        width: matchAnchor ? undefined : fit ? "max-content" : 280,
        visibility: "hidden",
      }}
    >
      <DialogSlotContext.Provider value={null}>{children}</DialogSlotContext.Provider>
    </div>,
    document.body
  );
}
