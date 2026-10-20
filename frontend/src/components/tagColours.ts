/**
 * Module: components/tagColours
 *
 * The colours a tag can be given in the tag admin, by name; the stored value is the hex code. Only the
 * tag chip's left edge uses it, so the label keeps the theme's text colour in light and dark.
 */

/** Colours a tag can take, by name; the stored value is the hex code. */
export const TAG_COLOURS: Array<{ name: string; hex: string }> = [
  { name: "Blue", hex: "#2b6cb0" },
  { name: "Green", hex: "#2f855a" },
  { name: "Amber", hex: "#b7791f" },
  { name: "Orange", hex: "#c05621" },
  { name: "Red", hex: "#c53030" },
  { name: "Purple", hex: "#6b46c1" },
  { name: "Pink", hex: "#b83280" },
  { name: "Grey", hex: "#4a5568" },
];
