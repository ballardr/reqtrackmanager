/**
 * Module: modules/architecture/architectureFields
 *
 * Pure helpers shared by the element and connection forms and pages: blank and from-record field values, the
 * fields an edit changed (the update sends only those, plus the version lock), the element ids below an element (so a
 * parent picker never offers a cycle) and the text shown for an element in a picker.
 */
import { principalRef } from "../../api/types";
import type {
  ArchitectureConnection, ArchitectureElement, ConnectionFieldValues, ElementFieldValues,
} from "./types";

/** An empty element form; `elementTypeId` preselects the first type. */
export function blankElementValues(elementTypeId = "", parentId: string | null = null): ElementFieldValues {
  return { name: "", description: "", element_type_id: elementTypeId, parent_id: parentId, owner: null, symbol_id: null };
}

/** The editable fields of an element, as the form holds them. */
export function valuesFromElement(element: ArchitectureElement): ElementFieldValues {
  return {
    name: element.name, description: element.description, element_type_id: element.element_type_id,
    parent_id: element.parent_id, owner: principalRef(element.owner), symbol_id: element.symbol_id,
  };
}

/** The fields whose value differs between `before` and `after` (compared by value, owners by type and id). */
export function diffElementFields(before: ElementFieldValues, after: ElementFieldValues): Partial<ElementFieldValues> {
  const changed: Partial<ElementFieldValues> = {};
  (Object.keys(after) as (keyof ElementFieldValues)[]).forEach((key) => {
    const a = before[key];
    const b = after[key];
    const same = key === "owner"
      ? (a as ElementFieldValues["owner"])?.id === (b as ElementFieldValues["owner"])?.id
        && (a as ElementFieldValues["owner"])?.type === (b as ElementFieldValues["owner"])?.type
      : a === b;
    if (!same) (changed as Record<string, unknown>)[key] = b;
  });
  return changed;
}

/** An empty connection form. */
export function blankConnectionValues(connectionTypeId = "", sourceElementId = ""): ConnectionFieldValues {
  return {
    name: "", connection_type_id: connectionTypeId, source_element_id: sourceElementId, source_port_id: null,
    target_element_id: "", target_port_id: null, protocol: "", description: "",
  };
}

/** The editable fields of a connection, as the form holds them. */
export function valuesFromConnection(connection: ArchitectureConnection): ConnectionFieldValues {
  return {
    name: connection.name, connection_type_id: connection.connection_type_id,
    source_element_id: connection.source_element_id, source_port_id: connection.source_port_id,
    target_element_id: connection.target_element_id, target_port_id: connection.target_port_id,
    protocol: connection.protocol, description: connection.description,
  };
}

/** The fields whose value differs between `before` and `after`. */
export function diffConnectionFields(before: ConnectionFieldValues, after: ConnectionFieldValues): Partial<ConnectionFieldValues> {
  const changed: Partial<ConnectionFieldValues> = {};
  (Object.keys(after) as (keyof ConnectionFieldValues)[]).forEach((key) => {
    if (before[key] !== after[key]) (changed as Record<string, unknown>)[key] = after[key];
  });
  return changed;
}

/** The ids of `elementId` and every element below it in `elements`' parent links (cycle-safe). */
export function subtreeIds(elementId: string, elements: ArchitectureElement[]): Set<string> {
  const childrenOf = new Map<string, string[]>();
  for (const e of elements) {
    if (e.parent_id) childrenOf.set(e.parent_id, [...(childrenOf.get(e.parent_id) ?? []), e.id]);
  }
  const seen = new Set<string>([elementId]);
  const queue = [elementId];
  while (queue.length > 0) {
    for (const child of childrenOf.get(queue.shift() as string) ?? []) {
      if (!seen.has(child)) {
        seen.add(child);
        queue.push(child);
      }
    }
  }
  return seen;
}

/** A node of the element tree. */
export interface ElementTreeNode {
  id: string;
  element: ArchitectureElement;
  children: ElementTreeNode[];
}

/**
 * Arranges `elements` as a forest by their parent links. An element whose parent is not in the list (filtered out, or
 * owned by another project) is a root of the forest, so a filtered list still shows every match.
 */
export function buildElementTree(elements: ArchitectureElement[]): ElementTreeNode[] {
  const nodes = new Map<string, ElementTreeNode>(elements.map((e) => [e.id, { id: e.id, element: e, children: [] }]));
  const roots: ElementTreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.element.parent_id ? nodes.get(node.element.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

/** The record-code inputs for an element, so `ScopedRecordCode` qualifies an organisation-owned one by its organisation. */
export function elementCodeRecord(element: ArchitectureElement) {
  return {
    unique_code: element.unique_code, scope: element.organization_id ? "organization" : "project",
    organization_id: element.organization_id, from_project_code: element.from_project_code,
  };
}
