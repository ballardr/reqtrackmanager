/**
 * Module: components/TreeSelectField
 *
 * A form field whose value is chosen from a tree: the shared field caption (with `(?)` help and the `*` of a
 * required field) around a `TreeSelect`. Use it for a vocabulary that nests (the connection types) in a create or
 * edit form; a flat list is a `LabeledSelect`. Presentational: the caller owns the value.
 */
import { useId } from "react";

import { FieldShell, type FieldHelpProps } from "./FieldHelp";
import { TreeSelect, type TreeSelectNode } from "./TreeSelect";

/**
 * @param label The caption, also the trigger's accessible name.
 * @param nodes The tree of options.
 * @param value The chosen ids (at most one when `single`).
 * @param onChange Called with the new ids.
 * @param single One choice instead of several.
 * @param searchable Adds a search box to the opened tree.
 * @param emptyLabel The trigger's text while nothing is chosen.
 * @param clearLabel One-choice only: adds an entry that clears the choice.
 * @param required Marks the field with `*`.
 */
export function TreeSelectField({
  label, nodes, value, onChange, single = false, searchable = false, emptyLabel, clearLabel, help, required,
}: FieldHelpProps & {
  label: string;
  nodes: TreeSelectNode[];
  value: string[];
  onChange: (next: string[]) => void;
  single?: boolean;
  searchable?: boolean;
  emptyLabel?: string;
  clearLabel?: string;
}) {
  const id = useId();
  return (
    <FieldShell label={label} controlId={id} help={help} required={required}>
      <TreeSelect
        id={id} triggerLabel={label} nodes={nodes} selectedIds={value} onChange={onChange} single={single}
        searchable={searchable} emptyLabel={emptyLabel} clearLabel={clearLabel}
      />
    </FieldShell>
  );
}
