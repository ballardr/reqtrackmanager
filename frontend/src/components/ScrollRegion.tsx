/**
 * Module: components/ScrollRegion
 *
 * The one scrolling list: a capped box with the product's thin themed scrollbar, an edge indicator on a side only while
 * content continues beyond it, no scroll chaining to the page behind (`overscroll-behavior: contain`) and a focus ring
 * drawn inside, never clipped. The look is the `.scroll-region` rule in `styles/theme.css` (no scroll listener); this
 * component only sets the cap.
 *
 * Presentational. A header that stays put (a search box) is rendered outside the region; padding goes on the region
 * (its `style`) so the scrollbar and clipped edge meet the container's border.
 */
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

/**
 * A scrolling list with the shared scrollbar and edge indicators.
 *
 * @param maxHeight The height the region may grow to before it scrolls (a CSS length such as `20rem`); omit when a flex
 *   parent bounds it instead (the region then takes `flex: 1 1 auto; min-height: 0` from its container).
 * @param style Extra inline style (padding, minimum width); `maxHeight` is applied after it.
 * @param children The list.
 * @param rest Any other attribute of a `div` (`role`, `aria-label`, `tabIndex`, `ref` through the DOM).
 * @returns The scrolling element.
 */
export function ScrollRegion({
  maxHeight, style, className, children, ...rest
}: { maxHeight?: string; style?: CSSProperties; className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={className ? `scroll-region ${className}` : "scroll-region"} style={{ ...style, ...(maxHeight ? { maxHeight } : {}) }}>
      {children}
    </div>
  );
}
