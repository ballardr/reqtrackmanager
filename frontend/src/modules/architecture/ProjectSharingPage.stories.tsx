import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectSharingPage } from "./ProjectSharingPage";

const meta: Meta<typeof ProjectSharingPage> = {
  title: "Modules/Architecture/ProjectSharingPage",
  component: ProjectSharingPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/sharing`, "/projects/:projectId/modules/architecture/sharing"),
    withToast(),
  ],
  beforeEach: () => { mockArchitectureReads(); },
};
export default meta;

type Story = StoryObj<typeof ProjectSharingPage>;

export const ShowsTheCollectionsAndLinksBackToTheElements: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Shared infrastructure" })).toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Sharing", level: 1 })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Elements" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture?tab=elements`);
  },
};
