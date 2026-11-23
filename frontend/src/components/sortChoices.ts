/**
 * Module: components/sortChoices
 *
 * The choices of a list's **Sort by** field (`SortField`): each sortable column of its table, then **Created** and
 * **Modified**. Split out of `SortField.tsx` so that file exports only the component (Fast Refresh).
 */
import type { ReactNode } from "react";

/** One thing a list can be ordered by. */
export interface SortChoice {
  /** The sort key (a column key, `created` or `modified`). */
  value: string;
  /** What the person sees (the column's heading). */
  label: string;
}

/** The columns of a table that can be sorted, in the order the table shows them. */
export interface SortableColumn {
  key: string;
  label: ReactNode;
  sortable?: boolean;
}

/**
 * The choices a list offers: each sortable column of its table, then **Created** and **Modified**.
 *
 * @param columns The table's columns (a column with no natural order is not offered).
 * @param created The label for the creation time.
 * @param modified The label for the modification time.
 * @returns The choices in display order; a key that is already a column is not repeated.
 */
export function sortChoices(columns: readonly SortableColumn[], created: string, modified: string): SortChoice[] {
  const choices = columns
    .filter((c) => c.sortable)
    .map((c) => ({ value: c.key, label: typeof c.label === "string" ? c.label : c.key }));
  for (const [value, label] of [["created", created], ["modified", modified]] as const) {
    if (!choices.some((c) => c.value === value)) choices.push({ value, label });
  }
  return choices;
}

