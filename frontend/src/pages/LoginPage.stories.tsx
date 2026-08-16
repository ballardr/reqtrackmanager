import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ServerSettings, SignupConfig } from "../api/types";
import { buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { LoginPage } from "./LoginPage";

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: "ReqTrack Manager",
  default_login_background_file_id: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  org_label_singular: null, org_label_plural: null,
};

function mockBrandingAndSignup(signupMode: SignupConfig["signup_mode"] = "disabled") {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("signup-config")) return { signup_mode: signupMode, self_signup_organizations: [] } satisfies SignupConfig;
    return SERVER_SETTINGS;
  });
}

// Stable mock references reconfigured per-story via `beforeEach`, rather
// than a fresh `fn()` per story's `decorators` array — Vitest browser mode
// doesn't fully remount LoginPage between stories in this file, so a
// per-story `withAuth(null, { login: fn()... })` closure could still be
// showing a PREVIOUS story's stale resolved/rejected value by the time this
// story's `play` runs. Reconfiguring the same reference in `beforeEach`
// (the pattern already used for `api.get` throughout this codebase) avoids
// that ordering hazard entirely.
const loginMock = fn();
const verify2faMock = fn();

const meta: Meta<typeof LoginPage> = {
  title: "Pages/LoginPage",
  component: LoginPage,
  // No router decorator at the meta level: `ReauthMessage` below needs a
  // MemoryRouter carrying route `state`, and story-level decorators
  // compose WITH (not instead of) meta-level ones — two `<MemoryRouter>`s
  // would nest, which React Router forbids. Each story that doesn't need
  // special router state adds its own plain `withRouter("/login")` instead.
  decorators: [withAuth(null, { login: loginMock, verify2fa: verify2faMock })],
};
export default meta;

type Story = StoryObj<typeof LoginPage>;

export const Default: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockResolvedValue({ requires2fa: false, user: buildUser() });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Sign in" is both the heading and the submit button — scope to the heading.
    await expect(canvas.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await expect(canvas.queryByText(/New here/)).not.toBeInTheDocument();
  },
};

export const SignUpPromptShownWhenSignupEnabled: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => mockBrandingAndSignup("always_on"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/New here/)).toBeInTheDocument());
  },
};

export const InvalidCredentials: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockRejectedValue(new ApiError(401, "Invalid email or password."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "wrong-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Invalid email or password.")).toBeInTheDocument());
  },
};

/** A 2FA-enrolled account's login returns a challenge token instead of a
 * session — the page switches to the code-entry form. */
export const TwoFactorChallenge: Story = {
  decorators: [withRouter("/login")],
  beforeEach: () => {
    mockBrandingAndSignup();
    loginMock.mockResolvedValue({ requires2fa: true, challengeToken: "challenge-1" });
    verify2faMock.mockResolvedValue(buildUser());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "correct-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Two-factor verification")).toBeInTheDocument());
  },
};

const withReauthState: Decorator = (Story) => (
  <MemoryRouter initialEntries={[{ pathname: "/login", state: { message: "For your security, you've been signed out. Please sign in again." } }]}>
    <Story />
  </MemoryRouter>
);

/** Redirected here after a forced logout (expired token, password changed
 * elsewhere) — App.tsx passes a `message` via router state. `withAuth` is
 * already provided at the meta level; this only adds the router. */
export const ReauthMessage: Story = {
  decorators: [withReauthState],
  beforeEach: () => mockBrandingAndSignup(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/signed out/)).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
