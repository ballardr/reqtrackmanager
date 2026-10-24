import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { withToast } from "../testing/storybook-helpers";
import { SendPasswordResetDialog } from "./SendPasswordResetDialog";

const meta: Meta<typeof SendPasswordResetDialog> = {
  title: "Components/SendPasswordResetDialog",
  component: SendPasswordResetDialog,
  decorators: [withToast()],
  args: { userName: "Alex Morgan", endpoint: "/api/v1/orgs/org-1/users/u1/password-reset", onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof SendPasswordResetDialog>;

export const AsksFirst: Story = {
  play: async () => {
    const dialog = within(document.body).getByRole("dialog", { name: "Send a password reset link to Alex Morgan?" });
    await expect(within(dialog).getByText(/you will not see the link/)).toBeInTheDocument();
  },
};

export const SendsAndConfirms: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ args }) => {
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send link" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/users/u1/password-reset"));
    await expect(args.onClose).toHaveBeenCalled();
    await expect(within(document.body).getByText("Password reset link sent to Alex Morgan")).toBeInTheDocument();
  },
};

/** The server's reason is shown, e.g. the account signs in with single sign-on. */
export const ShowsTheServersReason: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(
      new ApiError(400, "This account signs in with single sign-on and has no password to reset."),
    );
  },
  play: async () => {
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send link" }));
    await waitFor(() => expect(within(document.body).getByText(/single sign-on/)).toBeInTheDocument());
  },
};

export const Cancel: Story = {
  play: async ({ args }) => {
    await userEvent.click(within(document.body).getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
  },
};
