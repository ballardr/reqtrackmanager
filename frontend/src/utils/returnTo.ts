/**
 * Module: utils/returnTo
 *
 * Remembers the page a person was on when the application sent them to sign in, so signing in returns them there.
 *
 * Responsibilities: validate a candidate path (`normaliseReturnTo`: same-origin, relative, never an authentication
 * page) and keep one path across a reload, the single sign-on redirect and the two-factor step.
 *
 * Design decisions:
 * - Stored in `sessionStorage`, with an in-memory fallback when storage is blocked.
 * - The stored value is validated again on every read, because anything in the tab can write `sessionStorage` and the
 *   value becomes a navigation target (open redirect). `takeReturnTo` removes it, so it is used once.
 *
 * External dependencies: none (browser `URL` and `sessionStorage`).
 */

const STORAGE_KEY = "reqtrack:return-to";
const MAX_LENGTH = 2048;

/** Pages shown to a person who is not signed in; returning to one of them after signing in would be a loop or a dead end. */
const AUTHENTICATION_PATHS = ["/login", "/signup", "/forgot-password", "/reset-password", "/confirm-email", "/oidc-complete"];

let memoryFallback: string | null = null;

/**
 * Validates a candidate return path and returns it in canonical form.
 *
 * Args:
 *     raw: Any value; only a string that is a path on this origin is accepted.
 *
 * Returns:
 *     The path with its query and hash (`/projects/1/requirements?status=open#top`), or null when the value is absent,
 *     not a string, longer than 2048 characters, contains a control character or a backslash, resolves to another
 *     origin (`//host`, `/\host`, `https://host`), is the application root, or is an authentication page.
 */
export function normaliseReturnTo(raw: unknown): string | null {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > MAX_LENGTH) return null;
  // A browser strips tabs and newlines from a URL and reads a backslash as a slash, so each of these can turn a
  // path that looks local into `//host`.
  for (const char of raw) {
    const code = char.codePointAt(0) ?? 0;
    if (code <= 0x1f || code === 0x7f || char === "\\") return null;
  }
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  let url: URL;
  try {
    url = new URL(raw, window.location.origin);
  } catch {
    return null;
  }
  if (url.origin !== window.location.origin) return null;
  const pathname = url.pathname;
  if (pathname === "/") return null;
  const lowered = pathname.toLowerCase();
  if (AUTHENTICATION_PATHS.some((p) => lowered === p || lowered.startsWith(`${p}/`))) return null;
  return pathname + url.search + url.hash;
}

/**
 * Remembers a path for the next sign-in, replacing any earlier one.
 *
 * Args:
 *     path: The page to return to; an invalid path is ignored (the earlier one is kept).
 *
 * Side effects:
 *     Writes `sessionStorage` (or the in-memory fallback when storage is unavailable).
 */
export function rememberReturnTo(path: string): void {
  const valid = normaliseReturnTo(path);
  if (!valid) return;
  memoryFallback = valid;
  try {
    sessionStorage.setItem(STORAGE_KEY, valid);
  } catch {
    // Storage blocked: the in-memory copy above is used instead.
  }
}

/**
 * Reads the remembered path without removing it.
 *
 * Returns:
 *     The validated path, or null when there is none or the stored value fails validation.
 */
export function peekReturnTo(): string | null {
  let stored: string | null = null;
  try {
    stored = sessionStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage blocked: fall back to memory.
  }
  return normaliseReturnTo(stored ?? memoryFallback);
}

/**
 * Forgets the remembered path (an explicit sign-out, or a path that has been used).
 *
 * Side effects:
 *     Removes the `sessionStorage` entry and the in-memory copy.
 */
export function clearReturnTo(): void {
  memoryFallback = null;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage blocked: nothing stored.
  }
}

/**
 * Reads the remembered path and removes it, so it is used for one sign-in only.
 *
 * Returns:
 *     The validated path, or null when there is none.
 */
export function takeReturnTo(): string | null {
  const path = peekReturnTo();
  clearReturnTo();
  return path;
}
