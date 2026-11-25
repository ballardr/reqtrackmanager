/**
 * Fixtures for the Structure stories: a small tree and a stateful fake `StructureApi` whose methods are `fn()` spies,
 * so a story sees a created, moved or deleted node in the next read and can assert what was called, without a network.
 *
 * The fake suggestion stands in for the server's rule: the initials of several words, the first letters of one word,
 * numbered when the prefix is taken among the siblings.
 */
import { fn } from "storybook/test";

import { ApiError } from "../api/client";
import type { PlacementTree } from "../api/placements";
import type { NodeValues, StructureApi, StructureCounts, StructureKind, SuggestionRequest } from "../api/structure";
import type { Category, Component } from "../api/types";

export const STRUCTURE_PROJECT_ID = "project-1";

/** Hardware (Cooling, Power), Software (Performance), and Operations with no categories. */
export function buildStructureTree(): PlacementTree {
  const base = { project_id: STRUCTURE_PROJECT_ID };
  return {
    components: [
      { ...base, id: "c-hw", name: "Hardware", prefix: "HW", sort_order: 0 },
      { ...base, id: "c-sw", name: "Software", prefix: "SW", sort_order: 1 },
      { ...base, id: "c-ops", name: "Operations", prefix: "OPS", sort_order: 2 },
    ],
    categories: [
      { ...base, id: "k-cool", component_id: "c-hw", name: "Cooling", prefix: "COOL", sort_order: 0 },
      { ...base, id: "k-power", component_id: "c-hw", name: "Power", prefix: "PWR", sort_order: 1 },
      { ...base, id: "k-perf", component_id: "c-sw", name: "Performance", prefix: "PERF", sort_order: 0 },
    ],
  };
}

/** The server's suggestion, for a story: initials, first letters of one word, numbered among `used`. */
export function suggestFor(name: string, used: string[]): string {
  const words = name.normalize("NFKD").replace(/\p{M}/gu, "").split(/[^A-Za-z0-9]+/).filter(Boolean).map((w) => w.toUpperCase());
  const base = words.length === 0 ? "" : words.length === 1 ? words[0].slice(0, 6) : words.map((w) => w[0]).join("").slice(0, 6);
  if (!base) return "";
  const taken = new Set(used.map((u) => u.toUpperCase()));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(base + n)) n += 1;
  return base + n;
}

/** The counts of the tree above: Hardware holds 3 requirements, Software 2. */
export function buildStructureCounts(): StructureCounts {
  return {
    components: { "c-hw": { categories: 2, requirements: 3 }, "c-sw": { categories: 1, requirements: 2 }, "c-ops": { categories: 0, requirements: 0 } },
    categories: { "k-cool": 2, "k-power": 1, "k-perf": 2 },
  };
}

/**
 * A fake `StructureApi` over an in-memory tree.
 *
 * @param initial The starting tree (default {@link buildStructureTree}).
 * @param overrides Replace a method, for example to refuse a delete with 409.
 */
export function buildStructureApi(
  initial: PlacementTree = buildStructureTree(), overrides: Partial<StructureApi> = {},
): StructureApi {
  const tree: PlacementTree = { components: [...initial.components], categories: [...initial.categories] };
  let next = 1;
  const copy = (): PlacementTree => ({ components: [...tree.components], categories: [...tree.categories] });
  const siblings = (kind: StructureKind, id: string): Array<Component | Category> => {
    if (kind === "component") return tree.components;
    const category = tree.categories.find((c) => c.id === id);
    return tree.categories.filter((c) => c.component_id === category?.component_id);
  };
  return {
    tree: fn(async () => copy()),
    counts: fn(async () => buildStructureCounts()),
    suggestPrefix: fn(async (_p: string, request: SuggestionRequest) => {
      const used = request.kind === "component"
        ? tree.components.filter((c) => c.id !== request.ignore).map((c) => c.prefix)
        : tree.categories.filter((c) => c.component_id === request.componentId && c.id !== request.ignore).map((c) => c.prefix);
      return suggestFor(request.name, used);
    }),
    createComponent: fn(async (_p: string, values: NodeValues) => {
      if (tree.components.some((c) => c.prefix === values.prefix)) throw new ApiError(400, "A component with this prefix already exists.");
      const component: Component = { id: `c-new-${next++}`, project_id: STRUCTURE_PROJECT_ID, ...values, sort_order: tree.components.length };
      tree.components.push(component);
      return component;
    }),
    createCategory: fn(async (_p: string, componentId: string, values: NodeValues) => {
      if (tree.categories.some((c) => c.component_id === componentId && c.prefix === values.prefix)) {
        throw new ApiError(400, "A category with this prefix already exists under this component.");
      }
      const category: Category = {
        id: `k-new-${next++}`, project_id: STRUCTURE_PROJECT_ID, component_id: componentId, ...values,
        sort_order: tree.categories.filter((c) => c.component_id === componentId).length,
      };
      tree.categories.push(category);
      return category;
    }),
    update: fn(async (_p: string, kind: StructureKind, id: string, values: NodeValues) => {
      const list: Array<Component | Category> = kind === "component" ? tree.components : tree.categories;
      Object.assign(list.find((n) => n.id === id) ?? {}, values);
    }),
    move: fn(async (_p: string, kind: StructureKind, id: string, direction: "up" | "down") => {
      const list = siblings(kind, id);
      const index = list.findIndex((n) => n.id === id);
      const other = direction === "up" ? index - 1 : index + 1;
      if (other < 0 || other >= list.length) return;
      [list[index].sort_order, list[other].sort_order] = [list[other].sort_order, list[index].sort_order];
      list.sort((a, b) => a.sort_order - b.sort_order);
    }),
    moveCategoryTo: fn(async (_p: string, categoryId: string, componentId: string) => {
      const category = tree.categories.find((c) => c.id === categoryId);
      if (!category) return;
      if (tree.categories.some((c) => c.component_id === componentId && c.prefix === category.prefix)) {
        throw new ApiError(400, "A category with this prefix already exists under this component.");
      }
      category.component_id = componentId;
      category.sort_order = tree.categories.filter((c) => c.component_id === componentId).length;
    }),
    remove: fn(async (_p: string, kind: StructureKind, id: string) => {
      if (kind === "component") tree.components = tree.components.filter((c) => c.id !== id);
      else tree.categories = tree.categories.filter((c) => c.id !== id);
    }),
    ...overrides,
  };
}
