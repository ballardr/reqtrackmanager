import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { FormActions } from "./FormActions";
import { Modal } from "./Modal";

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

export const CancelOnlyHasNoPrimaryButton: Story = {
  args: { onCancel: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Cancel" })).toBeEnabled();
    await expect(canvas.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  },
};

export const DangerToneAndDisabledCancelWhileBusy: Story = {
  args: { onCancel: fn(), onSave: fn(), saveLabel: "Reject", saveTone: "danger", cancelDisabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Reject" })).toHaveClass("btn-danger");
    await expect(canvas.getByRole("button", { name: "Cancel" })).toBeDisabled();
  },
};

/** In a dialog the header's close button is the way out, so FormActions shows Save but no Cancel. */
export const InADialogThereIsNoCancel: Story = {
  render: () => (
    <Modal title="New thing" onClose={fn()}>
      <FormActions onCancel={fn()} onSave={fn()} />
    </Modal>
  ),
  play: async () => {
    const dialog = within(document.body).getByRole("dialog", { name: "New thing" });
    await expect(within(dialog).getByRole("button", { name: "Save" })).toBeInTheDocument();
    await expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsTheSaveErrorAndACustomLabel, globals: { theme: "dark" } };
