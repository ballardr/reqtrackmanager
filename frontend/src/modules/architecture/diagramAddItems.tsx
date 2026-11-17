/**
 * Module: modules/architecture/diagramAddItems
 *
 * The entries of the editor's "Add to diagram" menu: one per element type, listed under each domain the type is in (in
 * the domains' order) and a type in no domain under "New element"; then, on a diagram of an element's inside, the outer
 * connections that can still be drawn as boundary boxes, "Add existing elements", "Add note" and, for a person who may
 * manage the types, a gear entry to the Element Types settings. Pure over the vocabulary rows, so the grouping is tested
 * without a screen; `DiagramAddMenu` draws them.
 */
import { Settings } from "lucide-react";

import type { ActionMenuItem } from "../../components/ActionMenu";
import { GRAPH_DROP_MIME } from "../../components/GraphCanvas";
import { PALETTE_TYPE_PREFIX } from "./diagramToggles";
import type { ArchitectureDomain, ElementType } from "./types";

/** An outer connection that can still be added as a boundary box: its id and the text the menu shows. */
export interface OuterConnectionChoice {
  id: string;
  label: string;
}

/**
 * Builds the menu's entries: the element types in domain groups (a type once under each of its domains, a type in none
 * under "New element" after them), then the non-type entries.
 *
 * @param elementTypes The types that may be created.
 * @param domains The project's domains, in the order their groups are listed.
 * @param handlers What each kind of entry does when chosen.
 * @returns The entries in display order; the items of one group are adjacent, as the menu requires.
 */
export function addMenuItems(
  elementTypes: ElementType[],
  domains: readonly ArchitectureDomain[],
  handlers: {
    onAddType: (typeId: string) => void; onAddExisting: () => void; onAddNote: () => void; onSetup?: () => void;
    outerConnections: readonly OuterConnectionChoice[]; onAddOuter: (connectionId: string) => void;
  },
): ActionMenuItem[] {
  const typeItem = (t: ElementType, group: string, key: string): ActionMenuItem => ({
    label: t.name,
    key,
    group,
    onSelect: () => handlers.onAddType(t.id),
    onDragStart: (event) => {
      event.dataTransfer.setData(GRAPH_DROP_MIME, PALETTE_TYPE_PREFIX + t.id);
      event.dataTransfer.effectAllowed = "copy";
    },
  });
  const typeItems = [
    ...domains.flatMap((domain) => elementTypes
      .filter((t) => t.domain_ids.includes(domain.id))
      .map((t) => typeItem(t, `New ${domain.name.toLowerCase()} element`, `type:${domain.id}:${t.id}`))),
    ...elementTypes.filter((t) => t.domain_ids.length === 0).map((t) => typeItem(t, "New element", `type:${t.id}`)),
  ];
  const outerItems = handlers.outerConnections.map((c): ActionMenuItem => ({
    label: c.label, key: `outer:${c.id}`, group: "Outside this element", onSelect: () => handlers.onAddOuter(c.id),
  }));
  return [
    ...typeItems,
    ...outerItems,
    { label: "Add existing elements", key: "existing", group: "Other", onSelect: handlers.onAddExisting },
    { label: "Add note", key: "note", group: "Other", onSelect: handlers.onAddNote },
    ...(handlers.onSetup
      ? [{ label: "Set up element types", key: "setup", group: "Settings", icon: <Settings size={14} aria-hidden="true" />, onSelect: handlers.onSetup }]
      : []),
  ];
}
