/**
 * Module: hooks/useInitialSearchParams
 *
 * The URL's query parameters as they were when the page mounted, for pages
 * whose filters can be pre-set by a link (a report figure that opens "the
 * Blockers", say). Read once, to seed the page's own filter state: the page
 * stays the source of truth afterwards, so changing a filter never rewrites
 * the URL or re-triggers the seed, and the filters stay ordinary visible
 * controls the user can change or clear.
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * @returns A snapshot of the query parameters at mount.
 */
export function useInitialSearchParams(): URLSearchParams {
  const [searchParams] = useSearchParams();
  const [initial] = useState(() => new URLSearchParams(searchParams));
  return initial;
}

/**
 * Narrows a URL value to a known option.
 *
 * @param value The raw parameter (or `null`).
 * @param allowed The accepted values.
 * @returns The value when it is one of `allowed`, else the empty string (no filter).
 */
export function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | "" {
  return allowed.includes(value as T) ? (value as T) : "";
}
