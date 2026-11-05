import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ReferenceFormModal } from "./ReferenceFormModal";
import { buildExternalRef, SYSTEM_CHOICES } from "./requestFixtures";
import { requiredCaptions } from "../../testing/requiredMarkers";

const meta: Meta<typeof ReferenceFormModal> = {
  title: "Modules/ProductFeedback/ReferenceFormModal",
  component: ReferenceFormModal,
  args: { systems: SYSTEM_CHOICES, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ReferenceFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Saving needs a system and a key or a link; the system is the only field marked required. */
export const AddNeedsASystemAndAKeyOrALink: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(document.body)).toEqual(["System"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Reference system"), "system-servicenow");
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Reference key"), "INC0012345");
    await userEvent.selectOptions(d.getByLabelText("Reference role"), "origin");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({ systemId: "system-servicenow", key: "INC0012345", url: "", role: "origin" });
  },
};

/** Editing starts from the reference's own values. */
export const EditStartsFromTheReference: Story = {
  args: { initial: buildExternalRef() },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Reference system")).toHaveValue("system-jira");
    await expect(d.getByLabelText("Reference key")).toHaveValue("PROJ-123");
    await expect(d.getByLabelText("Reference link")).toHaveValue("https://jira.example.com/browse/PROJ-123");
    await expect(d.getByRole("heading", { name: "Edit reference" })).toBeInTheDocument();
  },
};
