import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { SignupConfig } from "../api/types";
import { buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { SignupPage } from "./SignupPage";

function mockSignupConfig(config: SignupConfig) {
  spyOn(api, "get").mockResolvedValue(config);
}

// Stable mock reference, reconfigured per-story via `beforeEach` — see
// LoginPage.stories.tsx's `loginMock` comment for why a fresh `fn()` per
// story's own `decorators` array isn't safe here (Vitest browser mode
// doesn't fully remount the page between stories in this file).
const signupMock = fn();

const meta: Meta<typeof SignupPage> = {
  title: "Pages/SignupPage",
  component: SignupPage,
  decorators: [withAuth(null, { signup: signupMock })],
};
export default meta;

type Story = StoryObj<typeof SignupPage>;

export const AlwaysOn: Story = {
  decorators: [withRouter("/signup")],
  beforeEach: () => {
    mockSignupConfig({ signup_mode: "always_on", self_signup_organizations: [] });
    signupMock.mockResolvedValue(buildUser());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Create an account")).toBeInTheDocument());
    await expect(canvas.queryByText(/participating organisations/)).not.toBeInTheDocument();
  },
};

export const OrgSpecifiedShowsHint: Story = {
  decorators: [withRouter("/signup")],
  beforeEach: () => mockSignupConfig({ signup_mode: "org_specified", self_signup_organizations: [{ id: "org-1", name: "Acme Corp" }] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/participating organisations/)).toBeInTheDocument());
  },
};

/** Signup disabled deployment-wide with no invite token — the form is
 * replaced entirely with an "unavailable" message. */
export const DisabledUnavailable: Story = {
  decorators: [withRouter("/signup")],
  beforeEach: () => mockSignupConfig({ signup_mode: "disabled", self_signup_organizations: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Public sign-up is not available for this deployment.")).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Display name")).not.toBeInTheDocument();
  },
};

export const InviteTokenBypassesDisabledMode: Story = {
  decorators: [withRouter("/signup?invite=abc123")],
  beforeEach: () => {
    mockSignupConfig({ signup_mode: "disabled", self_signup_organizations: [] });
    signupMock.mockResolvedValue(buildUser());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("You've been invited — complete your account below.")).toBeInTheDocument());
  },
};

export const SignupError: Story = {
  decorators: [withRouter("/signup")],
  beforeEach: () => {
    mockSignupConfig({ signup_mode: "always_on", self_signup_organizations: [] });
    signupMock.mockRejectedValue(new ApiError(409, "Could not create your account."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Display name")).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText("Display name"), "Alex Morgan");
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "password123");
    await userEvent.click(canvas.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(canvas.getByText("Could not create your account.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...AlwaysOn, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AlwaysOn, globals: { theme: "dark" } };
