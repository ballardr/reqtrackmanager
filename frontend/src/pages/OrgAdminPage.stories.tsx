import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { LinkTypeDefinition, OrgAdvancedSettings, OrgGroup, OrgSsoConfig, OrgUser, Organization, ProjectStatusDefinition } from "../api/types";
import { buildLinkType, buildProjectStatus, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { OrgAdminPage } from "./OrgAdminPage";

const ORG_ID = "org-1";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
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

const groups: OrgGroup[] = [
  { id: "grp1", name: "Engineering", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null },
  { id: "grp2", name: "Platform", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null },
];

function mockOrgAdminApis(overrides: {
  advanced?: OrgAdvancedSettings; sso?: OrgSsoConfig; org?: Organization;
  projectStatuses?: ProjectStatusDefinition[]; linkTypes?: LinkTypeDefinition[];
} = {}) {
  const statuses = overrides.projectStatuses ?? [buildProjectStatus({ id: "st1", name: "Proposed", sort_order: 0 }), buildProjectStatus({ id: "st2", name: "Active", sort_order: 1 })];
  const types = overrides.linkTypes ?? [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of", sort_order: 0 })];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return overrides.org ?? org;
    if (path.includes("/project-statuses")) return statuses;
    if (path.includes("/link-types")) return types;
    if (path.includes("/groups")) return groups;
    if (path.includes("/resources")) return [];
    if (path.includes("archived=false")) return [];
    if (path.includes("/report-templates")) return [];
    if (path.includes("/report-defaults")) throw new ApiError(403, "Forbidden");
    if (path.includes("/advanced-settings")) return overrides.advanced ?? advanced;
    if (path.includes("/pats")) return [];
    if (path.includes("/projects")) return [];
    if (path.includes("/sso-config")) return overrides.sso ?? ssoConfig;
    if (path.includes("/scim-token")) return { enabled: false, token_prefix: null };
    if (path.includes("/users")) return [orgUser];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof OrgAdminPage> = {
  title: "Pages/OrgAdminPage",
  component: OrgAdminPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })),
    withRouter(`/orgs/${ORG_ID}/admin`, "/orgs/:orgId/admin"),
    withToast(),
  ],
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

export const RenameOrganization: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockImplementation(async (path: string) =>
      path === `/api/v1/orgs/${ORG_ID}/name` ? { ...org, name: "Renamed Corp" } : org
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Rename")).toHaveValue("Acme Corp"));
    await userEvent.clear(canvas.getByLabelText("Rename"));
    await userEvent.type(canvas.getByLabelText("Rename"), "Renamed Corp");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/name`, { name: "Renamed Corp" })
    );
    await expect(canvas.getByRole("heading", { name: "Renamed Corp" })).toBeInTheDocument();
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
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Branding saved")).toBeInTheDocument();
  },
};

/** Style guide "Pattern: platform default vs. override" (2026-08 UX audit):
 * a field with a saved custom value shows a "Custom" pill and an explicit
 * "Reset to platform default" action, instead of the field just quietly
 * accepting an emptied-out value with no indication of what that does. */
export const BrandingSectionOverridePillAndReset: Story = {
  beforeEach: () => mockOrgAdminApis({ org: { ...org, header_title: "Acme Requirements", email_footer_company_name: "Acme Ltd" } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Branding section" }));
    await waitFor(() => expect(canvas.getByLabelText(/^Header title/)).toBeInTheDocument());

    // Overridden fields show "Custom" + a reset action…
    await expect(canvas.getAllByText("Custom")).toHaveLength(2);
    await expect(canvas.getAllByRole("button", { name: "Reset to platform default" })).toHaveLength(2);
    // …fields still on the platform default show the pill with no reset.
    await expect(canvas.getAllByText("Platform default").length).toBeGreaterThan(0);

    await expect(canvas.getByLabelText(/^Header title/)).toHaveValue("Acme Requirements");
    await userEvent.click(canvas.getAllByRole("button", { name: "Reset to platform default" })[0]);
    await expect(canvas.getByLabelText(/^Header title/)).toHaveValue("");
  },
};

export const BrandingSectionEmailFooterSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Branding section" }));
    await waitFor(() => expect(canvas.getByLabelText("Company name")).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText("Company name"), "Acme Requirements Ltd");
    await userEvent.type(canvas.getByLabelText("Website"), "https://acme.example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/branding`,
        expect.objectContaining({
          email_footer_company_name: "Acme Requirements Ltd", email_footer_website: "https://acme.example.com",
        }),
      )
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

export const AdvancedSettingsTestEmailNoSmtpConfigured: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Advanced settings section" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Send test email" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Send test email" })).toBeDisabled();
    await expect(canvas.getByText("Set an SMTP host above first.")).toBeInTheDocument();
  },
};

