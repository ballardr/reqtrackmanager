import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";

const VIEWPORT_MARGIN_PX = 8;
const VERTICAL_GAP_PX = 6.4; // 0.4rem
// A pointer-following bubble sits below the cursor by roughly the cursor's own height, so it never covers what is being pointed at.
const POINTER_OFFSET_PX = 20;

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
 *
 * `followPointer` is for wide hover targets (a whole table row or stat cell
 * made clickable by a stretched link), where centring on the trigger would
 * put the bubble away from the cursor: the bubble then sits just below the
 * pointer, centred on it, and tracks it while it moves over the target.
 * It still stays inside the viewport (clamped horizontally, flipped above the
 * pointer when there is no room below), and a keyboard focus (no pointer)
 * falls back to the trigger-centred placement.
 *
 * `className`/`style` are applied to the wrapping span itself (merged with
 * its own default `tooltip-trigger` class), not the child. They matter for
 * a `position: fixed` child like the nav-rail collapse toggle: that button
 * is placed by its own `left`/`top`, entirely independent of where its
 * parent sits in normal flow, so the default shrink-wrapped, in-flow
 * `tooltip-trigger` span collapses to a zero-size box wherever the DOM
 * happens to put it — nowhere near the button it wraps — and `measure()`
 * below (which reads *this* span's `getBoundingClientRect()`, not the
 * child's) would position the bubble there instead. The fix is for the
 * caller to give the wrapping span the same `position: fixed` placement as
 * the fixed child, via these props, so the span IS the button's true
 * on-screen box and measurement is accurate again.
 */
export function Tooltip({
  label, children, className, style, followPointer = false,
}: { label: string; children: ReactNode; className?: string; style?: CSSProperties; followPointer?: boolean }) {
  const [visible, setVisible] = useState(false);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
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

      const anchorX = followPointer && pointer ? pointer.x : triggerRect.left + triggerRect.width / 2;
      let left = anchorX - bubbleRect.width / 2;
      left = Math.max(VIEWPORT_MARGIN_PX, Math.min(left, window.innerWidth - bubbleRect.width - VIEWPORT_MARGIN_PX));

      let top: number;
      if (followPointer && pointer) {
        // Below the cursor; flip above it when the bubble would leave the viewport.
        const below = pointer.y + POINTER_OFFSET_PX;
        top = below + bubbleRect.height + VIEWPORT_MARGIN_PX > window.innerHeight
          ? Math.max(VIEWPORT_MARGIN_PX, pointer.y - bubbleRect.height - VERTICAL_GAP_PX)
          : below;
      } else {
        const spaceAbove = triggerRect.top - bubbleRect.height - VERTICAL_GAP_PX;
        top = spaceAbove < VIEWPORT_MARGIN_PX ? triggerRect.bottom + VERTICAL_GAP_PX : spaceAbove;
      }

      setPosition({ top, left });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [visible, followPointer, pointer]);

  return (
    <span
      ref={triggerRef}
      className={className ? `tooltip-trigger ${className}` : "tooltip-trigger"}
      style={style}
      onMouseEnter={(e) => {
        if (followPointer) setPointer({ x: e.clientX, y: e.clientY });
        setVisible(true);
      }}
      onMouseMove={followPointer ? (e) => setPointer({ x: e.clientX, y: e.clientY }) : undefined}
      onMouseLeave={() => {
        setVisible(false);
        setPointer(null);
      }}
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
