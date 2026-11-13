/**
 * Module: modules/architecture/DiagramAddMenu
 *
 * The editor's "Add to diagram" menu button: one entry per element type (grouped by domain, the domain-neutral ones under "New element"; choosing one creates an element
 * at the next free place, dragging one onto the canvas creates it where it is dropped), then "Add existing elements" and
 * "Add note". Dragging is only one way in: every entry is a menu item, so the menu is usable from the keyboard.
 * For a person who may manage the project's types, a last entry (a gear) leads to the Element Types settings, so a type
 * that is missing can be added without hunting for the page.
 */
import { Settings } from "lucide-react";

import { GRAPH_DROP_MIME } from "../../components/GraphCanvas";
import { MenuButton } from "../../components/MenuButton";
import type { ActionMenuItem } from "../../components/ActionMenu";
import { PALETTE_TYPE_PREFIX } from "./diagramToggles";
import { DOMAIN_LABEL, type Domain, type ElementType } from "./types";

const DOMAIN_ORDER: Domain[] = ["software", "hardware", "any"];

/**
 * Builds the menu's entries: the element types in domain groups, then the two non-type entries.
 *
 * @param elementTypes The types that may be created.
 * @param handlers What each kind of entry does when chosen.
 * @returns The entries in display order; the items of one group are adjacent, as the menu requires.
 */
function addMenuItems(
  elementTypes: ElementType[],
  handlers: { onAddType: (typeId: string) => void; onAddExisting: () => void; onAddNote: () => void; onSetup?: () => void },
): ActionMenuItem[] {
  const typeItems = DOMAIN_ORDER.flatMap((domain) => elementTypes
    .filter((t) => t.domain === domain)
    .map((t): ActionMenuItem => ({
      label: t.name,
      key: `type:${t.id}`,
      group: domain === "any" ? "New element" : `New ${DOMAIN_LABEL[domain].toLowerCase()} element`,
      onSelect: () => handlers.onAddType(t.id),
      onDragStart: (event) => {
        event.dataTransfer.setData(GRAPH_DROP_MIME, PALETTE_TYPE_PREFIX + t.id);
        event.dataTransfer.effectAllowed = "copy";
      },
    })));
  return [
    ...typeItems,
    { label: "Add existing elements", key: "existing", group: "Other", onSelect: handlers.onAddExisting },
    { label: "Add note", key: "note", group: "Other", onSelect: handlers.onAddNote },
    ...(handlers.onSetup
      ? [{ label: "Set up element types", key: "setup", group: "Settings", icon: <Settings size={14} aria-hidden="true" />, onSelect: handlers.onSetup }]
      : []),
  ];
}

/**
 * @param elementTypes The types that may be created.
 * @param disabled True when the diagram cannot be edited (read-only).
 * @param onAddType Called with the type's id when a type is chosen.
 * @param onAddExisting Called by "Add existing elements".
 * @param onAddNote Called by "Add note".
 * @param onSetup Called by "Set up element types"; leave undefined for a person who may not manage types (no entry).
 */
export function DiagramAddMenu({
  elementTypes, disabled, onAddType, onAddExisting, onAddNote, onSetup,
}: {
  elementTypes: ElementType[];
  disabled: boolean;
  onAddType: (typeId: string) => void;
  onAddExisting: () => void;
  onAddNote: () => void;
  onSetup?: () => void;
}) {
  return (
    <MenuButton
      label="Add to diagram" menuLabel="Add to diagram" disabled={disabled}
      items={addMenuItems(elementTypes, { onAddType, onAddExisting, onAddNote, onSetup })}
    />
  );
}
