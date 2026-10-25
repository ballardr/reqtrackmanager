import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { requiredCaptions } from "../testing/requiredMarkers";
import { withRouter } from "../testing/storybook-helpers";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

const meta: Meta<typeof ForgotPasswordPage> = {
  title: "Pages/ForgotPasswordPage",
  component: ForgotPasswordPage,
  decorators: [withRouter("/forgot-password")],
};
export default meta;

type Story = StoryObj<typeof ForgotPasswordPage>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/login");
    // Required fields: the email is all the form blocks on.
    await expect(requiredCaptions(canvasElement)).toEqual(["Email"]);
  },
};

/** The confirmation is the same for every address; the page never says whether an account exists. */
export const RequestSent: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue({ detail: "ok" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/Email/), "alex@example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Send reset link" }));
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent(/reset link is on its way/));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/auth/forgot-password", { email: "alex@example.com" });
    await expect(canvas.queryByLabelText(/Email/)).not.toBeInTheDocument();
  },
};

export const RateLimited: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new ApiError(429, "Too many attempts. Wait 30 seconds and try again."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/Email/), "alex@example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Send reset link" }));
    await waitFor(() => expect(canvas.getByText(/Too many attempts/)).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
