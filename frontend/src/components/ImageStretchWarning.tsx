/**
 * Module: components/ImageStretchWarning
 *
 * A note under an image block's size fields when Width and Height are both set to a ratio unlike the picture's, so the
 * picture would print stretched. A warning, not an error: stretching is the author's choice.
 *
 * Responsibilities:
 * - Read the picture's pixel size from the library and compare it with the block's size (`utils/imageStretch`).
 * - Say nothing while the size is unknown (reading, an SVG, a failed read) or the ratios agree.
 */
import type { ReportImageLibrary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { useFileDetails } from "../hooks/useFileDetails";
import { stretchOf } from "../utils/imageStretch";

/**
 * @param node The image block being edited.
 * @param library The picture library, which reads the picture's details.
 */
export function ImageStretchWarning({ node, library }: { node: Record<string, unknown>; library: ReportImageLibrary }) {
  const text = useStrings().reportOutline;
  const file = typeof node.file === "string" && node.file !== "" ? node.file : null;
  const details = useFileDetails(file, library.details);
  if (details === undefined || details === "failed") return null;
  const stretch = stretchOf(node, details.width_px, details.height_px);
  if (stretch === null) return null;
  return <p className="text-muted" role="status" style={{ margin: 0 }}>{text.imageStretched(stretch.chosen, stretch.picture)}</p>;
}
