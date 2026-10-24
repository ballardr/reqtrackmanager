import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { requiredCaptions } from "../testing/requiredMarkers";
import { withRouter } from "../testing/storybook-helpers";
import { ResetPasswordPage } from "./ResetPasswordPage";

/** A reset link carries its secret in the URL fragment; set it before the page mounts. */
function openLink(fragment: string) {
  window.history.replaceState(null, "", `/reset-password${fragment}`);
}

const meta: Meta<typeof ResetPasswordPage> = {
  title: "Pages/ResetPasswordPage",
  component: ResetPasswordPage,
  decorators: [withRouter("/reset-password")],
};
export default meta;

type Story = StoryObj<typeof ResetPasswordPage>;

export const WithLink: Story = {
  beforeEach: () => openLink("#token=abc123abc123abc123abc123"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Choose a new password" })).toBeInTheDocument();
    await expect(requiredCaptions(canvasElement)).toEqual(["New password", "Confirm new password"]);
    // The secret is removed from the address bar as soon as the page has read it.
    await waitFor(() => expect(window.location.hash).toBe(""));
  },
};

export const SetsThePassword: Story = {
  beforeEach: () => {
    openLink("#token=abc123abc123abc123abc123");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^New password/), "BrandNewPassw0rd!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "BrandNewPassw0rd!");
    await userEvent.click(canvas.getByRole("button", { name: "Set new password" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/auth/reset-password", {
        token: "abc123abc123abc123abc123",
        new_password: "BrandNewPassw0rd!",
      }),
    );
  },
};

export const PasswordsDiffer: Story = {
  beforeEach: () => {
    openLink("#token=abc123abc123abc123abc123");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^New password/), "BrandNewPassw0rd!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "SomethingElse123");
    await userEvent.click(canvas.getByRole("button", { name: "Set new password" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("The two passwords do not match.");
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** An expired, used or unknown link: one message, with a way to ask for a new one. */
export const LinkRejected: Story = {
  beforeEach: () => {
    openLink("#token=abc123abc123abc123abc123");
    spyOn(api, "post").mockRejectedValue(new ApiError(400, "This reset link is invalid or has expired."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^New password/), "BrandNewPassw0rd!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "BrandNewPassw0rd!");
    await userEvent.click(canvas.getByRole("button", { name: "Set new password" }));
    await waitFor(() => expect(canvas.getByRole("alert")).toHaveTextContent("invalid or has expired"));
    await expect(canvas.getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
  },
};

export const MissingLink: Story = {
  beforeEach: () => openLink(""),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent("incomplete");
    await expect(canvas.queryByLabelText(/^New password/)).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WithLink, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WithLink, globals: { theme: "dark" } };
