import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import { buildUsage, buildVocabulary } from "../testing/tagsFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ProjectTagsPanel } from "./ProjectTagsPanel";

/** Project Admin's Tags section: the tag admin bound to one project's own vocabulary. */
const meta: Meta<typeof ProjectTagsPanel> = {
  title: "Components/ProjectTagsPanel",
  component: ProjectTagsPanel,
  decorators: [withToast()],
  args: { projectId: "project-1" },
};
export default meta;

type Story = StoryObj<typeof ProjectTagsPanel>;

export const ReadsTheProjectsOwnVocabularyAndUsage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/projects/project-1/tags") return buildVocabulary({ has_parent: true });
      if (path === "/api/v1/projects/project-1/tags/usage") return buildUsage();
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("table", { name: "Tags" })).toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Follow the parent project" })).toBeInTheDocument();
  },
};
