import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { ForcedPasswordChangePage } from "./ForcedPasswordChangePage";

const meta: Meta<typeof ForcedPasswordChangePage> = {
  title: "Pages/ForcedPasswordChangePage",
  component: ForcedPasswordChangePage,
  decorators: [withAuth(buildUser({ must_change_password: true })), withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof ForcedPasswordChangePage>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Choose your own password" })).toBeInTheDocument();
    await expect(requiredCaptions(canvasElement)).toEqual(["Current password", "New password", "Confirm new password"]);
    await expect(canvas.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  },
};

export const ChangesThePassword: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^Current password/), "Given-By-Admin-1!");
    await userEvent.type(canvas.getByLabelText(/^New password/), "Chosen-By-Person-7!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "Chosen-By-Person-7!");
    await userEvent.click(canvas.getByRole("button", { name: "Change password" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/auth/change-password", {
        current_password: "Given-By-Admin-1!",
        new_password: "Chosen-By-Person-7!",
      }),
    );
  },
};

export const PasswordsDiffer: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^Current password/), "Given-By-Admin-1!");
    await userEvent.type(canvas.getByLabelText(/^New password/), "Chosen-By-Person-7!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "Different-Password-8!");
    await userEvent.click(canvas.getByRole("button", { name: "Change password" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The two passwords do not match.");
    await expect(api.post).not.toHaveBeenCalled();
  },
};

export const RefusedPassword: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new ApiError(401, "Current password is incorrect."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText(/^Current password/), "Wrong-Password-1!");
    await userEvent.type(canvas.getByLabelText(/^New password/), "Chosen-By-Person-7!");
    await userEvent.type(canvas.getByLabelText(/^Confirm new password/), "Chosen-By-Person-7!");
    await userEvent.click(canvas.getByRole("button", { name: "Change password" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("Current password is incorrect.");
  },
};
