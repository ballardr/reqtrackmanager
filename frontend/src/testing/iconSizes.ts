/**
 * Module: testing/iconSizes
 *
 * The shared "is every icon the size its button says?" assertion. CSS sizes
 * button icons (`.btn svg` 16px, `.btn-sm svg` 14px; style guide "Pattern:
 * button sizes"); this reads the computed size of every icon inside a button
 * and returns what is wrong, for Storybook play functions and Playwright specs.
 * Self-contained (no imports, helpers inside the function) so Playwright can
 * ship it with `page.evaluate`, like `orphanedControls`.
 *
 * Rules (an ancestor with `data-icon-size-ok` opts out; scale in the style guide, "Icons"):
 * - an `svg` in a `.btn-sm` is 14px square; in any other `.btn`, 16px square;
 * - in a `.badge`, 12px square; in a collapsed (icon-only) nav-rail link, 14px;
 * - in any other nav-rail link, square and a whole number of pixels (16px, or
 *   14px for the disclosure chevron), so a long label cannot squeeze it.
 * Icons elsewhere are measured and reported but not enforced.
 */

/** One row of the measurement table: an icon and the container that sizes it. */
export interface IconMeasurement {
  /** What contains the icon: a medium button, a small button, a pill, a nav-rail link or something else. */
  context: "btn" | "btn-sm" | "badge" | "nav" | "other";
  widthPx: number;
  heightPx: number;
  /** Short DOM path to the icon's parent, for locating the offender. */
  container: string;
}

/** What `iconSizeGeometry` reports. */
export interface IconSizeGeometry {
  measurements: IconMeasurement[];
  violations: string[];
}

/**
 * Measures every visible `svg` under `root` and lists the button, pill and nav-link icons that are the wrong size.
 *
 * @param root Element to search; defaults to the whole document.
 * @returns One measurement per icon in document order, and the human-readable violations (empty
 *     when every icon is the size its container calls for).
 */
export function iconSizeGeometry(root?: Element): IconSizeGeometry {
  const scope: ParentNode = root ?? document;
  const medium = 16;
  const small = 14;
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

  const measurements: IconMeasurement[] = [];
  const violations: string[] = [];
  scope.querySelectorAll<SVGElement>("svg").forEach((svg) => {
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const context: IconMeasurement["context"] = svg.closest(".btn-sm")
      ? "btn-sm"
      : svg.closest(".btn") ? "btn" : svg.closest(".badge") ? "badge" : svg.closest(".nav-link") ? "nav" : "other";
    const m: IconMeasurement = {
      context,
      widthPx: round(rect.width),
      heightPx: round(rect.height),
      container: svg.parentElement ? describe(svg.parentElement) : "",
    };
    measurements.push(m);
    if (context === "other" || svg.closest("[data-icon-size-ok]")) return;
    if (context === "nav" && svg.closest(".nav-rail-icons")) {
      if (Math.abs(m.widthPx - small) > 0.5 || Math.abs(m.heightPx - small) > 0.5) {
        violations.push(`icon in collapsed nav link is ${m.widthPx}x${m.heightPx}px, expected ${small}px, in ${m.container}`);
      }
      return;
    }
    if (context === "nav") {
      if (m.widthPx !== m.heightPx || !Number.isInteger(m.widthPx)) {
        violations.push(`icon in nav link is ${m.widthPx}x${m.heightPx}px, expected a whole-pixel square, in ${m.container}`);
      }
      return;
    }
    const expected = context === "btn-sm" ? small : context === "badge" ? 12 : medium;
    if (Math.abs(m.widthPx - expected) > 0.5 || Math.abs(m.heightPx - expected) > 0.5) {
      violations.push(`icon in ${context} is ${m.widthPx}x${m.heightPx}px, expected ${expected}px, in ${m.container}`);
    }
  });
  return { measurements, violations };
}

/** Violations only, for Storybook play functions. */
export function iconSizeViolations(root?: Element): string[] {
  return iconSizeGeometry(root).violations;
}
