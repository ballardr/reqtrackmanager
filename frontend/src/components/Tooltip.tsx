import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";

const VIEWPORT_MARGIN_PX = 8;
const VERTICAL_GAP_PX = 6.4; // 0.4rem
// A pointer-following bubble sits below the cursor by roughly the cursor's own height, so it never covers what is being pointed at.
const POINTER_OFFSET_PX = 20;

/**
 * A lightweight hover/focus tooltip for icon-only controls, used instead of the native `title` attribute (slow,
 * inconsistent hover delay, absent on touch). It appears immediately on hover or keyboard focus and disappears on
 * blur or mouse-leave.
 *
 * Rendered through a portal into `document.body` as a viewport-`fixed` element positioned in pixels from the trigger's
 * `getBoundingClientRect()` and the bubble's own size. The portal matters: a bubble nested in the trigger would be
 * clipped by the nearest scrollable ancestor (the nav rail, whose `overflow-y: auto` also clips `overflow-x`). It is
 * measured again on every show, since the trigger can move without a `resize` event (the rail collapsing).
 *
 * It does not set the child's `aria-label` (the child is arbitrary JSX), so callers set `aria-label={label}` on the
 * interactive element themselves.
 *
 * `followPointer` is for wide hover targets (a table row or stat cell made clickable by a stretched link): the bubble sits
 * just below the pointer, centred on it, and tracks it, staying inside the viewport (clamped horizontally, flipped above
 * when there is no room below); keyboard focus falls back to trigger-centred placement.
 *
 * `className`/`style` apply to the wrapping span (merged with its default `tooltip-trigger` class), not the child. A
 * `position: fixed` child (the nav-rail collapse toggle) is placed independently of the DOM flow, so its in-flow wrapper
 * would collapse to a zero-size box and `measure()` (which reads the span's rectangle) would place the bubble there;
 * the caller gives the span the same fixed placement so it is the button's true on-screen box.
 *
 * `pinnable` is for a tooltip carrying a sentence or two to read (field help): a click or tap on the trigger (Enter or
 * Space on keyboard focus) pins the bubble open and the next closes it; hover and focus still show it. Escape closes it
 * without leaving the trigger (and stops there, so a dialog around it stays open), as does a press outside the trigger.
 * `wrap` lets a long label wrap inside a bounded width. `bubbleId` is the bubble's id, for the trigger's
 * `aria-describedby`. The bubble is measured again when anything scrolls, since a pinned one would otherwise be left
 * behind by a scrolling dialog body.
 *
 * `disabled` keeps the wrapper (so the layout does not change) but never shows the bubble: for a label worth showing only
 * some of the time, such as the full text of a clipped cell (`CellText`).
 */
export function Tooltip({
  label, children, className, style, followPointer = false, pinnable = false, wrap = false, bubbleId, disabled = false,
}: {
  label: string; children: ReactNode; className?: string; style?: CSSProperties; followPointer?: boolean;
  pinnable?: boolean; wrap?: boolean; bubbleId?: string; disabled?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [pinned, setPinned] = useState(false);
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
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [visible, followPointer, pointer]);

  useEffect(() => {
    if (!pinned) return;
    function onPointerDown(e: PointerEvent) {
      if (triggerRef.current?.contains(e.target as Node)) return;
      setPinned(false);
      setVisible(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [pinned]);

  function close() {
    setPinned(false);
    setVisible(false);
    setPointer(null);
  }

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
        if (pinned) return;
        setVisible(false);
        setPointer(null);
      }}
      onFocus={() => setVisible(true)}
      onBlur={close}
      onClick={pinnable ? () => (pinned ? close() : setPinned(true)) : undefined}
      onKeyDown={pinnable ? (e) => {
        if (e.key !== "Escape" || !visible) return;
        e.stopPropagation();
        close();
      } : undefined}
    >
      {children}
      {visible && !disabled && createPortal(
        <span
          ref={bubbleRef}
          id={bubbleId}
          role="tooltip"
          className={wrap ? "tooltip-bubble tooltip-bubble--wrap" : "tooltip-bubble"}
          style={{
            top: position?.top ?? 0,
            left: position?.left ?? 0,
            opacity: position ? 1 : 0,
            visibility: position ? "visible" : "hidden",
          }}
        >
          {label}
        </span>,
        document.body
      )}
    </span>
  );
}
