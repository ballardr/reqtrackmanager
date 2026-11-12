import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildConnection, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ConnectionDetailPage } from "./ConnectionDetailPage";

const meta: Meta<typeof ConnectionDetailPage> = {
  title: "Modules/Architecture/ConnectionDetailPage",
  component: ConnectionDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/connections/con-1`, "/projects/:projectId/modules/architecture/connections/:connectionId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ConnectionDetailPage>;

export const ShowsBothEndsWithPortsAndLinksToThem: Story = {
  beforeEach: () => { mockArchitectureReads({ connection: buildConnection() }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Client traffic/ })).toBeInTheDocument();
    const source = canvas.getByRole("link", { name: /ELM-001 Gateway \(HTTPS API\)/ });
    await expect(source).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/elements/el-1`);
    await expect(canvas.getByRole("link", { name: /ELM-002 Orders/ })).toBeInTheDocument();
    await expect(canvas.getByText("One-way, source to target")).toBeInTheDocument();
  },
};

/** An end the viewer can no longer read shows only its code, with no link. */
export const LockedEndShowsOnlyItsCode: Story = {
  beforeEach: () => {
    mockArchitectureReads({ connection: buildConnection({ target_locked: true, target_element_name: "" }) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Client traffic/ });
    await expect(canvas.getByText("(not visible)")).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /ELM-002/ })).not.toBeInTheDocument();
  },
};
