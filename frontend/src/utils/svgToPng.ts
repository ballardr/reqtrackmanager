/**
 * Module: utils/svgToPng
 *
 * Rasterises an SVG document to a PNG in the browser, for exports that offer a picture as well as the vector file.
 *
 * Responsibilities:
 * - Read the document's size, draw it on an off-screen canvas over a white background and encode the canvas as PNG.
 *
 * Design decisions:
 * - The SVG is loaded as an image from a Blob URL, never inserted into the page, so nothing in it can run script or reach
 *   the page's DOM; a browser draws an SVG image without running its script.
 * - The pixel size is capped so a very large diagram cannot exhaust memory; the scale drops to fit instead of failing.
 * - The background is opaque white because a transparent PNG of dark-on-light artwork is unreadable on a dark viewer.
 */

/** The longest side of the PNG, in pixels. */
export const MAX_PNG_SIDE = 8192;

/**
 * The size an SVG document declares: its `width` and `height`, else its `viewBox`.
 *
 * @param svg The SVG document text.
 * @returns The width and height, or null when the document declares neither.
 */
export function svgSize(svg: string): { width: number; height: number } | null {
  const root = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement;
  if (!root || root.nodeName.toLowerCase() !== "svg") return null;
  const width = parseFloat(root.getAttribute("width") ?? "");
  const height = parseFloat(root.getAttribute("height") ?? "");
  if (width > 0 && height > 0) return { width, height };
  const box = (root.getAttribute("viewBox") ?? "").trim().split(/[\s,]+/).map(Number);
  return box.length === 4 && box[2] > 0 && box[3] > 0 ? { width: box[2], height: box[3] } : null;
}

/**
 * Draws an SVG document as a PNG.
 *
 * @param svg The SVG document text.
 * @param scale Pixels per SVG unit (2 gives a sharp image on a high-density screen); lowered when the result would pass
 *   `MAX_PNG_SIDE`.
 * @returns The PNG file.
 * @throws Error When the document has no size or the browser cannot draw it.
 */
export async function svgToPngBlob(svg: string, scale = 2): Promise<Blob> {
  const size = svgSize(svg);
  if (!size) throw new Error("The diagram has no size to draw.");
  const factor = Math.min(scale, MAX_PNG_SIDE / Math.max(size.width, size.height));
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("The diagram could not be drawn as an image."));
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(size.width * factor));
    canvas.height = Math.max(1, Math.round(size.height * factor));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("The diagram could not be drawn as an image.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("The image could not be created."))), "image/png");
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
