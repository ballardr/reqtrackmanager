/**
 * Module: utils/mermaidRender
 *
 * Draws Mermaid diagram text as an image source for `MermaidDiagram`, on demand and within fixed limits.
 *
 * Responsibilities:
 * - Load the Mermaid library on first use only (a dynamic import), so no page that shows no diagram pays for it.
 * - Draw in strict mode with SVG text labels, the shared font (DejaVu Sans, a local file) and the limits in
 *   `mermaidRenderConfig.json` (source size, edges, drawn elements, time).
 * - Return the drawing as a `data:image/svg+xml` image through `safeSvgImage`, so script in a diagram can never run.
 *
 * Design decisions:
 * - One engine version, one font and one set of limits are the contract with the server's renderer (reports), so a
 *   diagram reads the same on screen and in a document. The version is the `mermaid` pin in package.json and is
 *   repeated in the JSON file, where a story keeps the two equal.
 * - An image cannot use the page's fonts, so the font is also embedded in the drawing (a trusted `@font-face`
 *   added after sanitising); the same font is registered on the page first, so Mermaid measures the text it
 *   will draw with.
 * - Mermaid keeps global state, so drawings run one at a time. A drawing that takes too long is abandoned for the
 *   caller (a library call cannot be cancelled) and the next one is not blocked behind it.
 * - Results are cached per source and theme, because a list or a re-render repeats the same diagram.
 *
 * Dependencies: `mermaid` (MIT), `utils/safeSvgImage`, the font in `assets/fonts/` (licence beside it).
 */
import fontUrl from "../assets/fonts/DejaVuSans-diagram.woff2?url";
import config from "./mermaidRenderConfig.json";
import { safeSvgImage } from "./safeSvgImage";

export type DiagramTheme = "light" | "dark";

/** A drawn diagram: the image source and its natural size in pixels. */
export interface RenderedDiagram {
  src: string;
  width: number;
  height: number;
}

/** A diagram that cannot be drawn: invalid text, over a limit, out of time. The message is safe to show. */
export class DiagramError extends Error {}

/** The Mermaid version the application draws with. */
export const MERMAID_VERSION: string = config.version;
/** The limits a diagram is drawn within (the server applies the same ones). */
export const DIAGRAM_LIMITS = config.limits;
export const DIAGRAM_FONT_FAMILY: string = config.fontFamily;

const cache = new Map<string, RenderedDiagram>();
const CACHE_LIMIT = 100;

let fontStyle: Promise<string> | null = null;
let queue: Promise<unknown> = Promise.resolve();
let counter = 0;

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** Registers the font on the page and returns the CSS that embeds it in a drawing ("" when it cannot be loaded). */
function loadFont(): Promise<string> {
  fontStyle ??= (async () => {
    try {
      const buffer = await (await fetch(fontUrl)).arrayBuffer();
      const face = new FontFace(config.fontFamily, buffer);
      document.fonts.add(await face.load());
      return `@font-face{font-family:"${config.fontFamily}";src:url(data:font/woff2;base64,${toBase64(buffer)}) format("woff2")}`;
    } catch {
      return ""; // drawn with the fallback font rather than not at all
    }
  })();
  return fontStyle;
}

/** The size from the drawing's `viewBox`, or a default when it has none. */
function sizeOf(svg: string): { width: number; height: number } {
  const match = svg.match(/viewBox="[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)"/);
  return match ? { width: Math.ceil(Number(match[1])), height: Math.ceil(Number(match[2])) } : { width: 300, height: 150 };
}

async function draw(source: string, theme: DiagramTheme): Promise<RenderedDiagram> {
  const [{ default: mermaid }, style] = await Promise.all([import("mermaid"), loadFont()]);
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: theme === "dark" ? "dark" : "default",
    fontFamily: `"${config.fontFamily}"`,
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    maxTextSize: config.limits.sourceChars,
    maxEdges: config.limits.edges,
    suppressErrorRendering: true,
  });
  const id = `diagram-${++counter}`;
  let svg: string;
  try {
    ({ svg } = await mermaid.render(id, source));
  } catch (error) {
    throw new DiagramError(String((error as Error)?.message ?? error).split("\n").slice(0, 3).join(" ").slice(0, 300));
  } finally {
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  }
  if ((svg.match(/<[a-zA-Z]/g) ?? []).length > config.limits.elements) throw new DiagramError("The diagram is too large to draw.");
  const src = safeSvgImage(svg, style);
  if (src === null) throw new DiagramError("The diagram is too large to draw.");
  return { src, ...sizeOf(svg) };
}

/**
 * Draws diagram text.
 *
 * @param source The Mermaid text.
 * @param theme The page's colour theme; the diagram is drawn for it.
 * @returns The image source and size.
 * @throws DiagramError When the text is empty, too long, invalid, too large to draw or takes too long.
 */
export function renderDiagram(source: string, theme: DiagramTheme): Promise<RenderedDiagram> {
  const text = source.trim();
  if (text === "") return Promise.reject(new DiagramError("The diagram is empty."));
  if (text.length > config.limits.sourceChars) {
    return Promise.reject(new DiagramError(`The diagram text is over the limit of ${config.limits.sourceChars} characters.`));
  }
  const key = `${theme}\n${text}`;
  const hit = cache.get(key);
  if (hit) return Promise.resolve(hit);
  const job = queue.then(() => draw(text, theme));
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new DiagramError("The diagram took too long to draw.")), config.limits.renderMilliseconds);
  });
  const result = Promise.race([job, timeout]).finally(() => clearTimeout(timer));
  queue = result.catch(() => undefined);
  return result.then((drawn) => {
    if (cache.size >= CACHE_LIMIT) cache.clear();
    cache.set(key, drawn);
    return drawn;
  });
}
