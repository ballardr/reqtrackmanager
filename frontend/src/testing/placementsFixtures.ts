/**
 * Fixtures for the component/placement stories: a small project tree, one record's places, and a fake
 * `RecordPlacementsApi` whose methods are `fn()` spies, so a story can assert what was called without a network.
 */
import { fn, userEvent, within } from "storybook/test";

import type { Placement, PlacementPair, PlacementTree, RecordPlacements, RecordPlacementsApi } from "../api/placements";

export const PLACEMENTS_PROJECT_ID = "project-1";

/** Hardware (with Cooling and Power) and Software (no categories). */
export function buildTree(): PlacementTree {
  const base = { project_id: PLACEMENTS_PROJECT_ID };
  return {
    components: [
      { ...base, id: "c-hw", name: "Hardware", prefix: "HW", sort_order: 0 },
      { ...base, id: "c-sw", name: "Software", prefix: "SW", sort_order: 1 },
    ],
    categories: [
      { ...base, id: "k-cool", component_id: "c-hw", name: "Cooling", prefix: "COOL", sort_order: 0 },
      { ...base, id: "k-power", component_id: "c-hw", name: "Power", prefix: "PWR", sort_order: 1 },
    ],
  };
}

/** A place with its names. */
export function buildPlace(componentId: string, categoryId: string | null = null): Placement {
  const tree = buildTree();
  return {
    component_id: componentId,
    category_id: categoryId,
    component_name: tree.components.find((c) => c.id === componentId)!.name,
    category_name: categoryId ? tree.categories.find((c) => c.id === categoryId)!.name : null,
  };
}

/** One record's places and what its picker needs. */
export function buildRecordPlacements(overrides: Partial<RecordPlacements> = {}): RecordPlacements {
  return { placements: [buildPlace("c-hw", "k-cool")], can_edit: true, managed_on_record: false, ...overrides };
}

/** A fake `RecordPlacementsApi`; `set` echoes the places back with their names. */
export function buildPlacementsApi(
  data: RecordPlacements = buildRecordPlacements(), overrides: Partial<RecordPlacementsApi> = {},
): RecordPlacementsApi {
  return {
    get: fn(async () => data),
    set: fn(async (_p: string, _t: string, _i: string, places: PlacementPair[]) => ({
      ...data, placements: places.map((p) => buildPlace(p.component_id, p.category_id)),
    })),
    tree: fn(async () => buildTree()),
    page: fn(async () => ({})),
    ...overrides,
  };
}

/** Opens the place picker inside `scope` and returns the list popover (portalled to `document.body`). */
export async function openPlacementPicker(scope: ReturnType<typeof within>): Promise<void> {
  await userEvent.click(await scope.findByRole("button", { name: "Components and categories" }));
}
