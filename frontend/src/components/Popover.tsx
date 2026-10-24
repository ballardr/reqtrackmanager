import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

import { useDialogA11y } from "./dialogA11y";
import { DialogSlotContext } from "./dialogSlots";

const VIEWPORT_MARGIN_PX = 8;
const VERTICAL_GAP_PX = 6.4; // 0.4rem

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
 * changes size, so it stays attached to its anchor; if the content does not fit on the roomier side
 * of the anchor it is capped to the room and scrolls inside, so no control is ever out of reach.
 *
 * A popover has no header, so it clears any enclosing dialog's header slots: a `FormActions` inside it
 * keeps its buttons in the popover instead of moving them to the dialog behind it.
 *
 * `fit` sizes the panel to its content instead of the fixed 280px (up to the
 * viewport width less a margin, `.popover-bubble`'s `max-width`), for a menu
 * whose longest label would otherwise clip.
 */
export function Popover({
  anchorRef,
  onClose,
  title,
  fit = false,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  title: string;
  fit?: boolean;
  children: ReactNode;
}) {
  const bubbleRef = useRef<HTMLDivElement>(null);
  useDialogA11y(bubbleRef, onClose);

  useLayoutEffect(() => {
    function measure() {
      const anchor = anchorRef.current;
      const bubble = bubbleRef.current;
      if (!anchor || !bubble) return;
      // Measure the content's natural height, not a height capped by an earlier pass.
      bubble.style.maxHeight = "";
      const anchorRect = anchor.getBoundingClientRect();
      const bubbleRect = bubble.getBoundingClientRect();

      let left = anchorRect.right - bubbleRect.width;
      left = Math.max(VIEWPORT_MARGIN_PX, Math.min(left, window.innerWidth - bubbleRect.width - VIEWPORT_MARGIN_PX));

      // Open on the side with room for the whole bubble, else on the roomier side, capped to that room
      // and scrolling inside, so every control in it can be reached however low the anchor sits.
      const spaceBelow = window.innerHeight - anchorRect.bottom - VERTICAL_GAP_PX - VIEWPORT_MARGIN_PX;
      const spaceAbove = anchorRect.top - VERTICAL_GAP_PX - VIEWPORT_MARGIN_PX;
      const below = bubbleRect.height <= spaceBelow || spaceBelow >= spaceAbove;
      const room = Math.max(0, below ? spaceBelow : spaceAbove);
      const height = Math.min(bubbleRect.height, room);
      if (bubbleRect.height > room) {
        bubble.style.maxHeight = `${room}px`;
        bubble.style.overflowY = "auto";
      }
      const top = below ? anchorRect.bottom + VERTICAL_GAP_PX : anchorRect.top - height - VERTICAL_GAP_PX;

      bubble.style.top = `${top}px`;
      bubble.style.left = `${left}px`;
      bubble.style.visibility = "visible";
    }
    measure();
    // The bubble is `position: fixed`, so it must follow its anchor when any ancestor scrolls (the page
    // scrolls inside a container, not the window) and when its own content changes size.
    const observer = new ResizeObserver(measure);
    if (bubbleRef.current) observer.observe(bubbleRef.current);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [anchorRef]);

  useEffect(() => {
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (bubbleRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [anchorRef, onClose]);

  return createPortal(
    <div
      ref={bubbleRef}
      className="card stack popover-bubble"
      role="dialog"
      aria-label={title}
      tabIndex={-1}
      style={{
        position: "fixed",
        zIndex: 1150,
        width: fit ? "max-content" : 280,
        visibility: "hidden",
      }}
    >
      <DialogSlotContext.Provider value={null}>{children}</DialogSlotContext.Provider>
    </div>,
    document.body
  );
}
