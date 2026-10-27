/**
 * Module: utils/reportPackDraft
 *
 * Small helpers the report pack editor's parts share: the client-only ids that keep a reordered list's text in the
 * right box, and which formats a layout can be produced in.
 */
import type { LayoutFamily } from "../api/reportLayouts";
import type { PackFormat } from "../api/reportPacks";

/** A layout the scope can reach, as the entries editor offers it. */
export interface LayoutChoice {
  name: string;
  family: LayoutFamily;
}

/** The formats each layout family can be produced in. */
export const FAMILY_FORMATS: Record<LayoutFamily, PackFormat[]> = {
  document: ["pdf", "docx", "odt", "html"],
  table: ["csv", "xlsx", "ods"],
};
const ALL_LAYOUT_FORMATS: PackFormat[] = ["pdf", "docx", "odt", "html", "csv", "xlsx", "ods"];

let nextUid = 0;
/** A fresh client-only id for a draft entry or variable. */
export function newUid(): string {
  nextUid += 1;
  return `draft-${nextUid}`;
}

/** The formats a layout entry can be produced in, given the layout it names (every format when the name is unknown). */
export function layoutFormats(layouts: LayoutChoice[], name: string): PackFormat[] {
  const found = layouts.find((l) => l.name === name);
  return found ? FAMILY_FORMATS[found.family] : ALL_LAYOUT_FORMATS;
}

/** JSON with every object's keys sorted, so two definitions that mean the same compare equal whatever order they were built in. */
export function canonicalJson(value: unknown): string {
  const sorted = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sorted);
    if (v !== null && typeof v === "object") {
      return Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, sorted(x)]));
    }
    return v;
  };
  return JSON.stringify(sorted(value));
}
