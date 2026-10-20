/**
 * Module: testing/orphanedControls
 *
 * The shared "do controls and pills stay where they belong?" assertion. Text
 * that sits beside a control can push that control onto a new line when the
 * text is long (a 200-character title drops its Delete button below it), and a
 * pill whose label wraps changes height and breaks the row it is in. A short
 * story or a tidy demo record never shows either. This reads real layout and
 * returns what is wrong, so Storybook play functions and Playwright specs fail
 * instead of someone spotting it in a screenshot.
 *
 * Self-contained on purpose (no imports, helpers inside each function) so
 * Playwright can ship it into the page with `page.evaluate`, and the same
 * rules therefore apply in Storybook (real Chromium) and in the e2e suite.
 *
 * Rules (a container or ancestor with `data-wrap-ok` opts out; toolbars and
 * filter bars that are meant to wrap use it, or the plain `.row` they already
 * are not checked unless a control ends up alone at the start of a line):
 * - a `.btn` or `.badge` must not be the first item on a second or later line
 *   of its flex container, unless the line before it is made only of controls
 *   and pills (a toolbar of buttons wrapping at a narrow width is fine; text
 *   dropping its trailing control is not);
 * - a `.badge` narrower than its maximum width must be a single line;
 * - a `.badge` must never exceed two lines.
 */

/** One row of the measurement table: a pill or button and the facts that define "tidy". */
export interface ControlMeasurement {
  kind: "badge" | "btn";
  text: string;
  heightPx: number;
  widthPx: number;
  paddingPx: string;
  fontSizePx: number;
  lines: number;
  /** Set when the control is the first item on a later line of its flex container. */
  orphaned: boolean;
  /** Short DOM path to the container, for locating the offender. */
  container: string;
  /** Start of the control's own HTML, to find the offender when its text is empty (an icon button). */
  html: string;
}

/** What `controlGeometry` reports. */
export interface ControlGeometry {
  measurements: ControlMeasurement[];
  violations: string[];
}

/**
 * Measures every `.badge` and `.btn` under `root` and lists what is wrong with them. One function
 * (not two that call each other) because Playwright serialises only the function it is given.
 *
 * @param root Element to search; defaults to the whole document.
 * @returns One measurement per control in document order, and the human-readable violations
 *     (empty when every control is where it belongs).
 */
export function controlGeometry(root?: Element): ControlGeometry {
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
  const isControl = (el: Element) => el.classList.contains("btn") || el.classList.contains("badge");
  const visible = (el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };

  const orphans = new Set<Element>();
  scope.querySelectorAll<HTMLElement>("*").forEach((container) => {
    if (container.closest("[data-wrap-ok]")) return;
    const style = getComputedStyle(container);
    if (!style.display.includes("flex") || style.flexWrap === "nowrap") return;
    const children = (Array.from(container.children) as HTMLElement[]).filter(visible);
    if (children.length < 2) return;
    const lines: HTMLElement[][] = [];
    children.forEach((child) => {
      const top = child.getBoundingClientRect().top;
      const line = lines.find((l) => {
        const rect = l[0].getBoundingClientRect();
        // Same line when the child's box overlaps the line's first box vertically.
        return top < rect.bottom - 1 && child.getBoundingClientRect().bottom > rect.top + 1;
      });
      if (line) line.push(child);
      else lines.push([child]);
    });
    lines.forEach((line, index) => {
      if (index === 0) return;
      const previous = lines[index - 1];
      // A wrapped toolbar of nothing but controls and pills is allowed; text pushing a control away is not.
      if (previous.every(isControl)) return;
      const first = line[0];
      if (isControl(first)) orphans.add(first);
    });
  });

  const result: ControlMeasurement[] = [];
  scope.querySelectorAll<HTMLElement>(".badge, .btn").forEach((el) => {
    if (!visible(el)) return;
    const style = getComputedStyle(el);
    const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
    const inner = el.getBoundingClientRect().height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
      - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth);
    result.push({
      kind: el.classList.contains("badge") ? "badge" : "btn",
      text: (el.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40),
      heightPx: round(el.getBoundingClientRect().height),
      widthPx: round(el.getBoundingClientRect().width),
      paddingPx: `${style.paddingTop} ${style.paddingRight}`,
      fontSizePx: parseFloat(style.fontSize),
      lines: Math.max(1, Math.round(inner / lineHeight)),
      orphaned: orphans.has(el),
      container: el.parentElement ? describe(el.parentElement) : "",
      html: el.outerHTML.replace(/\s+/g, " ").slice(0, 160),
    });
  });
  const violations: string[] = [];
  const measurements = result;
  const badges = Array.from(scope.querySelectorAll<HTMLElement>(".badge")).filter(
    (el) => el.getBoundingClientRect().width > 0,
  );
  measurements.forEach((m) => {
    if (m.orphaned) {
      violations.push(`${m.kind} "${m.text}" is alone at the start of a new line in ${m.container}: ${m.html}`);
    }
  });
  badges.forEach((badge) => {
    if (badge.closest("[data-wrap-ok]")) return;
    const style = getComputedStyle(badge);
    const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
    const rect = badge.getBoundingClientRect();
    const inner = rect.height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
      - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth);
    const lines = Math.max(1, Math.round(inner / lineHeight));
    const text = (badge.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
    const maxWidth = parseFloat(style.maxWidth);
    const atMaxWidth = Number.isFinite(maxWidth) && rect.width >= maxWidth - 2;
    if (lines > 2) violations.push(`badge "${text}" spans ${lines} lines (the limit is two)`);
    else if (lines > 1 && !atMaxWidth) {
      violations.push(`badge "${text}" wraps onto ${lines} lines while narrower than its maximum width`);
    }
  });
  return { measurements, violations };
}

/** Violations only, for Storybook play functions. */
export function orphanedControlViolations(root?: Element): string[] {
  return controlGeometry(root).violations;
}

/**
 * The menu items under `menu` whose label is cut off (wider than the item) or that stick out of the
 * menu or the viewport. A menu sizes to its longest label and wraps one that still does not fit, so
 * this list is empty for a tidy menu.
 *
 * @param menu The `role="menu"` element (or its popover) to inspect.
 * @returns Human-readable descriptions of each offending item.
 */
export function clippedMenuItems(menu: Element): string[] {
  const bubble = menu.closest(".popover-bubble") ?? menu;
  const box = bubble.getBoundingClientRect();
  const problems: string[] = [];
  if (box.left < 0 || box.right > window.innerWidth) problems.push("menu extends past the viewport");
  for (const item of menu.querySelectorAll<HTMLElement>('[role="menuitem"]')) {
    const rect = item.getBoundingClientRect();
    const text = (item.textContent ?? "").trim();
    if (item.scrollWidth > item.clientWidth + 1) problems.push(`"${text}" is clipped`);
    if (rect.right > box.right + 1 || rect.left < box.left - 1) problems.push(`"${text}" sticks out of the menu`);
  }
  return problems;
}
