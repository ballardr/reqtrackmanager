import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { LifecycleRequiredModal } from "./LifecycleRequiredModal";

const meta: Meta<typeof LifecycleRequiredModal> = {
  title: "Modules/Governance/LifecycleRequiredModal",
  component: LifecycleRequiredModal,
  args: {
    typeLabel: "Risk",
    states: [{ key: "assessed", label: "Assessed" }, { key: "treated", label: "Treated" }],
    initial: ["assessed"],
    onSave: fn(async () => undefined),
    onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof LifecycleRequiredModal>;

const dialog = () => within(document.body).findByRole("dialog", { name: "Required states: Risk" });

/** The states required now are ticked; saving sends the chosen keys in path order. */
export const SavesTheChosenStates: Story = {
  play: async ({ args }) => {
    const modal = within(await dialog());
    await expect(modal.getByRole("checkbox", { name: "Assessed" })).toBeChecked();
    await userEvent.click(modal.getByRole("checkbox", { name: "Treated" }));
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(["assessed", "treated"]));
  },
};

/** Clearing every box saves an empty set, which removes the requirement. */
export const ClearingRemovesTheRequirement: Story = {
  play: async ({ args }) => {
    const modal = within(await dialog());
    await userEvent.click(modal.getByRole("checkbox", { name: "Assessed" }));
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith([]));
  },
};

/** A failed save stays in the dialog with the reason. */
export const ShowsAFailedSave: Story = {
  args: { onSave: fn(async () => { throw new Error("The profile was deleted."); }) },
  play: async () => {
    const modal = within(await dialog());
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await expect(await modal.findByText("The profile was deleted.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...SavesTheChosenStates, globals: { theme: "dark" } };
