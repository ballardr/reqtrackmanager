/**
 * Module: testing/TextStress
 *
 * Component of the "long text never breaks the layout" harness: renders a view
 * twice at the same width, with short and long text, for `expectStressStable`
 * (`testing/stressFixtures.ts`) to compare.
 */
import type { ReactNode } from "react";

/**
 * Renders a view twice, with short and long text, in boxes of the same width.
 *
 * @param render Draws the view; `long` is false for the short-text render and true for the long one.
 * @param width Width of each box in pixels (default 760, a settings panel's usual width).
 */
export function TextStress({ render, width = 760 }: { render: (long: boolean) => ReactNode; width?: number }) {
  return (
    <div>
      <div data-stress="short" style={{ width, marginBottom: 24 }}>{render(false)}</div>
      <div data-stress="long" style={{ width }}>{render(true)}</div>
    </div>
  );
}
