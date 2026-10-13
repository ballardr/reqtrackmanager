/**
 * Module: components/TreeSelect
 *
 * A closed-by-default multi-select over a *tree* of options — the hierarchical
 * sibling of `MultiSelectDropdown` (docs/ux-style-guide.md "Pattern:
 * multi-select dropdown"): it looks like one dropdown, summarises the checked
 * options' labels, and opens a `Popover` holding the tree with a checkbox per
 * node. Used where a record can be in several places of a taxonomy at once
 * (a Stakeholder's groups). The tree shell is the shared `TreeView`; checking a
 * node never checks its ancestors or descendants, since each id is independent.
 *
 * Presentational: the caller owns `selectedIds` and applies `onChange`. A
 * node may be `disabled` (with a `title` explaining why) to show a position in
 * the tree that cannot be chosen, e.g. an organisation group inside a project
 * picker.
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState } from "react";

import { Popover } from "./Popover";
import { TreeView } from "./TreeView";

export interface TreeSelectNode {
  id: string;
  label: string;
  children: TreeSelectNode[];
  disabled?: boolean;
  /** Tooltip while `disabled`, explaining why the node cannot be chosen. */
  title?: string;
}

function flatten(nodes: TreeSelectNode[]): TreeSelectNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)]);
}

export function TreeSelect({
  triggerLabel,
  nodes,
  selectedIds,
  onChange,
  emptyLabel = "None",
}: {
  /** Accessible name for the trigger and the opened tree's title. */
  triggerLabel: string;
  nodes: TreeSelectNode[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  /** Shown on the trigger when nothing is checked. */
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selected = new Set(selectedIds);
  const summary =
    flatten(nodes).filter((n) => selected.has(n.id)).map((n) => n.label).join(", ") || emptyLabel;

  function toggle(id: string) {
    onChange(selected.has(id) ? selectedIds.filter((s) => s !== id) : [...selectedIds, id]);
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="input row"
        style={{ justifyContent: "space-between", flexWrap: "nowrap", cursor: "pointer" }}
        title={summary}
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{summary}</span>
        <ChevronDown size={14} style={{ flexShrink: 0 }} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} onClose={() => setOpen(false)}>
          <div role="group" aria-label={triggerLabel} style={{ minWidth: "14rem", maxHeight: "20rem", overflowY: "auto" }}>
            <TreeView
              nodes={nodes}
              emptyText="No options."
              nodeLabel={(n) => n.label}
              renderNode={(n) => (
                <label className="row" style={{ gap: "0.35rem", fontSize: "0.85rem" }} title={n.disabled ? n.title : undefined}>
                  <input
                    type="checkbox"
                    checked={selected.has(n.id)}
                    disabled={n.disabled}
                    aria-label={n.label}
                    onChange={() => toggle(n.id)}
                  />
                  {n.label}
                </label>
              )}
            />
          </div>
        </Popover>
      )}
    </>
  );
}
