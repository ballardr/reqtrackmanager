/**
 * Module: testing/TextStress
 *
 * The component of the "long text never breaks the layout" harness: it renders a view twice at the same width, once
 * with short text and once with long text, for `expectStressStable` (`testing/stressFixtures.ts`) to compare. See that
 * module for the fixtures and the assertion.
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
