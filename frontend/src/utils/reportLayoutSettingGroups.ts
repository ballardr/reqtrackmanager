/**
 * Module: utils/reportLayoutSettingGroups
 *
 * The one arrangement of a layout's own settings, shared by the Blocks view's layout panel and the text view's
 * page setup dialog.
 *
 * Responsibilities:
 * - `LAYOUT_SETTING_GROUPS`: the groups, their order and whether each starts open; `groupOfField` places a layout
 *   field (by key) in one, with an "other" group for a field this table does not know yet so a field added on the
 *   server is never lost.
 * - `treeSettingChanges` / `pageSetupChanges`: how many settings in each group differ from their defaults, read from
 *   the tree or from the page setup of the text, so a closed group can say it is not plain.
 * - `layoutGroupSummary`: the pill text for a closed group ("2 changed"; "3 page styles" for a list).
 * - `pageGroupSummary` / `marginsGroupSummary`: the effective value of the Page and Margins groups ("A4 portrait";
 *   "1.5 cm"), which always have one, so their bars say it in place of a count.
 *
 * Design decisions: arrangement only. Nothing here changes what is stored or the text view's syntax. The server's
 * field catalogue stays the source of which settings exist; this table only says where each one sits.
 */
import type { BlockField } from "../api/reportLayouts";
import { effectiveMargins, type PageMargins, type PageOrientation, type PageSetup, type PageSize } from "./reportPageSetup";
import type { Tree } from "./reportLayoutTree";

export const LAYOUT_SETTING_GROUP_KEYS = ["page", "margins", "header", "footer", "look", "variables", "tables", "styles", "other"] as const;
export type LayoutSettingGroupKey = (typeof LAYOUT_SETTING_GROUP_KEYS)[number];

/**
 * The groups in the order they are drawn. Every group is collapsible and starts closed (the settings are mostly set once
 * and forgotten); `opensOnNewLayout` groups, the page size and margins, start open on a layout that has not been
 * published beyond its first version so its first setup is not hidden.
 */
export const LAYOUT_SETTING_GROUPS: readonly { key: LayoutSettingGroupKey; opensOnNewLayout: boolean }[] = [
  { key: "page", opensOnNewLayout: true },
  { key: "margins", opensOnNewLayout: true },
  { key: "header", opensOnNewLayout: false },
  { key: "footer", opensOnNewLayout: false },
  { key: "look", opensOnNewLayout: false },
  { key: "variables", opensOnNewLayout: false },
  { key: "tables", opensOnNewLayout: false },
  { key: "styles", opensOnNewLayout: false },
  { key: "other", opensOnNewLayout: false },
];

const GROUP_OF_FIELD: Record<string, LayoutSettingGroupKey> = {
  orientation: "page", page_size: "page", mirror_margins: "page",
  margins: "margins",
  header: "header", footer: "footer",
  palette: "look", styles: "look", embed_fonts: "look", table_header_fill: "look", table_header_text: "look",
  run_scope: "variables", file_name: "variables", variables: "variables",
  repeat_table_header: "tables", align_tables: "tables", contents_sheet: "tables",
  page_styles: "styles",
};

/** The group a layout field sits in; a key this table does not list goes to "other". */
export function groupOfField(key: string): LayoutSettingGroupKey {
  return GROUP_OF_FIELD[key] ?? "other";
}

/** The fields split into the non-empty groups, in drawing order. */
export function groupLayoutFields(fields: readonly BlockField[]): { key: LayoutSettingGroupKey; fields: BlockField[] }[] {
  return LAYOUT_SETTING_GROUPS
    .map((group) => ({ key: group.key, fields: fields.filter((f) => groupOfField(f.key) === group.key) }))
    .filter((group) => group.fields.length > 0);
}

/** Whether a stored value differs from what the layout or block does without it. */
export function settingIsSet(field: BlockField, value: unknown): boolean {
  if (value === undefined || value === null) return false;
  // A band of `{}` is a choice: it prints nothing.
  if (field.kind === "running_band") return true;
  if (typeof value === "string") return value !== "" && value !== field.default;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return value !== field.default;
}

