/**
 * Module: testing/statBlockGeometry
 *
 * The shared "is this block of stats tidy?" assertion. A stat block (a flat
 * `StatBar`, a grouped `StatBar`, or a `.grid-metrics` grid of `StatCard`s /
 * `MetricTile`s) can look fine in a short isolated story and still come out
 * ragged once there are many entries, long labels or a narrow container. The
 * 25-figure summary report did exactly that, as did the org-overview and
 * compliance stat rows before it. This reads real layout and returns what is
 * wrong, so Storybook play functions and Playwright specs fail on it instead
 * of someone spotting it in a screenshot.
 *
 * Self-contained on purpose (no imports, helpers inside the function) so
 * Playwright can ship it into the page with `page.evaluate`, and the same
 * rules therefore apply in Storybook (real Chromium) and in the e2e suite.
 *
 * Rules, per block (`[data-stat-block]`, `.stat-groups`, `.grid-metrics`):
 * - nothing overflows the block horizontally;
 * - entries in one visual row share a top and a height (equal-height rows);
 * - the number of distinct left edges equals the widest row (columns line up;
 *   a ragged flex-wrap produces more);
 * - no label wraps onto more than three lines (a longer one has swamped its
 *   number: shorten it or group the block).
 *
 * @param root Element to search; defaults to the whole document.
 * @returns Human-readable violations; empty when every block is tidy.
 */
export function statBlockViolations(root?: Element): string[] {
  const scope: ParentNode = root ?? document;
  const violations: string[] = [];
  const blocks = Array.from(scope.querySelectorAll<HTMLElement>("[data-stat-block], .stat-groups, .grid-metrics"));
  if (blocks.length === 0) return ["no stat block found to check"];
  const round = (n: number) => Math.round(n);
  blocks.forEach((block, index) => {
    const snippet = (block.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
    const name = `${block.getAttribute("data-stat-block") ?? block.className.split(" ")[0]} block #${index + 1} ("${snippet}…")`;
    if (block.scrollWidth > block.clientWidth + 1) {
      violations.push(`${name}: overflows horizontally (${block.scrollWidth}px content in ${block.clientWidth}px)`);
    }
    const entries =
      block.matches(".stat-groups, .grid-metrics")
        ? (Array.from(block.children) as HTMLElement[])
        : Array.from(block.querySelectorAll<HTMLElement>("[data-stat-entry]"));
    const rows = new Map<number, HTMLElement[]>();
    entries.forEach((entry) => {
      const top = round(entry.getBoundingClientRect().top);
      // Entries whose tops are within 2px sit on the same visual row.
      const key = [...rows.keys()].find((k) => Math.abs(k - top) <= 2) ?? top;
      rows.set(key, [...(rows.get(key) ?? []), entry]);
    });
    let widest = 0;
    rows.forEach((row) => {
      widest = Math.max(widest, row.length);
      const heights = new Set(row.map((e) => round(e.getBoundingClientRect().height)));
      if (heights.size > 1) violations.push(`${name}: entries in one row have unequal heights (${[...heights].join(", ")}px)`);
    });
    const lefts = new Set<number>();
    entries.forEach((entry) => {
      const left = round(entry.getBoundingClientRect().left);
      lefts.add([...lefts].find((l) => Math.abs(l - left) <= 2) ?? left);
    });
    if (entries.length > 0 && lefts.size !== widest) {
      violations.push(`${name}: ${lefts.size} distinct column edges for rows of at most ${widest} (ragged columns)`);
    }
    block.querySelectorAll<HTMLElement>(".stat-bar-label, .stat-group-row dt").forEach((label) => {
      const lineHeight = parseFloat(getComputedStyle(label).lineHeight) || parseFloat(getComputedStyle(label).fontSize) * 1.4;
      const lines = Math.round(label.getBoundingClientRect().height / lineHeight);
      if (lines > 3) violations.push(`${name}: label "${label.textContent}" wraps onto ${lines} lines`);
    });
  });
  return violations;
}
