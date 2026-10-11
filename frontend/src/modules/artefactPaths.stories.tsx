import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { getArtefactPath, getArtefactStatusLabel, isArtefactInactive } from "./artefactPaths";
import { installedModules } from "./registry";
import registeredArtefactTypes from "./registeredArtefactTypes.json";

/**
 * Guard: every artefact type the backend registers must resolve to a page, so a
 * type can never be linkable yet unreachable. `registeredArtefactTypes.json` is
 * kept equal to the backend registry by `backend/tests/test_artefact_type_routes.py`;
 * adding a type fails that test until the file is updated, and this story fails
 * until the type's module declares an `artefactPaths` entry for it.
 */
const meta: Meta = { title: "Modules/ArtefactPaths" };
export default meta;

type Story = StoryObj;

export const EveryRegisteredArtefactTypeHasARoute: Story = {
  render: () => <div>Artefact type routes</div>,
  play: async () => {
    const unreachable = registeredArtefactTypes.filter((type) => getArtefactPath(type, "p-1", "id-1") === null);
    await expect(unreachable).toEqual([]);
  },
};

export const ResolvesCoreAndModulePaths: Story = {
  render: () => <div>Artefact type routes</div>,
  play: async () => {
    await expect(getArtefactPath("requirement", "p-1", "r-1")).toBe("/projects/p-1/requirements/r-1");
    await expect(getArtefactPath("requirement_action", "p-1", "a-1")).toBe("/projects/p-1/actions/a-1");
    await expect(getArtefactPath("decision", "p-1", "d-1")).toBe("/projects/p-1/modules/decisions/d-1");
    await expect(getArtefactPath("not_a_type", "p-1", "x")).toBeNull();
  },
};

export const InactiveStatusesAreRealLabelledStatuses: Story = {
  render: () => <div>Inactive statuses</div>,
  play: async () => {
    // A module cannot declare a status inactive that its own label map does not know (a typo would hide nothing, silently).
    const unknown: string[] = [];
    for (const module of installedModules) {
      for (const [type, statuses] of Object.entries(module.artefactInactiveStatuses ?? {})) {
        for (const status of statuses) if (getArtefactStatusLabel(type, status) === null) unknown.push(`${type}:${status}`);
      }
    }
    await expect(unknown).toEqual([]);
  },
};

export const ResolvesInactiveRecords: Story = {
  render: () => <div>Inactive statuses</div>,
  play: async () => {
    await expect(isArtefactInactive("decision", "superseded", false)).toBe(true);
    await expect(isArtefactInactive("decision", "approved", false)).toBe(false);
    await expect(isArtefactInactive("decision", "approved", true)).toBe(true);
    await expect(isArtefactInactive("requirement", "archived", false)).toBe(true);
    await expect(isArtefactInactive("requirement", "approved", false)).toBe(false);
    await expect(isArtefactInactive("stakeholder", "retired", false)).toBe(true);
    await expect(isArtefactInactive("not_a_type", "superseded", false)).toBe(false);
    await expect(isArtefactInactive("decision", null, false)).toBe(false);
  },
};
