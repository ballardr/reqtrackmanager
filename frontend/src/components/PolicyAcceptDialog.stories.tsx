import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildPendingPolicy, withPolicyAcceptance, withToast } from "../testing/storybook-helpers";
import { PolicyAcceptDialog } from "./PolicyAcceptDialog";

const reload = fn(async () => undefined);

/** The dialog that asks a person to accept a required policy: the text, and Accept in the header. */
const meta: Meta<typeof PolicyAcceptDialog> = {
  title: "Components/PolicyAcceptDialog",
  component: PolicyAcceptDialog,
  decorators: [withToast(), withPolicyAcceptance([], reload)],
  args: { policy: buildPendingPolicy(), onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof PolicyAcceptDialog>;

/** The full text, its organisation and version are shown, and Accept posts the version that was read. */
export const AcceptRecordsTheVersionRead: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue({ policy_id: "org-policy-1", version: 1, acknowledged_at: "2026-11-10T01:00:00Z" });
  },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "Confidentiality agreement" })).toBeInTheDocument();
    await expect(dialog.getByText("Keep what you learn here to yourself.")).toBeInTheDocument();
    await expect(dialog.getByText(/Version 1, published/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/policies/mine/org-policy-1/acknowledge", { version: 1 }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    await expect(await within(document.body).findByText("Policy accepted.")).toBeInTheDocument();
  },
};

/** When the text changed while the dialog was open the server refuses, the message is shown and nothing is recorded. */
export const AChangedTextIsNotAcceptedUnseen: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new Error("The policy has changed. Read the current version before accepting it."));
  },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(await dialog.findByRole("button", { name: "Accept" }));
    await expect(await within(document.body).findByText(/The policy has changed/)).toBeInTheDocument();
  },
};
