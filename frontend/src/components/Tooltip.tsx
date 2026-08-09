import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const VIEWPORT_MARGIN_PX = 8;
const VERTICAL_GAP_PX = 6.4; // 0.4rem

/**
 * A lightweight hover/focus tooltip for icon-only controls, replacing
 * reliance on the native `title` attribute — `title` has a slow,
 * inconsistent OS-level hover delay and doesn't appear on touch at all,
 * which is exactly what made the collapsed nav rail hard to use before
 * this was added. Appears immediately on hover or keyboard focus (no
 * delay to tune), and disappears on blur/mouse-leave.
 *
 * Screen-aware, and rendered through a portal into `document.body` as a
 * viewport-`fixed` element positioned with plain pixel coordinates
 * computed from the trigger's `getBoundingClientRect()` plus the bubble's
 * own (intrinsic, position-independent) width/height. The portal is the
 * important part: an ordinary absolutely-positioned bubble nested inside
 * the trigger would still get clipped by the nearest scrollable ancestor
 * regardless of how correct its left/right math was — the nav rail is
 * exactly such an ancestor (`overflow-y: auto` implicitly makes its
 * `overflow-x` clip too, per the CSS spec), which is what made tooltips
 * on the collapsed rail's icons disappear off-screen. Re-measured on
 * every show (not just on mount/resize) because the trigger's position
 * can change for reasons that never fire a `resize` event at all — e.g.
 * that same rail collapsing to icon-only width.
 *
 * This does *not* set the wrapped child's `aria-label` automatically —
 * the child is arbitrary JSX, not a component this can safely clone props
 * onto — so callers must still set `aria-label={label}` (and may keep
 * `title={label}` too, redundant but harmless) on the actual interactive
 * element themselves.
 */
export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    function measure() {
      const trigger = triggerRef.current;
      const bubble = bubbleRef.current;
      if (!trigger || !bubble) return;
      const triggerRect = trigger.getBoundingClientRect();
      const bubbleRect = bubble.getBoundingClientRect();

      let left = triggerRect.left + triggerRect.width / 2 - bubbleRect.width / 2;
      left = Math.max(VIEWPORT_MARGIN_PX, Math.min(left, window.innerWidth - bubbleRect.width - VIEWPORT_MARGIN_PX));

      const spaceAbove = triggerRect.top - bubbleRect.height - VERTICAL_GAP_PX;
      const top = spaceAbove < VIEWPORT_MARGIN_PX ? triggerRect.bottom + VERTICAL_GAP_PX : spaceAbove;

      setPosition({ top, left });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [visible]);

  return (
    <span
      ref={triggerRef}
      className="tooltip-trigger"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {createPortal(
        <span
          ref={bubbleRef}
          role="tooltip"
          className="tooltip-bubble"
          style={{
            top: position?.top ?? 0,
            left: position?.left ?? 0,
            opacity: visible && position ? 1 : 0,
            visibility: visible && position ? "visible" : "hidden",
          }}
        >
          {label}
        </span>,
        document.body
      )}
    </span>
  );
}
