/**
 * Module: utils/localDate
 *
 * The viewer's calendar day. A date a person types or sees ("today") is their local day, which differs
 * from the UTC day for part of every day outside UTC; `localToday()` is the one place that is worked out
 * (the API client sends it as `X-Client-Date` so the server's "has this happened yet" rules agree with it).
 */

/** Today as `YYYY-MM-DD` in the viewer's timezone. */
export function localToday(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}
