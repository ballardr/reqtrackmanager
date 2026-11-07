import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { AnnouncementNotice, OrgLoginInfo } from "../api/types";
import { withAuth, withRouter } from "../testing/storybook-helpers";
import { OrgLoginPage } from "./OrgLoginPage";

function info(overrides: Partial<OrgLoginInfo>): OrgLoginInfo {
  return {
    name: "Acme Corp", slug: "acme", logo_file_id: null, login_background_file_id: null,
    sso_enabled: false, sso_only: false,
    ...overrides,
  };
}

/** Answers the login-info read with `value` and the announcements read with `announcements` (none by default). */
function mockLoginInfo(value: OrgLoginInfo, announcements: AnnouncementNotice[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => (path.includes("/announcements/login") ? announcements : value));
}

// Stable mock reference, reconfigured per-story via `beforeEach` — see
// LoginPage.stories.tsx's `loginMock` comment for why a fresh `fn()` per
// story's own `decorators` array isn't safe here.
const loginMock = fn();

const meta: Meta<typeof OrgLoginPage> = {
  title: "Pages/OrgLoginPage",
  component: OrgLoginPage,
  decorators: [withAuth(null, { login: loginMock }), withRouter("/orgs/acme/login", "/orgs/:slug/login")],
};
export default meta;

type Story = StoryObj<typeof OrgLoginPage>;

export const NativeLoginOnly: Story = {
  beforeEach: () => {
    mockLoginInfo(info({}));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Acme Corp")).toBeInTheDocument());
    await expect(canvas.getByLabelText("Email")).toBeInTheDocument();
    await expect(canvas.queryByText("Sign in with SSO")).not.toBeInTheDocument();
  },
};

/** The branded page shows the organisation's messages with the platform's and sends its slug. */
export const ShowsPlatformAndOrganisationMessages: Story = {
  beforeEach: () => {
    mockLoginInfo(info({}), [
      { id: "n1", title: "Platform notice", body: "", severity: "warning", scope: "server" },
      { id: "n2", title: "Acme notice", body: "Badges are collected at reception.", severity: "information", scope: "organisation" },
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Platform notice")).toBeInTheDocument();
    await expect(canvas.getByText("Acme notice")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith("/api/v1/announcements/login?organization_slug=acme");
  },
};

export const SsoAndNativeBothOffered: Story = {
  beforeEach: () => {
    mockLoginInfo(info({ sso_enabled: true, sso_only: false }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Sign in with SSO")).toBeInTheDocument());
    await expect(canvas.getByText("or")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Email")).toBeInTheDocument();
  },
};

/** `sso_only`: the native email/password form is hidden entirely — SSO is
 * the only way in. */
export const SsoOnlyHidesNativeForm: Story = {
  beforeEach: () => {
    mockLoginInfo(info({ sso_enabled: true, sso_only: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Sign in with SSO")).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Email")).not.toBeInTheDocument();
    await expect(canvas.queryByText("or")).not.toBeInTheDocument();
  },
};

export const OrgNotFound: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Not found"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Something went wrong.")).toBeInTheDocument());
  },
};

export const NativeLoginError: Story = {
  beforeEach: () => {
    mockLoginInfo(info({}));
    loginMock.mockRejectedValue(new ApiError(401, "Invalid email or password."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Email")).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText("Email"), "alex@example.com");
    await userEvent.type(canvas.getByLabelText("Password"), "wrong");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(canvas.getByText("Invalid email or password.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...SsoAndNativeBothOffered, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SsoAndNativeBothOffered, globals: { theme: "dark" } };
