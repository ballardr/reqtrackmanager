/**
 * Module: modules/architecture/DiagramAddMenu
 *
 * The editor's "Add to diagram" menu button: one entry per element type (listed under each domain the type is in, in the
 * domains' order, and a type in no domain under "New element"; choosing one creates an element
 * at the next free place, dragging one onto the canvas creates it where it is dropped), then "Add existing elements" and
 * "Add note". On a diagram of an element's inside, a last group "Outside this element" lists the connections that cross the
 * element's boundary, each drawn as a boundary box. Dragging is only one way in: every entry is a menu item, so the menu is usable from the keyboard.
 * For a person who may manage the project's types, a last entry (a gear) leads to the Element Types settings, so a type
 * that is missing can be added without hunting for the page.
 */
import { MenuButton } from "../../components/MenuButton";
import { addMenuItems, type OuterConnectionChoice } from "./diagramAddItems";
import type { ArchitectureDomain, ElementType } from "./types";

/**
 * @param elementTypes The types that may be created.
 * @param domains The project's domains (the menu's groups).
 * @param disabled True when the diagram cannot be edited (read-only).
 * @param onAddType Called with the type's id when a type is chosen.
 * @param onAddExisting Called by "Add existing elements".
 * @param onAddNote Called by "Add note".
 * @param onSetup Called by "Set up element types"; leave undefined for a person who may not manage types (no entry).
 * @param outerConnections The connections crossing the diagram's element boundary that are not yet drawn (none for the system context).
 * @param onAddOuter Called with an outer connection's id when it is chosen.
 */
export function DiagramAddMenu({
  elementTypes, domains, disabled, onAddType, onAddExisting, onAddNote, onSetup, outerConnections, onAddOuter,
}: {
  elementTypes: ElementType[];
  domains: ArchitectureDomain[];
  disabled: boolean;
  onAddType: (typeId: string) => void;
  onAddExisting: () => void;
  onAddNote: () => void;
  onSetup?: () => void;
  outerConnections: readonly OuterConnectionChoice[];
  onAddOuter: (connectionId: string) => void;
}) {
  return (
    <MenuButton
      label="Add to diagram" menuLabel="Add to diagram" size="sm" disabled={disabled}
      items={addMenuItems(elementTypes, domains, { onAddType, onAddExisting, onAddNote, onSetup, outerConnections, onAddOuter })}
    />
  );
}
