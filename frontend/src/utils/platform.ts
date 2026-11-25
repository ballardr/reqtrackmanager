/**
 * Module: utils/platform
 *
 * Which keyboard convention the person's device follows, for shortcut handling
 * and tooltip shortcut text: whether it is an Apple device (Command is the
 * modifier) or not (Control), and the modifier's display name.
 * Design: read from the browser on each call, never cached at import, so a story
 * or test can change it (the check also takes the platform as an optional
 * argument). `userAgentData.platform` is preferred; `navigator.platform` and the
 * user agent are fallbacks, since neither is guaranteed.
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
