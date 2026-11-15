/**
 * Module: modules/architecture/stateShapes
 *
 * The standard geometry of a state machine diagram's items (UML state machine notation): the three marker shapes, drawn as
 * SVG the canvas shows as a marker node, and the sizes of a state and of the frame of a composite state. Pure data and
 * functions, no React.
 *
 * Responsibilities:
 * - Give the markers: the filled dot of an initial state, the ringed dot of a final state and the diamond of a choice, each
 *   with its size and its SVG markup, and the larger form each takes while it carries a label (`LABELLED_MARKERS`).
 * - `markerFrame`: the frame a marker is drawn in, which a label grows around the stored box's centre.
 * - Give the sizes a state, a composite state's header and padding and the corner radius use.
 *
 * Design decisions:
 * - The shapes are fixed standard geometry, not the symbol library. The server draws the same shapes with a Python copy
 *   (`state_shapes.py`); `stateShapeCases.json` holds the table both are tested against, so a change is made in both.
 * - A label grows the drawn symbol, not the stored box (`markerFrame`), so setting or clearing one never rewrites the layout and a
 *   diagram with no labels is drawn as before; the server's `marker_frame` is the same rule.
 * - The markup uses one neutral slate that keeps at least 3:1 contrast on the light and the dark canvas, because an image
 *   drawn from a data URI cannot read the page's colour tokens.
 */

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

/** A marker's larger form for a label: its frame, markup, the width its text may use and whether the text sits on the fill. */
export interface LabelledMarker extends StateMarker {
  textWidth: number;
  onFill: boolean;
}

/** Each marker kind's larger form (see `state_shapes.LABELLED_MARKERS`). */
export const LABELLED_MARKERS: Record<StateMarkerKind, LabelledMarker> = {
  initial: { size: 52, svg: `${open(52)}<circle cx="26" cy="26" r="25" fill="${INK}"/></svg>`, textWidth: 36, onFill: true },
  final: {
    size: 72,
    svg: `${open(72)}<circle cx="36" cy="36" r="34" fill="none" stroke="${INK}" stroke-width="2"/><circle cx="36" cy="36" r="26" fill="${INK}"/></svg>`,
    textWidth: 38, onFill: true,
  },
  choice: {
    size: 96,
    svg: `${open(96)}<polygon points="48,1 95,48 48,95 1,48" fill="none" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/></svg>`,
    textWidth: 48, onFill: false,
  },
};

/** The lines a symbol's label may take, and its font size and line height (canvas units). */
export const LABEL_METRICS = { max_lines: 3, font_size: 10, line_height: 12 } as const;

/** A box as `x`, `y`, `width`, `height`. */
export interface Frame {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * The frame a marker is drawn in: its stored box, or, when it carries a label, at least the labelled size and centred on the
 * stored box.
 *
 * @param kind The marker kind.
 * @param box The stored box.
 * @param label The symbol's label (blank means none).
 * @returns The frame to draw and to attach lines to.
 */
export function markerFrame(kind: StateMarkerKind, box: Frame, label: string): Frame {
  if (!label.trim()) return box;
  const size = LABELLED_MARKERS[kind].size;
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
    labelled_markers: Object.fromEntries(Object.entries(LABELLED_MARKERS).map(([kind, m]) => [
      kind, { size: m.size, svg: m.svg, text_width: m.textWidth, on_fill: m.onFill },
    ])),
    label: LABEL_METRICS,
    state: { ...STATE_DEFAULT_SIZE, corner_radius: STATE_CORNER_RADIUS },
    composite: { header_height: COMPOSITE_HEADER_HEIGHT, padding: COMPOSITE_PADDING },
  };
}
