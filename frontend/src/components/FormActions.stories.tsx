import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { FormActions } from "./FormActions";

const meta: Meta<typeof FormActions> = { title: "Components/FormActions", component: FormActions };
export default meta;

type Story = StoryObj<typeof FormActions>;

export const SaveAndCancelReportClicks: Story = {
  args: { onCancel: fn(), onSave: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await expect(args.onSave).toHaveBeenCalledTimes(1);
    await expect(args.onCancel).toHaveBeenCalledTimes(1);
  },
};

export const InvalidFormDisablesSave: Story = {
  args: { onCancel: fn(), onSave: fn(), saveDisabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

export const ShowsTheSaveErrorAndACustomLabel: Story = {
  args: { onCancel: fn(), onSave: fn(), error: "A decision with that title already exists.", saveLabel: "Create" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("A decision with that title already exists.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Create" })).toBeEnabled();
  },
};

export const SaveAndActivateIsASeparateButtonBesideSave: Story = {
  args: { onCancel: fn(), onSave: fn(), onSaveAndActivate: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Save and activate" }));
    await expect(args.onSaveAndActivate).toHaveBeenCalledTimes(1);
    await expect(args.onSave).not.toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledTimes(1);
  },
};

export const InvalidFormDisablesSaveAndActivateToo: Story = {
  args: { onCancel: fn(), onSave: fn(), onSaveAndActivate: fn(), saveDisabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Save and activate" })).toBeDisabled();
  },
};

export const DarkTheme: Story = { ...ShowsTheSaveErrorAndACustomLabel, globals: { theme: "dark" } };
