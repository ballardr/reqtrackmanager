/**
 * Module: modules/architecture/stateShapes
 *
 * The standard geometry of a state machine diagram's items (UML state machine notation): the three marker shapes, drawn as
 * SVG the canvas shows as a marker node, and the sizes of a state and of the frame of a composite state. Pure data and
 * functions, no React.
 *
 * Responsibilities:
 * - Give the markers: the filled dot of an initial state, the ringed dot of a final state and the diamond of a choice, each
 *   with its size and its SVG markup.
 * - Give the sizes a state, a composite state's header and padding and the corner radius use.
 *
 * Design decisions:
 * - The shapes are fixed standard geometry, not the symbol library. The server draws the same shapes with a Python copy
 *   (`state_shapes.py`); `stateShapeCases.json` holds the table both are tested against, so a change is made in both.
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
    state: { ...STATE_DEFAULT_SIZE, corner_radius: STATE_CORNER_RADIUS },
    composite: { header_height: COMPOSITE_HEADER_HEIGHT, padding: COMPOSITE_PADDING },
  };
}
