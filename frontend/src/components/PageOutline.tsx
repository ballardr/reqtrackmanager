/**
 * Module: components/PageOutline
 *
 * A small sketch of one page: its shape (paper and orientation) and, inside it, the area the text gets once the
 * margins and the gutter are taken off, so a person sees what a margin does before printing.
 *
 * Responsibilities: draw the page and its text area to scale in a fixed box; the gutter is shaded along the binding
 * edge (the left, or the inner edge of both facing pages when margins mirror). It is decorative with an
 * accessible name; every number it draws is also in the form beside it.
 */
import { useStrings } from "../context/TerminologyContext";
import { effectiveMargins, pageDimensionsCm, type PageMargins, type PageOrientation, type PageSize } from "../utils/reportPageSetup";

const BOX_PX = 64;

/**
 * @param size Paper size.
 * @param orientation Portrait or landscape.
 * @param margins The page's margins in cm (sides left out take the default).
 * @param mirror Whether margins mirror on facing pages (the sketch then shows a facing pair).
 */
export function PageOutline({
  size, orientation, margins, mirror = false,
}: { size: PageSize; orientation: PageOrientation; margins: PageMargins; mirror?: boolean }) {
  const strings = useStrings().pageSetup;
  const [width, height] = pageDimensionsCm(size, orientation);
  const edge = effectiveMargins(margins);
  const scale = BOX_PX / Math.max(width, height);
  const page = (offset: number, verso: boolean) => {
    const inner = edge.left + edge.gutter;
    const left = mirror && verso ? edge.right : inner;
    const right = mirror && verso ? inner : edge.right;
    const textWidth = Math.max(width - left - right, 0);
    const textHeight = Math.max(height - edge.top - edge.bottom, 0);
    const gutterX = mirror && verso ? width - edge.gutter : 0;
    return (
      <g transform={`translate(${offset} 0)`} key={offset}>
        <rect width={width * scale} height={height * scale} fill="var(--color-surface)" stroke="var(--color-border)" />
        <rect x={left * scale} y={edge.top * scale} width={textWidth * scale} height={textHeight * scale} fill="var(--color-surface-alt)" stroke="var(--color-accent)" strokeDasharray="2 2" />
        {edge.gutter > 0 && (
          <rect x={gutterX * scale} y={0} width={edge.gutter * scale} height={height * scale} fill="var(--color-accent)" opacity={0.25} />
        )}
      </g>
    );
  };
  const pages = mirror ? [false, true] : [false];
  const total = pages.length * width * scale + (pages.length - 1) * 4;
  return (
    <svg role="img" aria-label={strings.sketch(size, strings.orientationLabels[orientation])} width={total} height={height * scale} style={{ flex: "none" }}>
      {pages.map((verso, index) => page(index * (width * scale + 4), verso))}
    </svg>
  );
}