/** How many settings of each group the tree sets away from their default. */
export function treeSettingChanges(tree: Tree, fields: readonly BlockField[]): Partial<Record<LayoutSettingGroupKey, number>> {
  const counts: Partial<Record<LayoutSettingGroupKey, number>> = {};
  for (const field of fields) {
    if (!settingIsSet(field, tree[field.key])) continue;
    const group = groupOfField(field.key);
    // A list of page styles counts its items, so the pill reads as a noun count.
    counts[group] = (counts[group] ?? 0) + (field.key === "page_styles" ? (tree[field.key] as unknown[]).length : 1);
  }
  return counts;
}

/** How many settings of each group a page setup (read from the text) sets away from their default. */
export function pageSetupChanges(setup: PageSetup): Partial<Record<LayoutSettingGroupKey, number>> {
  const count = (flags: boolean[]) => flags.filter(Boolean).length;
  const counts = {
    page: count([setup.orientation !== "portrait", setup.size !== "A4", setup.mirror]),
    margins: count([Object.keys(setup.margins).length > 0]),
    look: count([setup.tableHeadings?.fill !== undefined, setup.tableHeadings?.text !== undefined]),
    header: count([setup.header !== undefined]),
    footer: count([setup.footer !== undefined]),
    tables: count([setup.repeatHeader === false, setup.alignTables === false]),
    styles: setup.styles.length,
  };
  return Object.fromEntries(Object.entries(counts).filter(([, n]) => n > 0));
}

/**
 * The pill text for a group holding `changed` non-default settings: a noun count for the page styles list, "N
 * changed" for the rest, and nothing when the group is plain.
 *
 * @param group The group.
 * @param changed How many settings differ from their defaults.
 * @param words The wording: `changed(n)` and `pageStyles(n)`.
 * @returns The pill text, or `undefined` when nothing differs.
 */
export function layoutGroupSummary(
  group: LayoutSettingGroupKey, changed: number | undefined, words: { changed: (n: number) => string; pageStyles: (n: number) => string },
): string | undefined {
  if (!changed) return undefined;
  return group === "styles" ? words.pageStyles(changed) : words.changed(changed);
}

/** Whether any group differs from its defaults (the page setup button's mark). */
export function anySettingChanged(changes: Partial<Record<LayoutSettingGroupKey, number>>): boolean {
  return Object.values(changes).some((n) => (n ?? 0) > 0);
}

/**
 * The Page group's pill: the effective size and orientation, with "mirrored" when the margins are mirrored.
 *
 * @param size The page size.
 * @param orientation The page orientation.
 * @param mirror Whether the margins are mirrored.
 * @param words The wording: `orientation(o)` ("portrait") and `mirrored`.
 * @returns For example "A4 portrait" or "A3 landscape, mirrored".
 */
export function pageGroupSummary(
  size: PageSize, orientation: PageOrientation, mirror: boolean, words: { orientation: (o: PageOrientation) => string; mirrored: string },
): string {
  return `${size} ${words.orientation(orientation)}${mirror ? `, ${words.mirrored}` : ""}`;
}

/**
 * The Margins group's pill: one figure when the four sides agree (and there is no gutter), else each side.
 *
 * @param margins The margins as set (an unset side takes the default).
 * @param words The wording: `all(cm)` ("1.5 cm") and `sides(top, right, bottom, left, gutter)`.
 * @returns The effective margins in words.
 */
export function marginsGroupSummary(
  margins: PageMargins | undefined,
  words: { all: (cm: number) => string; sides: (top: number, right: number, bottom: number, left: number, gutter: number) => string },
): string {
  const m = effectiveMargins(margins);
  if (m.top === m.bottom && m.top === m.left && m.top === m.right && m.gutter === 0) return words.all(m.top);
  return words.sides(m.top, m.right, m.bottom, m.left, m.gutter);
}
