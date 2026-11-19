import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildReference, REFERENCE_SYSTEMS } from "../testing/referencesFixtures";
import { ReferenceFormModal } from "./ReferenceFormModal";

/** Adds or changes one external reference in a dialog over the shared `ReferenceFields`; Save needs a system and a key or a link. */
const meta: Meta<typeof ReferenceFormModal> = {
  title: "Components/ReferenceFormModal",
  component: ReferenceFormModal,
  args: { systems: REFERENCE_SYSTEMS, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ReferenceFormModal>;

export const AddingNeedsASystemAndAKeyOrALink: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add an external reference" }));
    const save = dialog.getByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "System" }), "Jira");
    await expect(save).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Link" }), "https://tracker.example/browse/PROJ-1");
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ systemId: "s-jira", url: "https://tracker.example/browse/PROJ-1" })));
  },
};

export const EditingStartsFromTheReference: Story = {
  args: { initial: buildReference({ role: "origin", note: "From the customer" }) },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit external reference" }));
    await expect(dialog.getByRole("combobox", { name: "System" })).toHaveValue("s-jira");
    await expect(dialog.getByRole("textbox", { name: "Key" })).toHaveValue("PROJ-1");
    await expect(dialog.getByRole("combobox", { name: "Role" })).toHaveValue("origin");
    await expect(dialog.getByRole("textbox", { name: "Note" })).toHaveValue("From the customer");
  },
};

export const ShowsASaveError: Story = {
  args: { error: "Could not save the reference: Not allowed." },
  play: async () => {
    await expect(await within(document.body).findByText("Could not save the reference: Not allowed.")).toBeInTheDocument();
  },
};
