/**
 * Module: utils/reportColours
 *
 * Colour words for report layouts, as the designer reads them: the same vocabulary the server resolves
 * (`backend/app/services/report_colours.py`), so a swatch shows the colour the report will print.
 *
 * Responsibilities:
 * - Name the reserved words and the standard scheme names; resolve any colour word to a `#rrggbb` for display.
 * - Build the choices a colour field offers (branding colour, the layout's scheme, the organisation's, white, black, none).
 * - Find the scheme names a tree uses, so a name still in use cannot be removed from the scheme.
 *
 * Design decisions: display only. The server is the judge of what is valid and the only thing that writes a colour into
 * a document; this module never validates for saving. A colour is stored by name, so a swatch resolves through the
 * scheme as the server will (layout, then organisation, then the standard four).
 */
import type { BlockCatalogue } from "../api/reportLayouts";
import type { TreeNode } from "./reportLayoutTree";
import { normaliseHexColour } from "./color";

/** One named colour of a scheme: the name and the colour word it stands for (a hex colour or a derived/reserved word). */
export interface ColourEntry {
  name: string;
  colour: string;
}

/** What the designer knows about the organisation's colours (`GET .../report-layouts/colours`). */
export interface ColourContext {
  /** The organisation's report accent, `#rrggbb`. */
  accent: string;
  organization_scheme: ColourEntry[];
  /** The four standard names and the word each stands for. */
  standard: ColourEntry[];
}

/** Reserved words, in the order the choices list them (after the branding colour itself). */
export const RESERVED_COLOUR_WORDS = ["accent", "accent_light", "accent_dark", "white", "black", "none"] as const;
export const MAX_SCHEME_COLOURS = 8;

/** Used when the designer was given no context (a story, or an older server): the platform's slate and the standard four. */
export const DEFAULT_COLOUR_CONTEXT: ColourContext = {
  accent: "#475569",
  organization_scheme: [],
  standard: [
    { name: "primary", colour: "accent" }, { name: "secondary", colour: "accent_dark" },
    { name: "tint", colour: "accent_light" }, { name: "neutral", colour: "#6b7280" },
  ],
};

const TINT_TOWARDS_WHITE = 0.85;
const SHADE_TOWARDS_BLACK = 0.25;

function mix(hex: string, target: number, share: number): string {
  const digits = hex.slice(1);
  const channels = [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16));
  return `#${channels.map((c) => Math.round(c + (target - c) * share).toString(16).padStart(2, "0")).join("")}`;
}

/** Whether `word` has the shape of a scheme name (it may still be unknown). */
export function isColourName(word: string): boolean {
  return /^[a-z][a-z0-9_]{0,23}$/.test(word) && !(RESERVED_COLOUR_WORDS as readonly string[]).includes(word);
}

/**
 * The names a layout resolves by: the standard four, then the organisation's, then the layout's own (a later source wins).
 */
export function effectiveScheme(context: ColourContext, layoutPalette: ColourEntry[]): Map<string, string> {
  const scheme = new Map<string, string>();
  for (const entry of [...context.standard, ...context.organization_scheme, ...layoutPalette]) scheme.set(entry.name, entry.colour);
  return scheme;
}

/**
 * A colour word as `#rrggbb`, or `null` for `none` (and for text that is not a colour).
 *
 * @param word A hex colour, a reserved word or a scheme name.
 * @param context The branding colour and the organisation's scheme.
 * @param layoutPalette The layout's own scheme.
 */
export function resolveColourWord(word: string, context: ColourContext, layoutPalette: ColourEntry[] = []): string | null {
  const accent = normaliseHexColour(context.accent) ?? "#475569";
  const reserved = (w: string): string | null | undefined => {
    switch (w) {
      case "accent": return accent;
      case "accent_light": return mix(accent, 255, TINT_TOWARDS_WHITE);
      case "accent_dark": return mix(accent, 0, SHADE_TOWARDS_BLACK);
      case "white": return "#ffffff";
      case "black": return "#000000";
      case "none": return null;
      default: return undefined;
    }
  };
  const direct = reserved(word);
  if (direct !== undefined) return direct;
  const hex = normaliseHexColour(word);
  if (hex) return hex;
  const target = effectiveScheme(context, layoutPalette).get(word);
  if (target === undefined) return accent;
  return reserved(target) ?? normaliseHexColour(target) ?? accent;
}

