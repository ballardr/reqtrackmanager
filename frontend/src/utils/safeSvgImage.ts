/**
 * Module: utils/safeSvgImage
 *
 * Turns a server-sanitised SVG drawing (an architecture symbol) into an image source that is safe to show.
 *
 * Responsibilities:
 * - Run a second DOMPurify pass (SVG profile) over the markup, as defence in depth after the server's sanitiser.
 * - Return a `data:image/svg+xml` URI, which an `<img>` draws without executing script or loading anything else,
 *   so the markup never joins the page's DOM.
 *
 * Design decisions:
 * - Markup over `MAX_SVG_CHARS`, or markup that sanitises to nothing, gives `null` and the caller draws no
 *   symbol; a hostile or broken drawing never blocks the node's text label.
 * - Results are cached per markup string, because a diagram repeats one symbol on many nodes.
 *
 * Dependencies: `dompurify`.
 */
import DOMPurify from "dompurify";

/** Upper bound on the markup accepted, matching the order of magnitude of the server's upload limit. */
export const MAX_SVG_CHARS = 262_144;

const cache = new Map<string, string | null>();
const CACHE_LIMIT = 200;

/**
 * Builds an image source from SVG markup.
 *
 * @param svg Markup the server has already sanitised.
 * @returns A `data:image/svg+xml` URI, or `null` when the markup is too large or has no drawable content.
 */
export function safeSvgImage(svg: string): string | null {
  if (svg.length > MAX_SVG_CHARS) return null;
  if (cache.has(svg)) return cache.get(svg) ?? null;
  const clean = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
  const uri = clean.includes("<svg") ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(clean)}` : null;
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(svg, uri);
  return uri;
}
