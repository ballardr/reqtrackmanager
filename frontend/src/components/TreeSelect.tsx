/**
 * Module: components/TreeSelect
 *
 * A closed-by-default multi-select over a *tree* of options, the hierarchical sibling of `MultiSelectDropdown`
 * (docs/ux-style-guide.md "Pattern: multi-select dropdown"): one dropdown summarising the checked labels, opening a
 * `Popover` with the tree and a checkbox per node. Used where a record can be in several places of a taxonomy (a
 * Stakeholder's groups). The tree shell is the shared `TreeView`; checking a node never checks its ancestors or
 * descendants, since each id is independent. The chevron stays beside the label, indented by depth, and the checkboxes
 * sit in one column at the right edge; the whole row is the click target.
 *
 * Presentational: the caller owns `selectedIds` and applies `onChange`. A node may be `disabled` (with a `title`
 * explaining why) to show a position that cannot be chosen, e.g. an organisation group inside a project picker.
 *
 * `single` makes it a one-choice picker (the chosen row has a tick and is a radio to assistive technology; choosing
 * closes the list; `clearLabel` adds a row that clears it). `searchable` adds a search box keeping matching nodes and
 * their ancestors, with every branch open while searching. The search box and clear row are a fixed header and only the
 * list below scrolls (`ScrollRegion`), so a scrolled list never moves the search away. A one-choice row shows the
 * node's own name under its parent and keeps the whole path (`pathLabel`) as its accessible name and in the trigger. A
 * node may appear under several parents (the same id twice); each place shows the same state.
 *
 * The panel opens under the field with its left edge on the field's (`Popover matchAnchor`), as wide as the field up to
 * 28rem, and below it whenever there is usable room.
 *
 * Tooltips: the closed trigger shows its full summary in the shared `Tooltip` only while the summary is clipped and never
 * while the list is open; a chevron has none; a row has one only to say why a `disabled` node cannot be chosen. No native
 * `title` (`scripts/check_native_title.py`).
 */
import { Check, ChevronDown } from "lucide-react";
import { useRef, useState } from "react";

import { useIsClipped } from "../hooks/useIsClipped";
import { Popover } from "./Popover";
import { ScrollRegion } from "./ScrollRegion";
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
  /** The node's name where its place in the tree is not visible (the trigger's summary, the control's accessible name),
   * for example `Hardware / Power` for a category; defaults to `label`. */
  pathLabel?: string;
}

/** The widest the panel gets (28rem): a picker in a dialog-wide field opens at the field's left edge, not across the row. */
const PANEL_MAX_WIDTH_PX = 448;

function flatten(nodes: TreeSelectNode[]): TreeSelectNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)]);
}

/** The row of a one-choice picker: a full-width selectable row with a tick on the chosen one, announced as a radio. */
function SingleChoiceRow({
  label, text, checked, disabled, onChoose,
}: { label: string; text?: string; checked: boolean; disabled?: boolean; onChoose: () => void }) {
  return (
    <button
      type="button" role="radio" aria-checked={checked} aria-label={label} disabled={disabled} onClick={onChoose}
      className="row"
      style={{
        flex: 1, minWidth: 0, flexWrap: "nowrap", justifyContent: "space-between", gap: "var(--space-2)", fontSize: "0.85rem",
        padding: "var(--space-1) var(--space-3)", border: "none", borderRadius: "var(--radius-sm, 4px)", textAlign: "left", cursor: disabled ? "not-allowed" : "pointer",
        background: checked ? "var(--color-surface-alt)" : "transparent", color: "inherit", fontWeight: checked ? 600 : undefined,
      }}
    >
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{text ?? label}</span>
      {checked && <Check size={14} aria-hidden="true" style={{ flexShrink: 0 }} />}
    </button>
  );
}

/** One row of the opened tree, its checkbox at the right edge (or, in a one-choice picker, a selectable row with no checkbox); a disabled node explains why in a tooltip. */
function TreeSelectOption({
  n, checked, onToggle, single,
}: { n: TreeSelectNode; checked: boolean; onToggle: () => void; single: boolean }) {
  const row = single ? (
    <SingleChoiceRow label={n.pathLabel ?? n.label} text={n.label} checked={checked} disabled={n.disabled} onChoose={onToggle} />
  ) : (
    <label className="tree-select-option">
      <span className="tree-select-option-label">{n.label}</span>
      <input type="checkbox" checked={checked} disabled={n.disabled} aria-label={n.pathLabel ?? n.label} onChange={onToggle} />
    </label>
  );
  return n.disabled && n.title ? (
    <Tooltip label={n.title} wrap style={{ display: "flex", flex: "1 1 0", minWidth: 0 }}>{row}</Tooltip>
  ) : row;
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
  /** One choice: a selectable row per node, and choosing closes the list. `onChange` then gets a list of at most one id. */
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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [summaryRef, summaryClipped] = useIsClipped<HTMLSpanElement>();
  const selected = new Set(selectedIds);
  const summary =
    flatten(nodes).filter((n) => selected.has(n.id)).map((n) => n.pathLabel ?? n.label).join(", ") || emptyLabel;
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
      <Tooltip label={summary} wrap disabled={!summaryClipped || open} style={{ display: "flex", width: "100%" }}>
        <button
          ref={triggerRef}
          id={id}
          type="button"
          className="input row"
          style={{ justifyContent: "space-between", flexWrap: "nowrap", cursor: "pointer" }}
          aria-label={triggerLabel}
          aria-haspopup="true"
          aria-expanded={open}
          onClick={() => { setQuery(""); setOpen((o) => !o); }}
        >
          <span ref={summaryRef} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 /* grid-text-ok: the label of a select control, not a cell of a grid */ }}>{summary}</span>
          <ChevronDown size={14} style={{ flexShrink: 0 }} />
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} onClose={() => setOpen(false)} matchAnchor maxWidth={PANEL_MAX_WIDTH_PX} flush>
          {(searchable || (single && clearLabel)) && (
            <div className="popover-flush-header stack" style={{ gap: "var(--space-2)", minWidth: "14rem" }}>
              {searchable && (
                <input
                  className="input" type="search" value={query} aria-label={`Search ${triggerLabel}`} placeholder="Search"
                  onChange={(e) => setQuery(e.target.value)}
                />
              )}
              {single && clearLabel && (
                <div className="row" style={{ minHeight: "2rem" }}>
                  <SingleChoiceRow label={clearLabel} checked={selectedIds.length === 0} onChoose={() => { onChange([]); setOpen(false); }} />
                </div>
              )}
            </div>
          )}
          <ScrollRegion role={single ? "radiogroup" : "group"} aria-label={triggerLabel} maxHeight="20rem" style={{ minWidth: "14rem" }}>
            <TreeView
              nodes={shown}
              emptyText={searching ? "Nothing matches." : "No options."}
              nodeLabel={(n) => n.label}
              toggleTooltip={false}
              expanded={searching ? new Set(flatten(shown).map((n) => n.id)) : undefined}
              onToggle={() => undefined}
              renderNode={(n) => (
                <TreeSelectOption n={n} checked={selected.has(n.id)} onToggle={() => toggle(n.id)} single={single} />
              )}
            />
          </ScrollRegion>
        </Popover>
      )}
    </>
  );
}