/** One line of the colour list a field offers. */
export interface ColourChoice {
  /** The word stored in the tree. */
  word: string;
  /** What the line says, never the colour alone. */
  label: string;
  /** Which part of the list it belongs to, for the grouping headings. */
  group: "branding" | "scheme" | "organisation" | "standard" | "fixed";
}

/**
 * The named choices a colour field lists, in order: the branding colour, the layout's scheme, the organisation's scheme names the
 * layout does not override, the standard four it does not redefine, then the fixed words.
 *
 * @param labels The words for the branding colour and the fixed ones.
 * @param allowNone Whether "no colour" is offered.
 * @param allowNames Whether scheme names are offered (a scheme entry itself points at a colour, never at a name).
 */
export function colourChoices(
  context: ColourContext, layoutPalette: ColourEntry[],
  labels: { accent: string; light: string; dark: string; white: string; black: string; none: string },
  { allowNone, allowNames }: { allowNone: boolean; allowNames: boolean },
): ColourChoice[] {
  const choices: ColourChoice[] = [{ word: "accent", label: labels.accent, group: "branding" }];
  if (allowNames) {
    const own = new Set(layoutPalette.map((e) => e.name));
    const organisation = context.organization_scheme.filter((e) => !own.has(e.name));
    const taken = new Set([...own, ...organisation.map((e) => e.name)]);
    choices.push(
      ...layoutPalette.map((e) => ({ word: e.name, label: e.name, group: "scheme" as const })),
      ...organisation.map((e) => ({ word: e.name, label: e.name, group: "organisation" as const })),
      ...context.standard.filter((e) => !taken.has(e.name)).map((e) => ({ word: e.name, label: e.name, group: "standard" as const })),
    );
  }
  choices.push(
    { word: "accent_light", label: labels.light, group: "fixed" }, { word: "accent_dark", label: labels.dark, group: "fixed" },
    { word: "white", label: labels.white, group: "fixed" }, { word: "black", label: labels.black, group: "fixed" },
  );
  if (allowNone) choices.push({ word: "none", label: labels.none, group: "fixed" });
  return choices;
}

/** The label a colour word is shown under: its name or a reserved word's label, else the hex itself. */
export function colourWordLabel(word: string, labels: Record<string, string>): string {
  return labels[word] ?? word;
}

/**
 * The scheme names the blocks of `tree` use, through every block field the server declares as a colour.
 *
 * @param tree The layout.
 * @param blocks The block catalogue (which fields of which blocks are colours).
 */
export function colourNamesUsed(tree: TreeNode, blocks: BlockCatalogue): Set<string> {
  const colourKeys = new Map(blocks.blocks.map((b) => [b.type, b.fields.filter((f) => f.kind === "colour").map((f) => f.key)]));
  const used = new Set<string>();
  const visit = (nodes: unknown) => {
    if (!Array.isArray(nodes)) return;
    for (const node of nodes as TreeNode[]) {
      for (const key of colourKeys.get(String(node.type)) ?? []) {
        const word = node[key];
        if (typeof word === "string" && isColourName(word)) used.add(word);
      }
      visit(node.children);
      visit(node.else_children);
    }
  };
  visit(tree.nodes);
  return used;
}

/** Fixed starting points for a layout's scheme (a one-shot fill the author then edits). */
export const SCHEME_STARTS: Record<string, ColourEntry[]> = {
  branding: [
    { name: "primary", colour: "accent" }, { name: "secondary", colour: "accent_dark" },
    { name: "tint", colour: "accent_light" }, { name: "neutral", colour: "#6b7280" },
  ],
  monochrome: [
    { name: "primary", colour: "#111827" }, { name: "secondary", colour: "#4b5563" },
    { name: "tint", colour: "#e5e7eb" }, { name: "neutral", colour: "#9ca3af" },
  ],
  cool: [
    { name: "primary", colour: "#1d4ed8" }, { name: "secondary", colour: "#0f766e" },
    { name: "tint", colour: "#dbeafe" }, { name: "neutral", colour: "#64748b" },
  ],
  warm: [
    { name: "primary", colour: "#b45309" }, { name: "secondary", colour: "#9f1239" },
    { name: "tint", colour: "#fef3c7" }, { name: "neutral", colour: "#78716c" },
  ],
};

/** The first name `base1`, `base2` ... not in `taken`. */
export function freshColourName(taken: Iterable<string>, base = "colour"): string {
  const used = new Set(taken);
  for (let i = 1; ; i += 1) if (!used.has(`${base}${i}`)) return `${base}${i}`;
}
