import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

import { useDialogA11y } from "./dialogA11y";

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
 */
export function Popover({
  anchorRef,
  onClose,
  title,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const bubbleRef = useRef<HTMLDivElement>(null);
  useDialogA11y(bubbleRef, onClose);

  useLayoutEffect(() => {
    function measure() {
      const anchor = anchorRef.current;
      const bubble = bubbleRef.current;
      if (!anchor || !bubble) return;
      const anchorRect = anchor.getBoundingClientRect();
      const bubbleRect = bubble.getBoundingClientRect();

      let left = anchorRect.right - bubbleRect.width;
      left = Math.max(VIEWPORT_MARGIN_PX, Math.min(left, window.innerWidth - bubbleRect.width - VIEWPORT_MARGIN_PX));

      const spaceBelow = window.innerHeight - anchorRect.bottom - bubbleRect.height - VERTICAL_GAP_PX;
      const top =
        spaceBelow < VIEWPORT_MARGIN_PX
          ? Math.max(VIEWPORT_MARGIN_PX, anchorRect.top - bubbleRect.height - VERTICAL_GAP_PX)
          : anchorRect.bottom + VERTICAL_GAP_PX;

      bubble.style.top = `${top}px`;
      bubble.style.left = `${left}px`;
      bubble.style.visibility = "visible";
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
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
        width: 280,
        visibility: "hidden",
      }}
    >
      {children}
    </div>,
    document.body
  );
}