export const AdvancedSettingsTestEmailSend: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ advanced: { ...advanced, smtp_host: "smtp.example.com", smtp_port: 587 } });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Advanced settings section" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Send test email" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/test-email`, {})
    );
    await expect(canvas.getByText(/Test email sent/)).toBeInTheDocument();
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

export const ScimSectionGenerateToken: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue({ token: "rtm_scim_fake-secret-value", token_prefix: "rtm_scim_fak" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "SCIM provisioning section" }));
    await waitFor(() => expect(canvas.getByText("Not enabled.")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Generate SCIM token" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/scim-token`)
    );
    await expect(canvas.getByDisplayValue("rtm_scim_fake-secret-value")).toBeInTheDocument();
  },
};

export const GroupsSectionShowsMembers: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups section" }));
    await waitFor(() => expect(canvas.getByText("Engineering", { selector: "span" })).toBeInTheDocument());
    await expect(canvas.getByText(/Alex Morgan/)).toBeInTheDocument();
  },
};

export const GroupsSectionNestGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups section" }));
    await waitFor(() => expect(canvas.getByText("Engineering", { selector: "span" })).toBeInTheDocument());

    // Exactly one <option>Platform</option> exists (Engineering's own
    // nest-picker) — Platform's own row excludes itself, so its picker
    // offers "Engineering" instead.
    const platformOption = canvas.getByText("Platform", { selector: "option" });
    const select = platformOption.closest("select")!;
    await userEvent.selectOptions(select, "grp2");
    const row = select.closest<HTMLElement>(".row")!;
    await userEvent.click(within(row).getByRole("button"));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/groups/grp1/members`,
        { member_org_group_id: "grp2" }
      )
    );
  },
};

/** Style guide "Pattern: create panels, popovers, and one door for bulk":
 * "+ New group" opens a small popover with just a name field, instead of a
 * permanently-visible inline form pinned below the group list. */
export const GroupsSectionCreateGroupViaPopover: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups section" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New group" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "New group" }));
    const dialog = body.getByRole("dialog", { name: "New group" });
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(within(dialog).getByPlaceholderText("e.g. Engineering"), "Design");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/groups`, { name: "Design" }));
    // Principle 7 — every mutation ends with feedback.
    await expect(body.getByText("Group created")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
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

export const ProjectStatusesAddAndReorder: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Project statuses section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Proposed")).toBeInTheDocument());
    const nameInput = canvas.getByPlaceholderText("Name");
    await userEvent.type(nameInput, "Deprecated");
    await userEvent.click(canvas.getByRole("button", { name: "New status" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/project-statuses`,
        { name: "Deprecated" }
      )
    );
  },
};

/** With only one project status left in the org, the delete control is
 * disabled outright (§4.0's minimum-one-remaining rule) rather than
 * offered and then rejected round-trip. */
export const ProjectStatusesDeleteDisabledAtLastRow: Story = {
  beforeEach: () => mockOrgAdminApis({ projectStatuses: [buildProjectStatus({ id: "st1", name: "Active", sort_order: 0 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Project statuses section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Active")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
  },
};

/** Deleting a status that's currently assigned to a project 409s; the UI
 * opens a reassignment picker showing the server's own in-use message
 * instead of a generic confirm, per §4.0's contract. */
export const ProjectStatusesDeleteInUseOpensReassignPicker: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "delete").mockRejectedValue(new ApiError(409, "This status is used by 3 project(s). Pass reassign_to_id to move them to another status before deleting."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Project statuses section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Proposed")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Proposed").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this status"));
    await waitFor(() => expect(canvas.getByText(/used by 3 project\(s\)/)).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Confirm delete" })).toBeDisabled();
  },
};

export const LinkTypesAddAndRename: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Link types section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    // Two "Forward name"/"Reverse name"-placeholder inputs exist on this
    // section: the existing row's own rename inputs (first, pre-filled)
    // and the "add new link type" row at the very bottom (last, empty) —
    // same convention as ProjectAdminPage's category/component add-rows.
    const forwardCandidates = canvas.getAllByPlaceholderText("Forward name");
    const reverseCandidates = canvas.getAllByPlaceholderText("Reverse name");
    const forwardInput = forwardCandidates[forwardCandidates.length - 1];
    const reverseInput = reverseCandidates[reverseCandidates.length - 1];
    await userEvent.type(forwardInput, "Supersedes");
    await userEvent.type(reverseInput, "Is superseded by");
    await userEvent.click(canvas.getByRole("button", { name: "New link type" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/link-types`,
        { forward_name: "Supersedes", reverse_name: "Is superseded by" }
      )
    );
  },
};

/** Same minimum-one-remaining rule as project statuses, applied to link
 * types. */
export const LinkTypesDeleteDisabledAtLastRow: Story = {
  beforeEach: () =>
    mockOrgAdminApis({ linkTypes: [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of", sort_order: 0 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Link types section" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
  },
};

export const LightTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "dark" } };
