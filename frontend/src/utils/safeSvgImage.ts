/**
 * Module: utils/safeSvgImage
 *
 * Turns a server-sanitised SVG drawing (an architecture symbol) into an image source that is safe to show.
 *
 * Responsibilities: run a second DOMPurify pass (SVG profile) as defence in depth after the server's sanitiser, and
 * return a `data:image/svg+xml` URI, which an `<img>` draws without running script or loading anything else.
 *
 * Design decisions:
 * - Markup over `MAX_SVG_CHARS`, or that sanitises to nothing, gives `null`, so a hostile or broken drawing never
 *   blocks the node's text label.
 * - Results are cached per markup string, because a diagram repeats one symbol on many nodes.
 * - A caller's `trustedStyle` (constant CSS such as an embedded font) is added after sanitising and never read from
 *   the markup.
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
 * @param trustedStyle Optional CSS the caller wrote itself, added as a `<style>` element after sanitising.
 * @returns A `data:image/svg+xml` URI, or `null` when the markup is too large or has no drawable content.
 */
export function safeSvgImage(svg: string, trustedStyle = ""): string | null {
  if (svg.length > MAX_SVG_CHARS) return null;
  const key = trustedStyle ? `${trustedStyle.length}:${svg}` : svg;
  if (cache.has(key)) return cache.get(key) ?? null;
  let clean = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
  if (trustedStyle) clean = clean.replace(/<svg\b[^>]*>/, (open) => `${open}<style>${trustedStyle}</style>`);
  const uri = clean.includes("<svg") ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(clean)}` : null;
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(key, uri);
  return uri;
}
