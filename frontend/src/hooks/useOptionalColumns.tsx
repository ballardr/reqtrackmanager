/**
 * Module: hooks/useOptionalColumns
 *
 * The one step that gives a `DirectoryTable` list a column chooser. A list marks its columns `optional` (and
 * `defaultHidden` for one that is off until chosen) and passes the full column set here; the hook returns the columns
 * to draw and the shared `ColumnChooser` bound to them, remembered per person (`useColumnChoice`, `ui_preferences`).
 * A column that is not optional (the Name, the Code, the Status) is always drawn.
 *
 * The chooser changes the screen only: the list keeps the full column set for its Sort by field, Export and Import,
 * so a hidden column can still be sorted by and is still in a file.
 *
 * Dependencies: `ColumnChooser`, `useColumnChoice`, `DirectoryTable` (the column type).
 */
import type { ReactNode } from "react";

import { ColumnChooser } from "../components/ColumnChooser";
import type { DirectoryColumn } from "../components/DirectoryTable";
import { useColumnChoice } from "./useColumnChoice";

/** Columns that hold row controls, not data: they are never listed as a shown column. */
const CONTROL_COLUMNS: ReadonlySet<string> = new Set(["actions", "preview", "select"]);

/** A column's name for the chooser: its `chooserLabel`, its text label, or its key. */
function chooserName<Row>(column: DirectoryColumn<Row>): string {
  return column.chooserLabel ?? (typeof column.label === "string" ? column.label : column.key);
}

/**
 * @param key Names the list; each list remembers its own choice (`column_choice_<key>`).
 * @param columns Every column the list can draw, in order. Mark the ones a person may hide `optional`.
 * @returns `columns`, the ones to draw now, and `chooser`, the control to place in the list's actions (null when the
 *   list offers nothing to choose: fewer than two optional columns and none hidden by default).
 */
export function useOptionalColumns<Row>(
  key: string,
  columns: DirectoryColumn<Row>[],
): { columns: DirectoryColumn<Row>[]; chooser: ReactNode } {
  const optional = columns.filter((c) => c.optional);
  const idsKey = optional.map((c) => c.key).join("\n");
  const defaultsKey = optional.filter((c) => !c.defaultHidden).map((c) => c.key).join("\n");
  // Derived from the joined strings so the arrays keep their identity while the column set is unchanged.
  const allIds = idsKey ? idsKey.split("\n") : [];
  const defaultIds = defaultsKey ? defaultsKey.split("\n") : [];
  const choice = useColumnChoice(key, allIds, defaultIds);

  const drawn = columns.filter((c) => !c.optional || choice.visible.includes(c.key));
  // A column that is off by default needs the chooser to be reachable, even when it is the list's only optional one.
  const offered = optional.length >= 2 || optional.some((c) => c.defaultHidden);
  const chooser = offered ? (
    <ColumnChooser
      columns={optional.map((c) => ({ id: c.key, label: chooserName(c) }))}
      visible={choice.visible} onToggle={choice.toggle} onReset={choice.reset} isDefault={choice.isDefault}
      alwaysOn={columns.filter((c) => !c.optional && !CONTROL_COLUMNS.has(c.key)).map(chooserName)}
    />
  ) : null;
  return { columns: drawn, chooser };
}
