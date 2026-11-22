/**
 * Module: components/TreeToggle
 *
 * The one expand/collapse chevron of every tree and nested list (`TreeView`, `FolderTreeList`,
 * `RequirementTree`): a plain disclosure control, not a bordered button, because it sits inside a
 * row that is itself the choice or the link. It stays a real `<button>` with an accessible name and
 * a 1.75rem hit area so it can be touched and reached by keyboard.
 *
 * Presentational: the caller owns the expanded state. `TreeChevron` is the bare glyph for a toggle
 * that carries a label of its own (a folder's icon and name in `FolderTreeList`), so the glyph,
 * size and direction are the same everywhere; `TreeToggleGap` holds the same width for a leaf.
 *
 * The tooltip ("Collapse Acme") is the shared `Tooltip`, never a native `title`; a transient picker, where the row's
 * name is beside the chevron and the list must not be covered, turns it off (`tooltip={false}`).
 *
 * Depends on lucide-react and `Tooltip`; styles are `.tree-toggle` and `.tree-toggle-gap` in `styles/theme.css`.
 */
import { ChevronDown, ChevronRight } from "lucide-react";

import { Tooltip } from "./Tooltip";

/**
 * The chevron glyph: down while open, right while closed.
 *
 * @param expanded Whether the node is open.
 * @returns A decorative icon (the surrounding control carries the name).
 */
export function TreeChevron({ expanded }: { expanded: boolean }) {
  return expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />;
}

/**
 * A plain expand/collapse button for one tree node.
 *
 * @param expanded Whether the node is open.
 * @param name The node's plain-text name; the accessible name reads "Collapse <name>" or "Expand <name>".
 * @param onToggle Called when the button is pressed.
 * @param tabIndex Pass `-1` where the row handles keyboard navigation itself.
 * @param tooltip Whether hovering or focusing the chevron shows its name (default true); a picker passes false.
 * @returns The button.
 */
export function TreeToggle({
  expanded, name, onToggle, tabIndex, tooltip = true,
}: { expanded: boolean; name: string; onToggle: () => void; tabIndex?: number; tooltip?: boolean }) {
  const label = expanded ? `Collapse ${name}` : `Expand ${name}`;
  const button = (
    <button
      type="button" className="tree-toggle" aria-expanded={expanded} aria-label={label}
      tabIndex={tabIndex} onClick={onToggle}
    >
      <TreeChevron expanded={expanded} />
    </button>
  );
  return tooltip ? <Tooltip label={label}>{button}</Tooltip> : button;
}

/** The space a leaf node keeps where a branch has its chevron, so labels line up at every depth. */
export function TreeToggleGap() {
  return <span className="tree-toggle-gap" aria-hidden="true" />;
}
