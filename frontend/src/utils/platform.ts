/**
 * Module: utils/platform
 *
 * Which keyboard convention the person's device follows, for shortcut handling and the shortcut text a tooltip shows.
 *
 * Responsibilities:
 * - Report whether the device is an Apple one (Command is the shortcut modifier) or not (Control is).
 * - Name the shortcut modifier for display.
 *
 * Design decisions:
 * - Read from the browser each call, never cached at import, so a story or test can change it; the check takes the platform
 *   as an optional argument for the same reason.
 * - `userAgentData.platform` is preferred where the browser offers it; `navigator.platform` and the user agent are the
 *   fallbacks, since neither is guaranteed.
 */

/** The parts of `navigator` this module reads (a test supplies its own). */
export interface PlatformSource {
  userAgentData?: { platform?: string };
  platform?: string;
  userAgent?: string;
}

/**
 * @param source The navigator to read; defaults to the browser's own.
 * @returns True on macOS, iOS and iPadOS, where Command rather than Control is the shortcut modifier.
 */
export function isApplePlatform(source: PlatformSource | undefined = typeof navigator === "undefined" ? undefined : navigator): boolean {
  if (!source) return false;
  const name = source.userAgentData?.platform || source.platform || source.userAgent || "";
  return /mac|iphone|ipad|ipod/i.test(name);
}

/**
 * @param apple Whether the device is an Apple one; defaults to the browser's own platform.
 * @returns The shortcut modifier's name as a person reads it: `Cmd` or `Ctrl`.
 */
export function shortcutModifierLabel(apple: boolean = isApplePlatform()): string {
  return apple ? "Cmd" : "Ctrl";
}
