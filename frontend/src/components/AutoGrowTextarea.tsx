/**
 * Module: components/AutoGrowTextarea
 *
 * A `<textarea>` that grows with its content, capped at a maximum visible height so a pasted essay does not push
 * the rest of the form off-screen. `rows` is the minimum height. Every long free-text field is one of these
 * (docs/ux-style-guide.md, "Pattern: auto-growing textarea"); `TextAreaField` renders it by default.
 *
 * Design: the cap is the resolved `line-height` (`getComputedStyle`) times `maxVisibleLines` (default 8) plus
 * padding and border, so it tracks the theme's typography without a hard-coded pixel value. It is re-measured on
 * every value change, since content outgrowing the cap is the case this exists for.
 *
 * It sizes itself (`element.style.height`) but does not own the value: the caller stays the source of truth.
 */
import { useImperativeHandle, useLayoutEffect, useRef, type Ref, type TextareaHTMLAttributes } from "react";

const DEFAULT_MAX_VISIBLE_LINES = 8;

export function AutoGrowTextarea({
  value,
  onChange,
  maxVisibleLines = DEFAULT_MAX_VISIBLE_LINES,
  className = "input",
  style,
  textareaRef,
  plainText: _plainText,
  ...rest
}: {
  value: string;
  onChange: (value: string) => void;
  /** Caps growth at roughly this many lines of the textarea's own resolved
   * line-height — see the module doc above for why this isn't a fixed
   * pixel number. */
  maxVisibleLines?: number;
  /** The underlying element, for a caller that needs the selection (a toolbar inserting at the cursor). */
  textareaRef?: Ref<HTMLTextAreaElement>;
  /** Why this long text is plain text, not Markdown (never rendered; `scripts/check_markdown_fields.py` requires it of a caller that
   * is not `MarkdownEditor` or `TextAreaField`). */
  plainText?: string;
} & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(textareaRef, () => ref.current as HTMLTextAreaElement, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const computed = window.getComputedStyle(el);
    // getComputedStyle resolves a numeric line-height to pixels (theme.css sets `1.5`); the `|| 20` fallback
    // covers a DOM with no stylesheet loaded.
    const lineHeight = parseFloat(computed.lineHeight) || 20;
    const verticalPadding = (parseFloat(computed.paddingTop) || 0) + (parseFloat(computed.paddingBottom) || 0);
    const verticalBorder = (parseFloat(computed.borderTopWidth) || 0) + (parseFloat(computed.borderBottomWidth) || 0);
    const maxHeight = lineHeight * maxVisibleLines + verticalPadding + verticalBorder;
    el.style.maxHeight = `${maxHeight}px`;
    el.style.height = "auto";
    // `scrollHeight` excludes the border, and the global `border-box` sizing makes `height` the total box, so
    // `verticalBorder` is added back; `maxHeight` above uses the same box model.
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
