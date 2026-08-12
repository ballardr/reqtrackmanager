import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { OrgAdvancedSettings, OrgGroup, OrgSsoConfig, OrgUser, Organization } from "../api/types";
import { buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgAdminPage } from "./OrgAdminPage";

const ORG_ID = "org-1";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
};

const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["org_admin"], display_name_locked: false, last_login_at: "2026-02-01T09:00:00Z",
  is_2fa_enabled: true,
};

const advanced: OrgAdvancedSettings = {
  smtp_host: null, smtp_port: null, smtp_username: null, smtp_use_tls: true, sso_group_mappings: [],
  pat_max_lifetime_days: null, require_2fa: false, allow_self_signup: false, auto_accept_email_domain: null,
  external_user_policy: "disabled",
};

const ssoConfig: OrgSsoConfig = {
  slug: "acme", sso_enabled: true, sso_only: false, oidc_issuer_url: "https://idp.example.com",
  oidc_client_id: "client-1", oidc_required_group: null,
};

const groups: OrgGroup[] = [{ id: "grp1", name: "Engineering", member_user_ids: ["user-1"] }];

function mockOrgAdminApis(overrides: { advanced?: OrgAdvancedSettings; sso?: OrgSsoConfig } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return org;
    if (path.includes("/groups")) return groups;
    if (path.includes("/resources")) return [];
    if (path.includes("archived=false")) return [];
    if (path.includes("/report-templates")) return [];
    if (path.includes("/report-defaults")) throw new ApiError(403, "Forbidden");
    if (path.includes("/advanced-settings")) return overrides.advanced ?? advanced;
    if (path.includes("/pats")) return [];
    if (path.includes("/projects")) return [];
    if (path.includes("/sso-config")) return overrides.sso ?? ssoConfig;
    if (path.includes("/users")) return [orgUser];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof OrgAdminPage> = {
  title: "Pages/OrgAdminPage",
  component: OrgAdminPage,
  decorators: [withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })), withRouter(`/orgs/${ORG_ID}/admin`, "/orgs/:orgId/admin")],
};
export default meta;

type Story = StoryObj<typeof OrgAdminPage>;

export const UsersSectionAndCreateUser: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Organisation users section" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Org admin")).toBeInTheDocument();
  },
};

/** A server admin who isn't a member of this org gets the degraded view
 * (join as admin, or bootstrap an admin user for someone else) instead of
 * the normal page. */
export const NotAMemberServerAdminDegradedView: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-2", is_server_admin: true }))],
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(403, "You are not a member of this organisation."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("You're not a member of this organisation")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Become admin of this organisation" })).toBeInTheDocument();
    // "Create an admin user" is the section heading; the submit button
    // underneath it is labelled "New user" (`strings.orgAdmin.newUser`).
    await expect(canvas.getByRole("heading", { name: "Create an admin user" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "New user" })).toBeInTheDocument();
  },
};

export const DisabledOrgServerAdminCanReEnable: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-2", is_server_admin: true }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === `/api/v1/orgs/${ORG_ID}`) return org;
      throw new ApiError(403, "This organisation is disabled.");
    });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("This organisation is disabled.")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Enable" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/enable`));
  },
};

export const BrandingSectionSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Branding section" }));
    // The label also wraps a trailing hint <span>, so its accessible name
    // is longer than "Header title" alone — match by prefix.
    await waitFor(() => expect(canvas.getByLabelText(/^Header title/)).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText(/^Header title/), "Acme Requirements");
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding`, expect.objectContaining({ header_title: "Acme Requirements" }))
    );
  },
};

/**
 * The fix made in this same pass: ticking "Allow self-signup" while this
 * organisation is SSO-only shows an inline warning and disables Save,
 * instead of the previous "only found out after a 422" behaviour. The
 * backend's own rejection of this combination is covered by
 * `test_update_advanced_settings_rejects_self_signup_for_sso_only_org`.
 */
export const SelfSignupSsoConflictBlocksSave: Story = {
  beforeEach: () => mockOrgAdminApis({ sso: { ...ssoConfig, sso_only: true } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Advanced settings section" }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Allow self-signup" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Allow self-signup" }));
    await expect(
      canvas.getByText("Self-signup can't be enabled while this organisation is SSO-only — turn off \"SSO only\" in the SSO configuration below first, or turn off self-signup here.")
    ).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save advanced settings" })).toBeDisabled();
  },
};

export const AdvancedSettingsRequire2fa: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Advanced settings section" }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Require two-factor authentication" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Require two-factor authentication" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save advanced settings" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/advanced-settings`,
        expect.objectContaining({ require_2fa: true })
      )
    );
  },
};

export const SsoSectionSaveDisabledWhenNotConfigured: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Single sign-on (SSO) section" }));
    await waitFor(() => expect(canvas.getByLabelText("OIDC issuer URL")).toHaveValue("https://idp.example.com"));
  },
};

export const GroupsSectionShowsMembers: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups section" }));
    await waitFor(() => expect(canvas.getByText("Engineering")).toBeInTheDocument());
    await expect(canvas.getByText(/Alex Morgan/)).toBeInTheDocument();
  },
};

export const PatsSectionNoneReachOrg: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Personal Access Tokens section" }));
    await waitFor(() => expect(canvas.getByText("No tokens currently reach this organisation.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "dark" } };
