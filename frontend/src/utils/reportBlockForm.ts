/**
 * Module: utils/reportBlockForm
 *
 * How a block's form is arranged, read from the block type's schema.
 *
 * Responsibilities: `arrangeBlockFields` splits a type's fields into the always-visible basic part and its collapsible
 * groups (in the schema's order); `blockGroupKey` names the key a group's open/closed choice is remembered under.
 *
 * Design decisions: arrangement only, nothing here changes what is stored. A type that declares no groups is flat. A
 * field that names a group the schema does not declare lands in an "Other" group, so a field the server adds is never
 * lost to a client that does not know its group.
 */
import type { BlockField, BlockGroup, BlockType } from "../api/reportLayouts";

/** The group a field lands in when it names one the schema does not declare. */
export const OTHER_GROUP_KEY = "other";

/** The arranged form: the basic fields, then each non-empty group. */
export interface ArrangedBlockForm {
  basic: BlockField[];
  groups: { group: BlockGroup; fields: BlockField[] }[];
}

/**
 * @param type The block type.
 * @param otherLabel What the "Other" group is called.
 * @returns The basic fields and the groups with their fields, each in schema order.
 */
export function arrangeBlockFields(type: Pick<BlockType, "fields" | "groups">, otherLabel: string): ArrangedBlockForm {
  if (type.groups.length === 0) return { basic: type.fields, groups: [] };
  const declared = new Set(type.groups.map((g) => g.key));
  const groups = type.groups.map((group) => ({ group, fields: type.fields.filter((f) => f.group === group.key) }));
  const stray = type.fields.filter((f) => f.group !== "" && !declared.has(f.group));
  if (stray.length > 0) groups.push({ group: { key: OTHER_GROUP_KEY, label: otherLabel, open: false }, fields: stray });
  return { basic: type.fields.filter((f) => f.group === ""), groups: groups.filter((g) => g.fields.length > 0) };
}

/** The key a block type's group state is remembered under (per person, per block type, not per block). */
export function blockGroupKey(blockType: string, groupKey: string): string {
  return `blockSettings:${blockType}:${groupKey}`;
}
