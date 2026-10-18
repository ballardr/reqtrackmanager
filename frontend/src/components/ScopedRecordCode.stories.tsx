import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization } from "../api/types";
import { ProjectContext } from "../context/ProjectContextValue";
import { buildUser, withAuth } from "../testing/storybook-helpers";
import { ScopedRecordCode } from "./ScopedRecordCode";

const meta: Meta<typeof ScopedRecordCode> = {
  title: "Components/ScopedRecordCode",
  component: ScopedRecordCode,
};
export default meta;
type Story = StoryObj<typeof ScopedRecordCode>;

function inProject(Story: () => React.ReactElement) {
  return (
    <ProjectContext.Provider
      value={{ terminology: {}, projectCode: "PRJ", enforceCodeEverywhere: false, organizationId: "org-1", organizationCode: "ACME" }}
    >
      <Story />
    </ProjectContext.Provider>
  );
}

/** A project-scoped record follows the ordinary project-code rule. */
export const ProjectScoped: Story = {
  args: { record: { unique_code: "PER-001", scope: "project", organization_id: null } },
  decorators: [inProject, withAuth(buildUser())],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("PRJ-PER-001")).toBeInTheDocument();
  },
};

/** A record the organisation owns is qualified by the organisation's code, even when the viewer prefers bare codes. */
export const OrganisationOwnedInAProject: Story = {
  args: { record: { unique_code: "PER-001", scope: "organization", organization_id: "org-1" } },
  decorators: [inProject, withAuth(buildUser({ ui_preferences: { show_project_code: false } }))],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("ACME-PER-001")).toBeInTheDocument();
  },
};

/** On an organisation page there is no project; the organisation's code is fetched once. */
export const OrganisationOwnedOnAnOrganisationPage: Story = {
  args: { record: { unique_code: "STR-004", scope: "organization", organization_id: "org-fetched" } },
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ id: "org-fetched", code: "GLOBEX" } as Organization);
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("GLOBEX-STR-004")).toBeInTheDocument();
  },
};

/** A record with no scope (a project-only type) is project-scoped. */
export const NoScope: Story = {
  args: { record: { unique_code: "NEED-002" } },
  decorators: [inProject, withAuth(buildUser())],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("PRJ-NEED-002")).toBeInTheDocument();
  },
};
