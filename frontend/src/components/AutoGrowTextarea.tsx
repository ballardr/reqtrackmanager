/**
 * Module: components/AutoGrowTextarea
 *
 * A `<textarea>` that grows with its content instead of scrolling inside a
 * fixed number of rows, capped at a maximum visible height so a pasted
 * essay doesn't push the rest of the form off-screen. See
 * docs/ux-audit-2026-08.md's "New requirement form: three unlabelled
 * fields, no auto-grow" (roadmap item 525) and docs/ux-style-guide.md's
 * "Missing components identified this pass" table — nothing in
 * `frontend/src/components/` did `scrollHeight`-based resize before this.
 *
 * Design decision: the height cap is computed from the textarea's own
 * *resolved* `line-height` (`getComputedStyle`, not a hardcoded pixel
 * number) multiplied by `maxVisibleLines` (default 8, per the audit's own
 * "roughly 8 lines" suggestion), plus its actual padding/border — so the
 * cap tracks `theme.css`'s real typography (15px body font / 1.5
 * line-height today) if that ever changes, rather than every caller
 * needing to keep a magic pixel number in sync with the stylesheet by
 * hand. Re-measured on every value change (one cheap `getComputedStyle`
 * call) rather than once on mount, since content growing past the cap is
 * exactly the case this component exists to catch.
 *
 * Responsibilities: sizes itself (`element.style.height`); does not own
 * the field's value — the caller remains the source of truth via
 * `value`/`onChange`, same contract as a plain controlled `<textarea>`.
 */
import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

const DEFAULT_MAX_VISIBLE_LINES = 8;

export function AutoGrowTextarea({
  value,
  onChange,
  maxVisibleLines = DEFAULT_MAX_VISIBLE_LINES,
  className = "input",
  style,
  ...rest
}: {
  value: string;
  onChange: (value: string) => void;
  /** Caps growth at roughly this many lines of the textarea's own resolved
   * line-height — see the module doc above for why this isn't a fixed
   * pixel number. */
  maxVisibleLines?: number;
} & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "rows">) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const computed = window.getComputedStyle(el);
    // `line-height` is one of the few properties getComputedStyle resolves
    // to a used pixel value rather than echoing the specified keyword back
    // (theme.css sets a real `1.5`, not `normal`, on the body, so this is
    // reliable in practice) — the `|| 20` fallback only guards an
    // environment where that resolution doesn't happen (e.g. a test DOM
    // with no stylesheet loaded at all).
    const lineHeight = parseFloat(computed.lineHeight) || 20;
    const verticalPadding = (parseFloat(computed.paddingTop) || 0) + (parseFloat(computed.paddingBottom) || 0);
    const verticalBorder = (parseFloat(computed.borderTopWidth) || 0) + (parseFloat(computed.borderBottomWidth) || 0);
    const maxHeight = lineHeight * maxVisibleLines + verticalPadding + verticalBorder;
    el.style.maxHeight = `${maxHeight}px`;
    el.style.height = "auto";
    // `scrollHeight` never includes border (it's always a content+padding
    // measurement, regardless of box-sizing) — `theme.css` sets a global
    // `box-sizing: border-box`, under which `height` sets the *total*
    // border-box size, so `verticalBorder` has to be added back here or
    // every resize would silently shrink the visible content area by the
    // border width. `maxHeight` above already accounts for this the same
    // way, so both branches target the same box model.
    el.style.height = `${Math.min(el.scrollHeight + verticalBorder, maxHeight)}px`;
  }, [value, maxVisibleLines]);

  return (
    <textarea
      ref={ref}
      className={className}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ overflowY: "auto", resize: "vertical", ...style }}
      {...rest}
    />
  );
}
