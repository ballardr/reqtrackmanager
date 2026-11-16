/**
 * Module: modules/architecture/stateShapes
 *
 * The standard geometry of a state machine diagram's items (UML state machine notation): the three marker shapes, drawn as
 * SVG the canvas shows as a marker node, and the sizes of a state and of the frame of a composite state. Pure data and
 * functions, no React.
 *
 * Responsibilities:
 * - Give the markers: the filled dot of an initial state, the ringed dot of a final state and the diamond of a choice, each
 *   with its size and its SVG markup, and the drawing each takes at any larger size while it carries a label (`labelledSvg`).
 * - `markerFrame`: the frame a marker is drawn in, which a label grows around the stored box's centre (`symbolLabelLayout`).
 * - Give the sizes a state, a composite state's header and padding and the corner radius use.
 *
 * Design decisions:
 * - The shapes are fixed standard geometry, not the symbol library. The server draws the same shapes with a Python copy
 *   (`state_shapes.py`); `stateShapeCases.json` holds the table both are tested against, so a change is made in both.
 * - A label grows the drawn symbol, not the stored box (`markerFrame`; whole words, never split), so setting or clearing one never rewrites the layout and a
 *   diagram with no labels is drawn as before; the server's `marker_frame` is the same rule.
 * - The markup uses one neutral slate that keeps at least 3:1 contrast on the light and the dark canvas, because an image
 *   drawn from a data URI cannot read the page's colour tokens.
 */

import { BASE_SIZE, fitLabel, LABEL_FONT_SIZE, LABEL_LINE_HEIGHT, MAX_SIZE, SIZE_STEP, TEXT_PERCENT } from "./symbolLabelLayout";

/** A marker kind: a state kind drawn as a shape with no text inside. */
export type StateMarkerKind = "initial" | "final" | "choice";

/** A marker's frame (a square, in canvas units) and its SVG markup. */
export interface StateMarker {
  size: number;
  svg: string;
}

/** The one colour of every marker. */
const INK = "#64748b";
const open = (size: number) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">`;

/** Each marker kind with its frame size and markup. */
export const STATE_MARKERS: Record<StateMarkerKind, StateMarker> = {
  initial: { size: 20, svg: `${open(20)}<circle cx="10" cy="10" r="9" fill="${INK}"/></svg>` },
  final: {
    size: 28,
    svg: `${open(28)}<circle cx="14" cy="14" r="12.5" fill="none" stroke="${INK}" stroke-width="2"/><circle cx="14" cy="14" r="7" fill="${INK}"/></svg>`,
  },
  choice: {
    size: 36,
    svg: `${open(36)}<polygon points="18,1 35,18 18,35 1,18" fill="none" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/></svg>`,
  },
};

/** The kinds whose label sits on the symbol's fill (an initial state's dot, a final state's inner disc); a choice's sits on the page. */
export const LABEL_ON_FILL_KINDS: ReadonlySet<StateMarkerKind> = new Set<StateMarkerKind>(["initial", "final"]);

/** The size the shared table samples each labelled drawing at besides its base size. */
const SAMPLE_SIZE = 200;

/**
 * A marker drawn at `size` (a multiple of `SIZE_STEP`) to hold a label. The initial dot is drawn larger only for a label; the
 * final ring keeps its inner disc so the text sits on the disc; the diamond is larger because only its middle holds text. Strokes
 * keep their width at every size (the same drawing as `state_shapes.labelled_svg`).
 *
 * @param kind The marker kind.
 * @param size The side of the square frame.
 * @returns The SVG markup, with a `viewBox` of `size` by `size`.
 */
export function labelledSvg(kind: StateMarkerKind, size: number): string {
  const half = size / 2;
  if (kind === "initial") return `${open(size)}<circle cx="${half}" cy="${half}" r="${half - 1}" fill="${INK}"/></svg>`;
  if (kind === "final") {
    const disc = Math.floor((26 * size + 36) / 72);
    return `${open(size)}<circle cx="${half}" cy="${half}" r="${half - 1}" fill="none" stroke="${INK}" stroke-width="2"/><circle cx="${half}" cy="${half}" r="${disc}" fill="${INK}"/></svg>`;
  }
  return `${open(size)}<polygon points="${half},1 ${size - 1},${half} ${half},${size - 1} 1,${half}" fill="none" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/></svg>`;
}

/** A box as `x`, `y`, `width`, `height`. */
export interface Frame {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * The frame a marker is drawn in: its stored box, or, when it carries a label, at least the size the label needs and centred on
 * the stored box.
 *
 * @param kind The marker kind.
 * @param box The stored box.
 * @param label The symbol's label (blank means none).
 * @returns The frame to draw and to attach lines to.
 */
export function markerFrame(kind: StateMarkerKind, box: Frame, label: string): Frame {
  const layout = fitLabel(kind, label);
  if (!layout) return box;
  const size = layout.size;
  const width = Math.max(box.width, size);
  const height = Math.max(box.height, size);
  return { x: box.x - (width - box.width) / 2, y: box.y - (height - box.height) / 2, width, height };
}

/** The size a new ordinary state is drawn at. */
export const STATE_DEFAULT_SIZE = { width: 160, height: 64 } as const;

/** The corner radius of a state (and of a composite state's frame). */
export const STATE_CORNER_RADIUS = 12;

/** A composite state's name strip across the top of its frame, and the gap its child states keep from the frame. */
export const COMPOSITE_HEADER_HEIGHT = 32;
export const COMPOSITE_PADDING = 16;

/** The table the cases file holds: every number and the markup of every marker. */
export function stateShapeTable() {
  return {
    markers: STATE_MARKERS,
    labelled_markers: Object.fromEntries((Object.keys(BASE_SIZE) as StateMarkerKind[]).map((kind) => [kind, {
      base_size: BASE_SIZE[kind], text_percent: TEXT_PERCENT[kind], on_fill: LABEL_ON_FILL_KINDS.has(kind),
      svg_at_base: labelledSvg(kind, BASE_SIZE[kind]), svg_at_sample: labelledSvg(kind, SAMPLE_SIZE),
    }])),
    label: {
      font_size: LABEL_FONT_SIZE, line_height: LABEL_LINE_HEIGHT, size_step: SIZE_STEP, max_size: MAX_SIZE, sample_size: SAMPLE_SIZE,
    },
    state: { ...STATE_DEFAULT_SIZE, corner_radius: STATE_CORNER_RADIUS },
    composite: { header_height: COMPOSITE_HEADER_HEIGHT, padding: COMPOSITE_PADDING },
  };
}
