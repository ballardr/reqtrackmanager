import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { RestoreOrgDefaultsButton } from "./RestoreOrgDefaultsButton";

const HIDDEN = [
  { id: "a", name: "Market" },
  { id: "b", name: "User" },
];

const meta: Meta<typeof RestoreOrgDefaultsButton> = {
  title: "Components/RestoreOrgDefaultsButton",
  component: RestoreOrgDefaultsButton,
  args: { hidden: HIDDEN, noun: "Pain Point types", onRestore: fn(async () => {}) },
};
export default meta;

type Story = StoryObj<typeof RestoreOrgDefaultsButton>;

export const NothingHiddenRendersNothing: Story = {
  args: { hidden: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

export const RestoresEverythingByDefault: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add organisation defaults (2)" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Add organisation defaults" }));
    await expect(dialog.getByRole("checkbox", { name: "Market" })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: "User" })).toBeChecked();
    await userEvent.click(dialog.getByRole("button", { name: "Add 2 defaults" }));
    await waitFor(() => expect(args.onRestore).toHaveBeenCalledWith(["a", "b"]));
  },
};

export const RestoresOnlyTheTickedOnesAndNeedsAtLeastOne: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add organisation defaults (2)" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.click(dialog.getByRole("checkbox", { name: "Market" }));
    await userEvent.click(dialog.getByRole("checkbox", { name: "User" }));
    await expect(dialog.getByRole("button", { name: "Add 0 defaults" })).toBeDisabled();
    await userEvent.click(dialog.getByRole("checkbox", { name: "User" }));
    await userEvent.click(dialog.getByRole("button", { name: "Add 1 default" }));
    await waitFor(() => expect(args.onRestore).toHaveBeenCalledWith(["b"]));
  },
};

export const FailureStaysInTheDialog: Story = {
  args: { onRestore: fn(async () => { throw new Error("Could not reach the server."); }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add organisation defaults (2)" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Add 2 defaults" }));
    await expect(await dialog.findByText("Could not reach the server.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...RestoresEverythingByDefault, globals: { theme: "dark" } };
