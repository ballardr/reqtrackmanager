import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { CustomFieldCreateModal } from "./CustomFieldCreateModal";

/** The dialog behind Project Administration's "New field" button. */
const meta: Meta<typeof CustomFieldCreateModal> = {
  title: "Components/CustomFieldCreateModal",
  component: CustomFieldCreateModal,
  args: { onCreate: fn(async () => true), onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof CustomFieldCreateModal>;

const body = () => within(document.body);

/** Only the name is required; Add waits for it and the options field appears for a list only. */
export const OpenWithTheNameRequired: Story = {
  play: async () => {
    const dialog = within(await body().findByRole("dialog", { name: "New field" }));
    await expect(requiredCaptions(document.body)).toEqual(["Field name"]);
    await expect(dialog.getByRole("button", { name: "Add" })).toBeDisabled();
    await expect(dialog.queryByRole("textbox", { name: "Options (comma separated)" })).not.toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Field type" }), "list");
    await expect(dialog.getByRole("textbox", { name: "Options (comma separated)" })).toBeInTheDocument();
  },
};

export const CreatesAListFieldAndCloses: Story = {
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "New field" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Field name" }), "Severity");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Field type" }), "list");
    await userEvent.type(dialog.getByRole("textbox", { name: "Options (comma separated)" }), "Low, High");
    await userEvent.click(dialog.getByRole("checkbox", { name: "required" }));
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.onCreate).toHaveBeenCalledWith({
      entityKind: "requirement", name: "Severity", fieldType: "list", options: "Low, High", required: true,
    }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

export const ARefusedCreateKeepsTheDialogOpen: Story = {
  args: { onCreate: fn(async () => false) },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "New field" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Field name" }), "Severity");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.onCreate).toHaveBeenCalled());
    await expect(args.onClose).not.toHaveBeenCalled();
    await expect(dialog.getByRole("textbox", { name: "Field name" })).toHaveValue("Severity");
  },
};
