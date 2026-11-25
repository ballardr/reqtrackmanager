import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildServiceUser, ORG_ID } from "../testing/serviceUserFixtures";
import { ServiceUserFormModal } from "./ServiceUserFormModal";

/** Creates or edits a service user over the one shared field group; only the name is required. */
const meta: Meta<typeof ServiceUserFormModal> = {
  title: "Components/ServiceUserFormModal",
  component: ServiceUserFormModal,
  args: { organizationId: ORG_ID, onCancel: fn(), onSave: fn() },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
};
export default meta;

type Story = StoryObj<typeof ServiceUserFormModal>;

/** The name is the only required field; Create stays disabled until it is filled and sends the draft. */
export const CreateNeedsAName: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New service user" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    const create = dialog.getByRole("button", { name: "Create" });
    await expect(create).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Build agent");
    await expect(create).toBeEnabled();
    await userEvent.click(create);
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Build agent", email: "", responsible: null })));
  },
};

/** Editing starts from the stored values; a generated address is shown as a blank field. */
export const EditStartsFromTheStoredValues: Story = {
  args: { initial: buildServiceUser() },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit service user" }));
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Build agent");
    await expect(dialog.getByRole("textbox", { name: "Notification email address" })).toHaveValue("");
    await expect(dialog.getByRole("textbox", { name: "Description" })).toHaveValue("Runs the nightly import.");
    await expect(dialog.getByText("Platform team")).toBeInTheDocument();
  },
};

export const ShowsASaveError: Story = {
  args: { error: "A service user with this name already exists in this organisation." },
  play: async () => {
    await expect(await within(document.body).findByText("A service user with this name already exists in this organisation.")).toBeInTheDocument();
  },
};
