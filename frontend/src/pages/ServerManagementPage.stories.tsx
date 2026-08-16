import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ServerSettings, SignupConfig, SystemUser } from "../api/types";
import { withRouter } from "../testing/storybook-helpers";
import { ServerManagementPage } from "./ServerManagementPage";

function systemUser(overrides: Partial<SystemUser>): SystemUser {
  return {
    user_id: "u1", email: "orphan@example.com", display_name: "Orphan User", is_active: true,
    is_banned: false, last_login_at: "2026-02-01T09:00:00Z", is_2fa_enabled: false,
    created_at: "2026-01-01T09:00:00Z", is_server_admin: false, has_org_membership: false,
    organization_count: 0, organization_names: [], group_names: [],
    ...overrides,
  };
}

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null,
  default_login_background_file_id: null,
  email_footer_company_name: "ReqTrackManager", email_footer_website: "https://reqtrackmanager.example.com",
  email_footer_address: "1 Example Street\nExample City, EX1 1AA",
  org_label_singular: null, org_label_plural: null,
};

const SIGNUP_CONFIG: SignupConfig = { signup_mode: "disabled", self_signup_organizations: [] };

function mockServerManagementApis(users: SystemUser[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/system/users")) return users;
    if (path.includes("/system/branding")) return SERVER_SETTINGS;
    if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ServerManagementPage> = {
  title: "Pages/ServerManagementPage",
  component: ServerManagementPage,
  decorators: [withRouter("/server/management")],
};
export default meta;

type Story = StoryObj<typeof ServerManagementPage>;

export const AccessReviewOrphanedAccounts: Story = {
  beforeEach: () => mockServerManagementApis([systemUser({})]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("None")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Grant server admin" })).toBeInTheDocument();
  },
};

export const AccessReviewShowsGroups: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({ user_id: "u1", email: "grouped@example.com", group_names: ["Engineering", "Platform"] }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("grouped@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Engineering, Platform")).toBeInTheDocument();
  },
};

export const AccessReviewBannedAndAdminBadges: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({ user_id: "u1", email: "banned@example.com", is_banned: true, is_active: false }),
      systemUser({ user_id: "u2", email: "admin@example.com", is_server_admin: true }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Banned")).toBeInTheDocument());
    await expect(canvas.getByText("Server admin")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Revoke server admin" })).toBeInTheDocument();
  },
};

export const AccessReviewGrantServerAdmin: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(window, "confirm").mockReturnValue(true);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Grant server admin" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/users/u1/server-admin", { is_server_admin: true }));
  },
};

export const PlatformBrandingTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Platform branding" }));
    await waitFor(() => expect(canvas.getByText(/default accent colour, logo/)).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Save platform branding" })).toBeInTheDocument();
  },
};

export const PlatformBrandingSave: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Platform branding" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save platform branding" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save platform branding" }));
    await waitFor(() => expect(canvas.getByText("Saved.")).toBeInTheDocument());
  },
};

export const PlatformBrandingEmailFooter: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Platform branding" }));
    // "Company name" also wraps a trailing hint <span>, so its accessible
    // name is longer than "Company name" alone — match by prefix.
    await waitFor(() => expect(canvas.getByLabelText(/^Company name/)).toHaveValue("ReqTrackManager"));
    await expect(canvas.getByLabelText("Website")).toHaveValue("https://reqtrackmanager.example.com");
    await expect(canvas.getByLabelText("Postal address")).toHaveValue("1 Example Street\nExample City, EX1 1AA");
    await userEvent.clear(canvas.getByLabelText(/^Company name/));
    await userEvent.type(canvas.getByLabelText(/^Company name/), "Acme Platform Inc");
    await userEvent.click(canvas.getByRole("button", { name: "Save platform branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/v1/system/branding",
        expect.objectContaining({ email_footer_company_name: "Acme Platform Inc" }),
      ),
    );
  },
};

export const PlatformBrandingOrgLabel: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Platform branding" }));
    await waitFor(() => expect(canvas.getByLabelText(/^Organisation label \(singular\)/)).toHaveValue(""));
    await userEvent.type(canvas.getByLabelText(/^Organisation label \(singular\)/), "tenant");
    await userEvent.type(canvas.getByLabelText(/^Organisation label \(plural\)/), "Tenants");
    await userEvent.click(canvas.getByRole("button", { name: "Save platform branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/v1/system/branding",
        expect.objectContaining({ org_label_singular: "tenant", org_label_plural: "Tenants" }),
      ),
    );
  },
};

export const SignupModeTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Public sign-up" }));
    await waitFor(() => expect(canvas.getByLabelText("Sign-up mode")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Sign-up mode"), "org_specified");
    await expect(canvas.getByText(/Organisations opt in/)).toBeInTheDocument();
  },
};

export const TestEmailTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() => expect(canvas.getByText(/deployment's configured SMTP settings/)).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Send test email" })).toBeInTheDocument();
  },
};

export const TestEmailSendSuccess: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/test-email", {}));
    await expect(canvas.getByText(/Test email sent/)).toBeInTheDocument();
  },
};

export const TestEmailSendFailure: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(502, "Failed to send test email: connection refused"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() => expect(canvas.getByText(/connection refused/)).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "dark" } };
