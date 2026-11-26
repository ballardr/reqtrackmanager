import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DEFAULT_PROFILE, ORG_ID, ORG_PROJECTS } from "./profileFixtures";
import { ProfileFormModal } from "./ProfileFormModal";

const URL = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles`;

const meta: Meta<typeof ProfileFormModal> = {
  title: "Modules/Governance/ProfileFormModal",
  component: ProfileFormModal,
  args: { orgId: ORG_ID, onCreated: fn(), onClose: fn() },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_PROJECTS);
  },
};
export default meta;

type Story = StoryObj<typeof ProfileFormModal>;

const dialog = () => within(document.body).findByRole("dialog", { name: "New profile" });

/** The dialog starts as a Default profile for every project; Create stays unavailable until the profile is named. */
export const CreateNeedsAName: Story = {
  play: async () => {
    const form = within(await dialog());
    await expect(form.getByRole("combobox", { name: "Mode" })).toHaveValue("default");
    await expect(form.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.type(form.getByRole("textbox", { name: "Name" }), "Safety critical");
    await expect(form.getByRole("button", { name: "Create" })).toBeEnabled();
  },
};

/** Create sends the profile with its mode and reach, toasts the outcome and hands the profile on. */
export const CreatesTheProfile: Story = {
  play: async ({ args }) => {
    spyOn(api, "post").mockResolvedValue(DEFAULT_PROFILE);
    const form = within(await dialog());
    await userEvent.type(form.getByRole("textbox", { name: "Name" }), "Standard review");
    await userEvent.selectOptions(form.getByRole("combobox", { name: "Mode" }), "enforced");
    await userEvent.click(form.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(URL, {
      name: "Standard review", description: "", mode: "enforced", target_kind: "all_projects", targets: [],
    }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith(DEFAULT_PROFILE));
    await expect(await within(document.body).findByText("Profile created.")).toBeInTheDocument();
  },
};

/** A refused create reports the server's message in a toast and keeps the dialog open. */
export const FailureStaysOpen: Story = {
  play: async ({ args }) => {
    spyOn(api, "post").mockRejectedValue(new Error("A profile with this name already exists."));
    const form = within(await dialog());
    await userEvent.type(form.getByRole("textbox", { name: "Name" }), "Standard review");
    await userEvent.click(form.getByRole("button", { name: "Create" }));
    await expect(await within(document.body).findByText("A profile with this name already exists.")).toBeInTheDocument();
    await expect(args.onCreated).not.toHaveBeenCalled();
  },
};

export const DarkTheme: Story = { globals: { theme: "dark" } };
