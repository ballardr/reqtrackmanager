/**
 * Module: modules/architecture/diagramToggles
 *
 * Plain helpers for a diagram's view switches, shared by the switch form, the switches panel and the editor page: a blank
 * switch and the stored form of a switch read from a resolved view.
 */
import type { DiagramToggle, DiagramToggleValues } from "./types";

/** A blank switch: on by default, matching nothing. */
export function blankToggle(): DiagramToggleValues {
  return {
    id: null, name: "", default_on: true, element_ids: [], connection_ids: [],
    rule: { element_type_ids: [], connection_type_ids: [], domains: [], tags: [] },
  };
}

/** @param toggle A switch as the view returns it. @returns The same switch as the form and the store hold it. */
export function toggleValues(toggle: DiagramToggle): DiagramToggleValues {
  return {
    id: toggle.id, name: toggle.name, default_on: toggle.default_on, rule: toggle.rule,
    element_ids: toggle.element_ids, connection_ids: toggle.connection_ids,
  };
}

/** The prefix of a palette drop payload that names an element type (`type:<id>`). */
export const PALETTE_TYPE_PREFIX = "type:";
