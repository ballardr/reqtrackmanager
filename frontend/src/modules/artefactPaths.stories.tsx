import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildNotification } from "../testing/storybook-helpers";
import { getArtefactListPath, getArtefactPath, getArtefactStatusLabel, getNotificationLink, getSearchHitPath, isArtefactInactive } from "./artefactPaths";
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

/**
 * Guard: every type the project overview counts opens a list from its chart, so a module that registers a type
 * must declare where its list is. The three Compliance types derived from an assigned standard are not counted.
 */
export const EveryCountedArtefactTypeHasAListPage: Story = {
  render: () => <div>Artefact type list pages</div>,
  play: async () => {
    const notCounted = new Set(["compliance_requirement", "project_compliance_requirement", "compliance_required_action_assessment"]);
    const missing = registeredArtefactTypes.filter((type) => !notCounted.has(type) && getArtefactListPath(type, "p-1") === null);
    await expect(missing).toEqual([]);
    await expect(getArtefactListPath("requirement", "p-1")).toBe("/projects/p-1/requirements");
    await expect(getArtefactListPath("risk", "p-1")).toBe("/projects/p-1/modules/risk_management/risks");
    await expect(getArtefactListPath("not_a_type", "p-1")).toBeNull();
  },
};

export const ResolvesCoreAndModulePaths: Story = {
  render: () => <div>Artefact type routes</div>,
  play: async () => {
    await expect(getArtefactPath("requirement", "p-1", "r-1")).toBe("/projects/p-1/requirements/r-1");
    await expect(getArtefactPath("requirement_action", "p-1", "a-1")).toBe("/projects/p-1/actions/a-1");
    await expect(getArtefactPath("change_request", "p-1", "c-1")).toBe("/projects/p-1/change-requests/c-1");
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

/** A notification about a module-owned record opens that record via the module's `artefactPaths`; core types keep their routes. */
export const ResolvesNotificationLinks: Story = {
  render: () => <div>Notification links</div>,
  play: async () => {
    const link = (entity_type: string | null, project_id: string | null = "p-1", entity_id: string | null = "x-1") =>
      getNotificationLink(buildNotification({ entity_type, entity_id, project_id }));
    await expect(link("risk")).toBe("/projects/p-1/modules/risk_management/risks/x-1");
    await expect(link("requirement")).toBe("/projects/p-1/requirements/x-1");
    await expect(link("change_request")).toBe("/projects/p-1/change-requests/x-1");
    await expect(link("not_a_type")).toBe("/projects/p-1");
    await expect(link("risk", null)).toBeNull();
  },
};

/** A search result is never a dead row: every registered type opens a page, a finding opens its engagement and a project opens itself. */
export const EverySearchResultOpensAPage: Story = {
  render: () => <div>Search results</div>,
  play: async () => {
    const dead = registeredArtefactTypes.filter(
      (type) => getSearchHitPath({ open_type: type, open_id: "id-1", open_project_id: "p-1" }) === null,
    );
    await expect(dead).toEqual([]);
    await expect(getSearchHitPath({ open_type: "project", open_id: "p-9", open_project_id: "p-9" })).toBe("/projects/p-9");
    await expect(getSearchHitPath({ open_type: "engagement", open_id: "e-1", open_project_id: "p-1" })).toBe(
      getArtefactPath("engagement", "p-1", "e-1"),
    );
    // A record with no project to open it in has no page...
    await expect(getSearchHitPath({ open_type: "requirement", open_id: "r-1", open_project_id: null })).toBeNull();
    // ...unless it belongs to the organisation and its module gives it an organisation page.
    await expect(getSearchHitPath({ open_type: "strategy", open_id: "s-1", open_project_id: null, organization_id: "o-1" })).toBe(
      "/orgs/o-1/modules/context_strategy/strategies/s-1",
    );
  },
};
