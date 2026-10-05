import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildStakeholder } from "./fixtures";
import { StakeholderVisibilityControl } from "./StakeholderVisibilityControl";

const ORG_STAKEHOLDER = buildStakeholder({
  scope: "organization", organization_id: "org-1", project_id: null, project_hidden: false,
});

const meta: Meta<typeof StakeholderVisibilityControl> = {
  title: "Modules/Stakeholders/StakeholderVisibilityControl",
  component: StakeholderVisibilityControl,
  args: { stakeholder: ORG_STAKEHOLDER, onHide: fn(), onReset: fn() },
};
export default meta;

type Story = StoryObj<typeof StakeholderVisibilityControl>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const VisibleByDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Visible");
    await expect(canvas.getByText("Shared by the organisation")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Use inherited value" })).not.toBeInTheDocument();
  },
};

export const HideNeedsConfirmation: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Hide from this project" }));
    await expect(dialog().getByText(/Nothing is deleted/)).toBeInTheDocument();
    await expect(args.onHide).not.toHaveBeenCalled();
    await userEvent.click(dialog().getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.onHide).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CancellingLeavesItVisible: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Hide from this project" }));
    await userEvent.click(dialog().getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(args.onHide).not.toHaveBeenCalled();
  },
};

export const ShownDespiteParentCanBeReset: Story = {
  args: { stakeholder: { ...ORG_STAKEHOLDER, hidden_override: false, hidden_source: "project" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTestId("project-visibility")).toHaveTextContent("Shown, although a parent project hides it");
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await expect(args.onReset).toHaveBeenCalledTimes(1);
  },
};

export const LightTheme: Story = { ...VisibleByDefault };
export const DarkTheme: Story = { ...VisibleByDefault, globals: { theme: "dark" } };
