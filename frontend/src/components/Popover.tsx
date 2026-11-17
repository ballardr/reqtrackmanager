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
 * A small anchored panel for a one- or two-field create flow — the other
 * half of style guide Principle 3 alongside `SidePanel`, for content too
 * light to justify a full panel (e.g. "+ New group" with just a name
 * field; see `docs/ux-style-guide.md`'s "Pattern: create panels, popovers,
 * and one door for bulk"). Unlike `Modal`/`SidePanel` it has no header
 * chrome of its own — callers supply the whole body, typically ending in a
 * Cancel/submit row that calls `onClose` itself — and no backdrop, so nav
 * and other page content stay interactive around it.
 *
 * Positioned relative to `anchorRef` on the same principle as `Tooltip`
 * (portalled to `document.body`, measured via `getBoundingClientRect` so a
 * scrollable ancestor like the nav rail can't clip it, flipped above the
 * anchor if there's no room below) but, unlike `Tooltip`, the measured
 * position is applied directly to the DOM node in the same layout effect
 * rather than through React state — routing it through state would add an
 * extra render between mount and the shared focus-management effect below,
 * which raced it and left focus on the page instead of moving into the
 * popover. It's also click-triggered rather than hover-triggered and is
 * interactive: focus moves into it on open and is trapped there (see
 * `dialogA11y.ts`, shared with `Modal`/`SidePanel`), and it closes on
 * Escape or a click anywhere outside itself and its anchor — the caller is
 * expected to hold `onClose` as "set open state to false" and pass a
 * stable `anchorRef` for the trigger button.
 *
 * The position is re-measured when the window or any ancestor scrolls or resizes and when the content
 * changes size, so it stays attached to its anchor (scrolling the popover's own content does not move it,
 * so it is ignored); if the content does not fit on the roomier side
 * of the anchor it is capped to the room and scrolls inside, so no control is ever out of reach.
 *
 * A popover has no header, so it clears any enclosing dialog's header slots: a `FormActions` inside it
 * keeps its buttons in the popover instead of moving them to the dialog behind it.
 *
 * A press inside a dialog the popover's own content opened (a confirmation) is not "outside": that dialog is a portal
 * beside the popover in the DOM, opened after it, so a press in anything portalled after this popover leaves it open
 * while its confirmation is answered.
 *
 * `fit` sizes the panel to its content instead of the fixed 280px (up to the
 * viewport width less a margin, `.popover-bubble`'s `max-width`), for a menu
 * whose longest label would otherwise clip.
 *
 * `placement="side"` opens the panel to the right of the anchor with their top edges level, for a small
 * (+) button whose panel should not cover the field it sits beside; it opens below when the width does not fit.
 *
 * `menu` gives the panel the look of an action menu (`ActionMenuList`): tighter padding, a soft shadow and a small caret
 * pointing at the anchor, on the side the panel opened (the caret is hidden while the panel is capped and scrolling).
 *
 * `matchAnchor` makes the panel open like a native select list: its left edge on the anchor's and at least
 * as wide as the anchor (never under 280px), for an anchor that is a form control and not a small button. The panel's
 * content takes the width it is given and must not set a minimum of its own: the bubble is only as wide as the field,
 * so a wider fixed content runs out of the bubble, the card and the window. It also keeps below the field, scrolling
 * inside, while at least 240px of room is there, so it does not flip over the fields above the anchor.
 */
export function Popover({
  anchorRef,
  onClose,
  title,
  fit = false,
  matchAnchor = false,
  placement = "below",
  menu = false,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  title: string;
  fit?: boolean;
  matchAnchor?: boolean;
  placement?: "below" | "side";
  menu?: boolean;
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
      const anchorRect = anchor.getBoundingClientRect();
      if (matchAnchor) bubble.style.width = `${Math.max(MATCH_ANCHOR_MIN_WIDTH_PX, anchorRect.width)}px`;
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
        bubble.style.overflowY = "auto";
        bubble.scrollTop = scrolled;
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
  }, [anchorRef, matchAnchor, placement, menu]);

  useEffect(() => {
    // Listens in the capture phase on `pointerdown`: React Flow's pane and nodes (d3-zoom, d3-drag) stop a
    // `mousedown` before it bubbles to the document, so a bubble-phase `mousedown` listener never saw a click on a
    // diagram and a popover opened over one could not be dismissed by clicking away. A capture listener on the
    // document runs before any of them, and `pointerdown` is not suppressed with the compatibility mouse events.
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
      className={menu ? "card stack popover-bubble popover-menu" : "card stack popover-bubble"}
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
