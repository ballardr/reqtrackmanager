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
 *
 * `single` turns it into a one-choice picker (a radio per node; choosing closes the list, and `clearLabel` adds an
 * entry that clears the choice), and `searchable` adds a search box that keeps the nodes whose label matches and the
 * ancestors leading to them, with every branch open while a search is active. A node may appear under several
 * parents (the same id twice): each place shows the same state.
 */
import { ChevronDown } from "lucide-react";
import { useId, useRef, useState } from "react";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";
import { filterTreeNodes } from "./treeSelectFilter";
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

/** One checkbox (or, in a one-choice picker, radio) row of the opened tree; a disabled node explains why in a tooltip. */
function TreeSelectOption({
  n, checked, onToggle, radioName,
}: { n: TreeSelectNode; checked: boolean; onToggle: () => void; radioName?: string }) {
  const row = (
    <label className="checkbox-label" style={{ gap: "var(--space-2)", fontSize: "0.85rem" }}>
      <input
        type={radioName ? "radio" : "checkbox"} name={radioName} checked={checked} disabled={n.disabled}
        aria-label={n.label} onChange={onToggle}
      />
      {n.label}
    </label>
  );
  return n.disabled && n.title ? <Tooltip label={n.title} wrap>{row}</Tooltip> : row;
}

export function TreeSelect({
  triggerLabel,
  nodes,
  selectedIds,
  onChange,
  emptyLabel = "None",
  single = false,
  searchable = false,
  clearLabel,
  id,
}: {
  /** Accessible name for the trigger and the opened tree's title. */
  triggerLabel: string;
  nodes: TreeSelectNode[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  /** Shown on the trigger when nothing is checked. */
  emptyLabel?: string;
  /** One choice: a radio per node, and choosing closes the list. `onChange` then gets a list of at most one id. */
  single?: boolean;
  /** Adds a search box above the tree. */
  searchable?: boolean;
  /** One-choice picker only: adds an entry that clears the choice, with this text ("All types"). */
  clearLabel?: string;
  /** The trigger's `id`, so a field caption can point at it. */
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const radioName = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selected = new Set(selectedIds);
  const summary =
    flatten(nodes).filter((n) => selected.has(n.id)).map((n) => n.label).join(", ") || emptyLabel;
  const shown = filterTreeNodes(nodes, query);
  const searching = query.trim() !== "";

  function toggle(id: string) {
    if (single) {
      onChange([id]);
      setOpen(false);
      return;
    }
    onChange(selected.has(id) ? selectedIds.filter((s) => s !== id) : [...selectedIds, id]);
  }

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className="input row"
        style={{ justifyContent: "space-between", flexWrap: "nowrap", cursor: "pointer" }}
        title={summary}
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => { setQuery(""); setOpen((o) => !o); }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{summary}</span>
        <ChevronDown size={14} style={{ flexShrink: 0 }} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} onClose={() => setOpen(false)}>
          <div role="group" aria-label={triggerLabel} style={{ minWidth: "14rem", maxHeight: "20rem", overflowY: "auto" }}>
            {searchable && (
              <input
                className="input" type="search" value={query} aria-label={`Search ${triggerLabel}`} placeholder="Search"
                onChange={(e) => setQuery(e.target.value)} style={{ marginBottom: "var(--space-2)" }}
              />
            )}
            {single && clearLabel && (
              <label className="checkbox-label" style={{ gap: "var(--space-2)", fontSize: "0.85rem", minHeight: "2rem" }}>
                <input
                  type="radio" name={radioName} checked={selectedIds.length === 0} aria-label={clearLabel}
                  onChange={() => { onChange([]); setOpen(false); }}
                />
                {clearLabel}
              </label>
            )}
            <TreeView
              nodes={shown}
              emptyText={searching ? "Nothing matches." : "No options."}
              nodeLabel={(n) => n.label}
              expanded={searching ? new Set(flatten(shown).map((n) => n.id)) : undefined}
              onToggle={() => undefined}
              renderNode={(n) => (
                <TreeSelectOption
                  n={n} checked={selected.has(n.id)} onToggle={() => toggle(n.id)} radioName={single ? radioName : undefined}
                />
              )}
            />
          </div>
        </Popover>
      )}
    </>
  );
}
