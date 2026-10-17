import type { BadgeTone } from "../api/types";

/**
 * Class names for a pill, shared with the few pills that must be a different element
 * (`FilterBadge` is a `<button>`).
 *
 * @param tone Status colour; omit for the neutral outline.
 * @param className Extra classes to append.
 * @returns The `badge badge--<tone>` class string.
 */
export function badgeClassName(tone?: BadgeTone, className?: string): string {
  return ["badge", tone ? `badge--${tone}` : "", className ?? ""].filter(Boolean).join(" ");
}
