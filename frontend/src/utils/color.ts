/**
 * Small colour-contrast helpers used to apply an admin-picked accent
 * colour safely: computing readable text-on-fill contrast for buttons, and
 * deriving a theme-appropriate variant of one brand colour for light vs.
 * dark backgrounds (one colour is picked; the two on-screen tints are
 * derived, not separately chosen) — mirrors
 * `backend/app/services/branding.py`'s equivalent Python helpers.
 */

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const linearize = (channel: number) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

export function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexToRgb(hexA));
  const lumB = relativeLuminance(hexToRgb(hexB));
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Picks black or white text, whichever contrasts better against `hex`. */
export function contrastTextHex(hex: string): string {
  return contrastRatio(hex, "#ffffff") >= contrastRatio(hex, "#000000") ? "#ffffff" : "#000000";
}

function hexToHsl(hex: string): [number, number, number] {
  const [r, g, b] = hexToRgb(hex).map((c) => c / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (max === g) h = ((b - r) / d + 2) / 6;
  else h = ((r - g) / d + 4) / 6;
  return [h, s, l];
}

function hslToHex(h: number, s: number, l: number): string {
  const hueToRgb = (p: number, q: number, t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  let r: number, g: number, b: number;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hueToRgb(p, q, h + 1 / 3);
    g = hueToRgb(p, q, h);
    b = hueToRgb(p, q, h - 1 / 3);
  }
  const toHex = (c: number) =>
    Math.round(c * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

/**
 * Nudges `hex`'s lightness (in fixed steps, up to 20 tries) until it
 * contrasts with `backgroundHex` at least `minRatio`, lightening for a dark
 * background or darkening for a light one — so one admin-picked brand
 * colour can be shown as a bare link/accent colour on both a light and a
 * dark page background without picking two colours.
 */
export function ensureContrast(hex: string, backgroundHex: string, minRatio: number, lighten: boolean): string {
  const [h, s, initialL] = hexToHsl(hex);
  let l = initialL;
  for (let i = 0; i < 20; i++) {
    const candidate = hslToHex(h, s, l);
    if (contrastRatio(candidate, backgroundHex) >= minRatio) return candidate;
    l = lighten ? Math.min(1, l + 0.03) : Math.max(0, l - 0.03);
  }
  return hslToHex(h, s, lighten ? 1 : 0);
}

/**
 * A visibly different hover shade of a solid button's fill colour, shifted
 * the same direction its own contrast text was picked for (dark text needs
 * a *lighter* hover; light text needs a *darker* one) so the button never
 * hovers towards its own text colour and loses contrast.
 */
export function hoverShade(hex: string): string {
  const [h, s, l] = hexToHsl(hex);
  const towardsLight = contrastTextHex(hex) === "#000000";
  const delta = 0.1;
  const newL = towardsLight ? Math.max(0, l - delta) : Math.min(1, l + delta);
  return hslToHex(h, s, newL);
}
