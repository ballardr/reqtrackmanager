import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { MoveToProjectDialog } from "./MoveToProjectDialog";

const meta: Meta<typeof MoveToProjectDialog> = {
  title: "Modules/ProductFeedback/MoveToProjectDialog",
  component: MoveToProjectDialog,
  args: { code: "ENH-003", projects: [{ id: "p1", name: "Apollo" }, { id: "p2", name: "Gemini" }], onMove: fn(), onCancel: fn() },
};
export default meta;

type Story = StoryObj<typeof MoveToProjectDialog>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const NeedsAProjectAndWarnsItIsOneWay: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByText(/cannot be undone/)).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Move" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Project"), "p2");
    await userEvent.click(d.getByRole("button", { name: "Move" }));
    await expect(args.onMove).toHaveBeenCalledWith("p2");
  },
};

export const ShowsTheServersRefusal: Story = {
  args: { error: "Request has links and cannot be moved." },
  play: async () => {
    await expect(dialog().getByRole("alert")).toHaveTextContent("Request has links and cannot be moved.");
  },
};
