/**
 * Module: testing/buttonHeights
 *
 * The shared "do neighbouring buttons share a height?" assertion. The style guide's button sizes
 * pattern says buttons that sit next to each other share a size ("Neighbours match"), but nothing
 * measured it: a small Undo beside a medium Export menu passed every other check. This reads the
 * rendered height of the buttons in each row and returns what is wrong, so Storybook play functions
 * and Playwright specs fail instead of someone spotting it in a screenshot.
 *
 * Self-contained on purpose (no imports, helpers inside the function) so Playwright can ship it into
 * the page with `page.evaluate`, the same as `orphanedControls` and `iconSizes`.
 *
 * Rules (an ancestor with `data-button-size-ok` opts out, with a reason beside it):
 * - a row is a flex container laid out horizontally; each visible child is one item, and an item is a
 *   `.btn` or a wrapper holding exactly one `.btn` (a tooltip or a menu trigger's wrapper);
 * - items of one row that share a line (their boxes overlap vertically) must have the same height,
 *   to within one pixel. A row of buttons that wraps compares each line on its own.
 * A button beside text, a pill or a chip is not compared: those have their own checks.
 */

/** One row of the measurement table: a button and the line of siblings it is compared with. */
export interface ButtonHeightMeasurement {
  text: string;
  heightPx: number;
  /** Short DOM path to the row's container, for locating the offender. */
  container: string;
}

/** What `buttonHeightGeometry` reports. */
export interface ButtonHeightGeometry {
  measurements: ButtonHeightMeasurement[];
  violations: string[];
}

/**
 * Measures the buttons in every horizontal flex row under `root` and lists the rows whose
 * neighbouring buttons differ in height.
 *
 * @param root Element to search; defaults to the whole document.
 * @returns One measurement per compared button in document order, and the human-readable violations
 *     (empty when every row of buttons is one height).
 */
export function buttonHeightGeometry(root?: Element): ButtonHeightGeometry {
  const scope: ParentNode = root ?? document;
  const round = (n: number) => Math.round(n * 10) / 10;
  const describe = (el: Element): string => {
    const parts: string[] = [];
    let node: Element | null = el;
    for (let depth = 0; node && depth < 3 && node !== document.body; depth += 1) {
      const cls = (node.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)[0];
      parts.unshift(node.tagName.toLowerCase() + (cls ? `.${cls}` : ""));
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const visible = (el: Element) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  /** The button an item stands for: itself, or the only button inside it. */
  const buttonOf = (item: Element): HTMLElement | null => {
    if (item.classList.contains("btn")) return item as HTMLElement;
    const inside = item.querySelectorAll<HTMLElement>(".btn");
    return inside.length === 1 ? inside[0] : null;
  };

  const measurements: ButtonHeightMeasurement[] = [];
  const violations: string[] = [];
  const containers = Array.from(scope.querySelectorAll<HTMLElement>("*"));
  if (scope instanceof HTMLElement) containers.unshift(scope);
  containers.forEach((container) => {
    if (container.closest("[data-button-size-ok]")) return;
    const style = getComputedStyle(container);
    if (!style.display.includes("flex") || style.flexDirection.startsWith("column")) return;
    const items = Array.from(container.children)
      .filter(visible)
      .map((child) => buttonOf(child))
      .filter((btn): btn is HTMLElement => btn !== null && visible(btn));
    if (items.length < 2) return;
    const lines: HTMLElement[][] = [];
    items.forEach((btn) => {
      const rect = btn.getBoundingClientRect();
      const line = lines.find((l) => {
        const first = l[0].getBoundingClientRect();
        return rect.top < first.bottom - 1 && rect.bottom > first.top + 1;
      });
      if (line) line.push(btn);
      else lines.push([btn]);
    });
    lines.forEach((line) => {
      if (line.length < 2) return;
      const heights = line.map((btn) => round(btn.getBoundingClientRect().height));
      const text = (btn: HTMLElement) => (btn.getAttribute("aria-label") ?? btn.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 30);
      line.forEach((btn, i) => measurements.push({ text: text(btn), heightPx: heights[i], container: describe(container) }));
      if (Math.max(...heights) - Math.min(...heights) > 1) {
        const list = line.map((btn, i) => `"${text(btn)}" ${heights[i]}px`).join(", ");
        violations.push(`buttons in one row differ in height (${list}) in ${describe(container)}`);
      }
    });
  });
  return { measurements, violations };
}

/** Violations only, for Storybook play functions. */
export function buttonHeightViolations(root?: Element): string[] {
  return buttonHeightGeometry(root).violations;
}
