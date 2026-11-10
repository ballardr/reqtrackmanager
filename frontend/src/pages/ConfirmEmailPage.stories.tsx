import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { withRouter } from "../testing/storybook-helpers";
import { ConfirmEmailPage } from "./ConfirmEmailPage";

/** A confirmation link carries its secret in the URL fragment; set it before the page mounts. */
function openLink(fragment: string) {
  window.history.replaceState(null, "", `/confirm-email${fragment}`);
}

const meta: Meta<typeof ConfirmEmailPage> = {
  title: "Pages/ConfirmEmailPage",
  component: ConfirmEmailPage,
  decorators: [withRouter("/confirm-email")],
};
export default meta;

type Story = StoryObj<typeof ConfirmEmailPage>;

export const Confirmed: Story = {
  beforeEach: () => {
    openLink("#token=abc123abc123abc123abc123");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Your email address is confirmed. You can sign in now.")).toBeInTheDocument();
    await expect(api.post).toHaveBeenCalledWith("/api/v1/auth/confirm-email", { token: "abc123abc123abc123abc123" });
    await waitFor(() => expect(window.location.hash).toBe(""));
  },
};

export const InvalidLink: Story = {
  beforeEach: () => {
    openLink("#token=abc123abc123abc123abc123");
    spyOn(api, "post").mockRejectedValue(new ApiError(400, "This confirmation link is invalid or has expired."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("invalid or has expired");
  },
};

export const MissingLink: Story = {
  beforeEach: () => {
    openLink("");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("incomplete");
    await expect(api.post).not.toHaveBeenCalled();
  },
};
