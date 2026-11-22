/**
 * Module: components/ScrollRegion
 *
 * The one scrolling list: a capped box that scrolls by itself with the product's thin themed scrollbar, an edge
 * indicator on a side only while content continues beyond it, no scroll chaining to the page behind it
 * (`overscroll-behavior: contain`) and a focus ring that is drawn inside, never clipped at its edge. The look is the
 * `.scroll-region` rule in `styles/theme.css` (no scroll listener); this component only sets the cap.
 *
 * Presentational. A caller that needs a header that stays put (a search box) renders it outside the region, and puts
 * the padding on the region (its `style`), so the scrollbar and the clipped edge meet the container's border.
 * A region shorter than its cap has no scrollbar and no indicator.
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
