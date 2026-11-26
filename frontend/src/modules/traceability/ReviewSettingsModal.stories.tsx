import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DANA, ORG_ID, ORG_USERS, ORG_USERS_URL } from "./policyFixtures";
import { ReviewSettingsModal } from "./ReviewSettingsModal";

const meta: Meta<typeof ReviewSettingsModal> = {
  title: "Modules/Governance/ReviewSettingsModal",
  component: ReviewSettingsModal,
  args: {
    typeLabel: "Requirement",
    initial: { interval_days: 90, lead_days: 14, default_owner: { type: "user", id: "user-1" } },
    ownerDisplay: DANA, orgUsers: ORG_USERS, organizationId: ORG_ID, onSave: fn(async () => undefined), onClose: fn(),
  },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === ORG_USERS_URL) return ORG_USERS;
      return [];
    });
  },
};
export default meta;

type Story = StoryObj<typeof ReviewSettingsModal>;

const dialog = async () => within(await within(document.body).findByRole("dialog", { name: "Edit review settings: Requirement" }));

export const SavesTheEditedSettings: Story = {
  play: async ({ args }) => {
    const modal = await dialog();
    const interval = modal.getByLabelText("Review interval (days)");
    await userEvent.clear(interval);
    await userEvent.type(interval, "45");
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith({ interval_days: 45, lead_days: 14, default_owner: { type: "user", id: "user-1" } }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

export const AnOutOfRangeNumberCannotBeSaved: Story = {
  play: async () => {
    const modal = await dialog();
    const interval = modal.getByLabelText("Review interval (days)");
    await userEvent.clear(interval);
    await userEvent.type(interval, "9999");
    await expect(modal.getByRole("button", { name: "Save" })).toBeDisabled();
    await expect(modal.getByText(/whole number of days from 1 to 3650/)).toBeInTheDocument();
  },
};

export const UseInheritedValueSavesNull: Story = {
  args: { allowFollowParent: true },
  play: async ({ args }) => {
    const modal = await dialog();
    await userEvent.click(modal.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(null));
  },
};

export const WithoutAnInheritedValueThereIsNoWayBack: Story = {
  play: async () => {
    const modal = await dialog();
    await expect(modal.queryByRole("button", { name: "Use inherited value" })).not.toBeInTheDocument();
  },
};

export const AFailedSaveIsShownAndKeepsTheDialogOpen: Story = {
  args: { onSave: fn(async () => { throw new Error("Not allowed."); }) },
  play: async ({ args }) => {
    const modal = await dialog();
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await expect(await modal.findByText("Not allowed.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

export const DarkTheme: Story = { ...SavesTheEditedSettings, globals: { theme: "dark" }, play: async () => { await dialog(); } };
