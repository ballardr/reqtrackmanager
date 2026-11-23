import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ServiceUser } from "../api/serviceUsers";
import type { ArtefactLinkRule, ArtefactTypeOption, CustomRoleDefinition, CustomRolePreset, EntityScope, LinkTypeDefinition, ModuleRoleDefinition, OrgAdvancedSettings, OrgGroup, OrgModule, OrgModuleSubComponent, OrgPendingInvite, OrgPersonalAccessToken, OrgRole, OrgSsoConfig, OrgUser, Organization, Permission, ProjectStatusDefinition, UserAccess } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildServiceUser } from "../testing/serviceUserFixtures";
import { buildLinkType, buildProjectStatus, buildUser, withRouter, withStatefulAuth, withToast, openAddDialog } from "../testing/storybook-helpers";
import { OrgAdminPage } from "./OrgAdminPage";

const ORG_ID = "org-1";

const org: Organization = {
  id: ORG_ID, name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
};

const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["org_admin"], display_name_locked: false, last_login_at: "2026-02-01T09:00:00Z",
  is_2fa_enabled: true, module_roles: [], custom_roles: [],
};

const advanced: OrgAdvancedSettings = {
  smtp_host: null, smtp_port: null, smtp_username: null, smtp_use_tls: true,
  pat_max_lifetime_days: null, report_output_retention_days: null, report_file_name: null, report_footer_text: null,
  report_include_cover_page: false, report_chapters_per_component: true, report_output_default_retention_days: 7,
  report_output_max_retention_days: 30, require_2fa: false, allow_self_signup: false, auto_accept_email_domain: null,
  external_user_policy: "disabled", allow_relaxed_child_project_creation: true,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
  allow_imported_approval_state: true,
};

const ssoConfig: OrgSsoConfig = {
  slug: "acme", sso_enabled: true, sso_only: false, oidc_issuer_url: "https://idp.example.com",
  oidc_client_id: "client-1", oidc_required_group: null, oidc_allow_account_creation: true,
};

const groups: OrgGroup[] = [
  { id: "grp1", name: "Engineering", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "grp2", name: "Platform", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

const defaultArtefactTypes: ArtefactTypeOption[] = [
  { type: "requirement", label: "Requirement" },
  { type: "decision", label: "Decision" },
];
const defaultArtefactRules: ArtefactLinkRule[] = [
  { artefact_type: "requirement", label: "Requirement", link_type_ids: null },
  { artefact_type: "decision", label: "Decision", link_type_ids: null },
];

/** The platform branding the company settings show as placeholders. */
const PLATFORM_BRANDING = {
  accent_color_hex: "#475569", default_logo_file_id: "platform-logo", default_header_title: "Platform Requirements",
  logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: "after_content",
  default_login_background_file_id: null, email_footer_company_name: "Platform Co", email_footer_website: "https://platform.example.com",
  email_footer_address: "1 Platform Way", org_label_singular: null, org_label_plural: null,
};

function mockOrgAdminApis(overrides: {
  scim?: { enabled: boolean; token_prefix: string | null };
  advanced?: OrgAdvancedSettings; sso?: OrgSsoConfig; org?: Organization;
  projectStatuses?: ProjectStatusDefinition[]; linkTypes?: LinkTypeDefinition[]; userAccess?: UserAccess;
  pats?: OrgPersonalAccessToken[]; serviceUsers?: ServiceUser[]; users?: OrgUser[]; orgInvites?: OrgPendingInvite[]; groups?: OrgGroup[];
  modules?: OrgModule[]; moduleRoles?: ModuleRoleDefinition[];
  // A module's declared sub-components, keyed by `module_key`; `[]` per module when none are declared, as the real `GET .../subcomponents` returns.
  moduleSubComponents?: Record<string, OrgModuleSubComponent[]>;
  // Fine-Grained Access Control (core): fetched in the main `reload()` bundle (open to any organisation role, not ORG_ADMIN-gated),
  // so every story must mock it or `reload()` fails as a whole. Defaults to the "no custom roles defined" case.
  permissions?: Permission[]; customRoles?: CustomRoleDefinition[];
  // `GET .../custom-role-presets`, fetched when the New custom role Modal opens; defaults to none.
  customRolePresets?: CustomRolePreset[];
  // Fine-Grained Access Control (core): fetched in the same `reload()` bundle as `permissions`/`customRoles`; unmocked it would
  // reject the whole `Promise.all` for every story, not only Role Management ones. Defaults to empty.
  entityScopes?: EntityScope[];
  /** Simulates a non-ORG_ADMIN caller (e.g. a plain `grant_roles` holder) for whom `GET .../advanced-settings` 403s, the signal the
   * Role Management role-definition half is gated on, so the definition half hides while the assignment half stays visible. */
  advancedForbidden?: boolean;
  /** The admin header's `EntitySwitcher` sibling-organisation list (`GET /api/v1/orgs?mine=true`); defaults to empty because every
   * render of the header calls it. */
  orgs?: Organization[];
  /** Link types panel: the artefact types the
   * restriction pickers offer, and the "By artefact type" rules. */
  artefactTypes?: ArtefactTypeOption[]; artefactRules?: ArtefactLinkRule[];
} = {}) {
  const statuses = overrides.projectStatuses ?? [buildProjectStatus({ id: "st1", name: "Proposed", sort_order: 0 }), buildProjectStatus({ id: "st2", name: "Active", sort_order: 1 })];
  const types = overrides.linkTypes ?? [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of", sort_order: 0 })];
  const orgUsers = overrides.users ?? [orgUser];
  const orgPendingInvites = overrides.orgInvites ?? [];
  const orgGroups = overrides.groups ?? groups;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/system/branding") return PLATFORM_BRANDING;
    if (path === `/api/v1/orgs/${ORG_ID}`) return overrides.org ?? org;
    if (path === "/api/v1/orgs?mine=true") return overrides.orgs ?? [];
    if (path.includes("/project-statuses")) return statuses;
    if (path.includes("/artefact-types")) return overrides.artefactTypes ?? defaultArtefactTypes;
    if (path.includes("/artefact-link-rules")) return overrides.artefactRules ?? defaultArtefactRules;
    if (path.endsWith("/project-customisation")) return { locks: [], local_link_type_count: 0, local_link_type_project_count: 0 };
    if (path.includes("/link-types")) return types;
    // The org-only pending-invites list.
    if (path.includes("/pending-invites")) return orgPendingInvites;
    if (path.includes("/imported-people")) return { retention_days: null, people: [] };
    if (path.includes("/groups")) return orgGroups;
    if (path.includes("/resources")) return [];
    if (path.includes("archived=false")) return [];
    if (path.includes("/advanced-settings")) {
      if (overrides.advancedForbidden) throw new ApiError(403, "Forbidden");
      return overrides.advanced ?? advanced;
    }
    if (path.includes("/service-users")) {
      if (path.includes("/pats")) return [];
      const known = overrides.serviceUsers ?? [];
      return known.find((u) => path.endsWith(`/${u.user_id}`)) ?? known;
    }
    if (path.includes("/pats")) return overrides.pats ?? [];
    // Fetched in the same try/catch-403 block as `/advanced-settings`; it and `/module-roles` must be mocked or `reload()` throws.
    // Checked first to keep the more specific path robust against ordering changes ("/module-roles" does not contain "/modules").
    if (path.includes("/module-roles")) return overrides.moduleRoles ?? [];
    // Before the generic "/modules" branch, since `.../modules/{key}/subcomponents` also contains it; `moduleKey` is parsed from the
    // path so each module's fixture routes to its own override.
    if (path.includes("/subcomponents")) {
      const moduleKey = path.split("/modules/")[1]?.split("/subcomponents")[0];
      return overrides.moduleSubComponents?.[moduleKey ?? ""] ?? [];
    }
    if (path.includes("/modules")) return overrides.modules ?? [];
    // Fine-Grained Access Control (core): before the plain "/users" branch, ordered like `/module-roles`/`/modules` above.
    if (path.includes("/permissions")) return overrides.permissions ?? [];
    if (path.includes("/custom-role-presets")) return overrides.customRolePresets ?? [];
    if (path.includes("/custom-roles")) return overrides.customRoles ?? [];
    // Fine-Grained Access Control (core): before the plain "/users" branch, ordered like the two branches above.
    if (path.includes("/entity-scopes")) return overrides.entityScopes ?? [];
    // `UserAutocomplete`'s debounced server search (`organizationId` mode, used by the custom-role assignment card), before the
    // "/users" catch-all it also matches.
    if (path.includes("/users/search")) return { members: orgUsers, external: null };
    if (path.includes("/projects")) return [];
    if (path.includes("/sso-config")) return overrides.sso ?? ssoConfig;
    if (path.includes("/scim-token")) return overrides.scim ?? { enabled: false, token_prefix: null };
    // Before the plain "/users" branch: a user-access summary request also contains that substring.
    if (path.includes("/access")) return overrides.userAccess ?? { org_groups: [], projects: [] };
    if (path.includes("/users")) return orgUsers;
    throw new Error(`unmocked path: ${path}`);
  });
  // Users and Groups paginate and search; `api.get` above serves the unpaginated groups fetch (`allGroups`, which resolves
  // nested-group names whatever the Groups section's state), and this is the paginated view each section renders. The `/users`
  // branch honours an `org_role` query parameter so a story can exercise the role filter.
  spyOn(api, "getPage").mockImplementation(async (path: string) => {
    if (path.includes("/groups")) return { items: orgGroups, total: orgGroups.length };
    if (path.includes("/users")) {
      const role = new URL(path, "http://x").searchParams.get("org_role") as OrgRole | null;
      const items = role ? orgUsers.filter((u) => u.roles.includes(role)) : orgUsers;
      return { items, total: items.length };
    }
    throw new Error(`unmocked getPage path: ${path}`);
  });
}

/**
 * A fixture module registered into the real `installedModules` (as `App.stories.tsx`'s `FIXTURE_MODULE_KEY`) contributes one
 * `orgAdminSections` entry, proving the generic merge-and-render in `OrgAdminPage.tsx` works for a module other than Compliance.
 * Nothing renders it unless a story's `mockOrgAdminApis({ modules: [...] })` reports this key as enabled (see
 * `moduleAdminSections`' enablement filter), so its permanent presence does not affect other stories. `routes` is omitted
 * (optional): a module can contribute an org-admin section with no project-scoped UI.
 */
const FIXTURE_ORG_MODULE_KEY = "fake_org_admin_fixture_module";
const FIXTURE_ORG_ADMIN_SECTION_KEY = "fixture-admin-section";

installedModules.push({
  key: FIXTURE_ORG_MODULE_KEY,
  orgAdminSections: [
    {
      key: FIXTURE_ORG_ADMIN_SECTION_KEY,
      label: "Fixture admin section",
      render: ({ orgId }) => <div>Fixture admin section content for org {orgId}</div>,
    },
  ],
});

function fixtureOrgModule(overrides: Partial<OrgModule> = {}): OrgModule {
  return {
    module_key: FIXTURE_ORG_MODULE_KEY, name: "Fixture Org Module",
    description: "A fixture module used only by this story file's own org-admin-section assertions.",
    version: "0.1.0", implemented: true, entitled: true, enabled: true, default_project_enabled: true,
    default_enabled: true, frontend_manifest: null, ...overrides,
  };
}

const meta: Meta<typeof OrgAdminPage> = {
  title: "Pages/OrgAdminPage",
  component: OrgAdminPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1", is_server_admin: false })),
    withRouter(`/orgs/${ORG_ID}/admin`, "/orgs/:orgId/admin/:group?"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof OrgAdminPage>;

/** The Organisation Settings menu does not list Reports or Tags. */
export const SettingsMenuNoLongerListsReportsOrTags: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await expect(canvas.queryByRole("link", { name: "Reports" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Tags" })).not.toBeInTheDocument();
  },
};

export const UsersSectionAndCreateUser: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    // Users is its own top-level resource-menu group and is open by default, so selecting the group is enough.
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    // Scoped to the roles dropdown trigger, not a page-wide `getByText`: the role `FilterField` also has an "Org admin" `<option>`.
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toHaveTextContent("Org admin");
    // This table's 6 columns crowd a side sidebar, so its `FilterPanel` renders `layout="top"` (docs/ux-style-guide.md "Pattern: filter panel placement").
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** A service user is badged in the Users table, its two-factor cell reads Not applicable, and it has no reset-link action. */
export const UsersTableMarksServiceUsers: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      users: [orgUser, { ...orgUser, user_id: "svc-1", email: "svc-1@service.invalid", display_name: "Build agent", roles: ["member"], is_2fa_enabled: false, is_service_account: true }],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    const row = (await canvas.findByText("Build agent")).closest("tr") as HTMLElement;
    await expect(within(row).getByText("Service", { exact: true })).toBeInTheDocument();
    // Two-factor and last sign-in both do not apply: it has no sign-in.
    await expect(within(row).getAllByText("Not applicable")).toHaveLength(2);
    await userEvent.click(within(row).getByRole("button", { name: "Build agent's actions" }));
    await expect(within(document.body).queryByRole("menuitem", { name: /reset link/i })).not.toBeInTheDocument();
  },
};

/** The service users are rows of the one Users list: no separate section, and a row carries its review flags. */
export const ServiceUsersAreRowsOfTheUsersList: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      users: [orgUser, { ...orgUser, user_id: "su-1", email: "svc-1@service.invalid", display_name: "Build agent", roles: ["member"], is_2fa_enabled: false, is_service_account: true, has_deliverable_email: false, service_flags: ["no_responsible"], last_login_at: null }],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    const row = (await canvas.findByRole("button", { name: "Build agent" })).closest("tr") as HTMLElement;
    await expect(within(row).getByText("No responsible party")).toBeInTheDocument();
    // The generated address is never shown, and there is no sign-in to report.
    await expect(within(row).queryByText(/service\.invalid/)).not.toBeInTheDocument();
    await expect(within(row).getAllByText("Not applicable")).toHaveLength(2);
    await expect(canvas.queryByRole("button", { name: "Service users section" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("table", { name: "Service users" })).not.toBeInTheDocument();
    // A person's name is not a button; only a service user's row opens a dialog.
    await expect(canvas.queryByRole("button", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

/** A service user's row opens its own dialog (tokens, lifecycle), not the person's panel. */
export const ServiceUserRowOpensItsDetail: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      users: [orgUser, { ...orgUser, user_id: "su-1", email: "svc-1@service.invalid", display_name: "Build agent", roles: ["member"], is_2fa_enabled: false, is_service_account: true, has_deliverable_email: false }],
      serviceUsers: [buildServiceUser()],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Build agent" }));
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Build agent" }));
    await expect(await detail.findByRole("button", { name: "Issue token" })).toBeInTheDocument();
    await expect(within(document.body).queryByRole("dialog", { name: /access/i })).not.toBeInTheDocument();
  },
};

/** The Add user menu offers New service user, which opens the service user form and posts to the service-user endpoint. */
export const AddUserMenuCreatesAServiceUser: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(buildServiceUser({ user_id: "su-9", name: "New job" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New service user" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New service user" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "New job");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/service-users`, { name: "New job", description: "", responsible: null }),
    );
    await expect(await within(document.body).findByText("Service user created.")).toBeInTheDocument();
    await expect(within(document.body).getByRole("button", { name: "Open New job" })).toBeInTheDocument();
  },
};

/** Include archived asks the server for archived accounts too (an archived service user is hidden otherwise). */
export const IncludeArchivedFilterAsksForArchivedAccounts: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Include archived" }));
    await waitFor(() => expect(api.getPage).toHaveBeenCalledWith(expect.stringContaining("include_archived=true")));
  },
};

/** Style guide "Pattern: modal dialog for entity create/rename" (Principle 3): "New user" opens a `Modal`, not an inline form. */
export const NewUserOpensModalAndCreates: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add user" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New user" }));
    const dialog = body.getByRole("dialog", { name: "New user" });
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(within(dialog).getByLabelText("Email"), "sam@example.com");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Sam Rivera");
    await userEvent.type(within(dialog).getByLabelText("Password"), "correct-horse-battery-staple");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users`, {
        email: "sam@example.com", display_name: "Sam Rivera", password: "correct-horse-battery-staple", role: "member",
      })
    );
    // Principle 7 — every mutation ends with feedback.
    await expect(body.getByText("User created")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Cancelling the "New user" modal creates nothing and leaves the Users table untouched. */
export const NewUserModalCancel: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add user" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New user" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New user" });
    await userEvent.type(within(dialog).getByLabelText("Email"), "discarded@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Discard changes" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** The "New user" modal's role select; `createUser()` sends the chosen role. */
export const NewUserModalRoleSelect: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add user" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New user" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New user" });

    await userEvent.type(within(dialog).getByLabelText("Email"), "sam@example.com");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Sam Rivera");
    await userEvent.type(within(dialog).getByLabelText("Password"), "correct-horse-battery-staple");
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "Project creator");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users`, {
        email: "sam@example.com", display_name: "Sam Rivera", password: "correct-horse-battery-staple", role: "project_creator",
      })
    );
  },
};

/** Per-row role grant/revoke through a `MultiSelectDropdown` (docs/decisions.md, "Org Users role picker"): granting a role the user
 * does not hold calls `POST .../roles`, revoking one they hold calls `DELETE .../roles/{role}`. It is a multi-select because
 * `UserOrgRole` allows several organisation roles at once. */
const secondOrgUser: OrgUser = {
  user_id: "user-2", email: "jordan@example.com", display_name: "Jordan Lee", is_active: true,
  is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null,
  is_2fa_enabled: false, module_roles: [], custom_roles: [],
};

export const UsersSectionGrantAndRevokeRole: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ users: [orgUser, secondOrgUser] });
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    // orgUser (the logged-in user) only holds "org_admin" — granting
    // "Project creator" posts.
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const alexRoles = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(alexRoles).getByRole("checkbox", { name: "Grant Project creator to Alex Morgan" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-1/roles`, {
        user_id: "user-1",
        role: "project_creator",
      })
    );

    // secondOrgUser (not the logged-in user) holds "project_creator" —
    // revoking it deletes. Opening this row's dropdown closes Alex's own,
    // via the shared `Popover` outside-click behaviour.
    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's roles" }));
    const jordanRoles = within(document.body).getByRole("group", { name: "Jordan Lee's roles" });
    await userEvent.click(within(jordanRoles).getByRole("checkbox", { name: "Revoke Project creator from Jordan Lee" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-2/roles/project_creator`)
    );
  },
};

/** The Users table's Roles dropdown merges in org-scoped module-contributed role options beside the three `OrgRole` ones, labelled
 * `"<role name> (<module name>)"` from the fetched `modules` list. Jordan holds one grant (checked, revoke path); Alex does not hold
 * the other (unchecked, grant path). Other stories cover the zero-module-roles default (`moduleRoles` defaults to `[]`). */
export const UsersSectionModuleRoleGrantAndRevoke: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      users: [orgUser, { ...secondOrgUser, module_roles: [{ module_key: "compliance", role_key: "compliance_manager" }] }],
      modules: [
        {
          module_key: "compliance", name: "Compliance", description: "Compliance tracking.", version: "1.0.0",
          implemented: true, entitled: true, enabled: true, default_project_enabled: true,
          default_enabled: true, frontend_manifest: null,
        },
      ],
      moduleRoles: [
        { module_key: "compliance", role_key: "compliance_manager", name: "Compliance Manager", description: "Manages standards." },
        { module_key: "compliance", role_key: "compliance_officer", name: "Compliance Officer", description: "Assesses projects." },
      ],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const alexRoles = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await expect(within(alexRoles).getByText("Compliance Manager (Compliance)")).toBeInTheDocument();
    await userEvent.click(
      within(alexRoles).getByRole("checkbox", { name: "Grant Compliance Officer (Compliance) to Alex Morgan" })
    );
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-1/module-roles`, {
        module_key: "compliance", role_key: "compliance_officer",
      })
    );

    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's roles" }));
    const jordanRoles = within(document.body).getByRole("group", { name: "Jordan Lee's roles" });
    await userEvent.click(
      within(jordanRoles).getByRole("checkbox", { name: "Revoke Compliance Manager (Compliance) from Jordan Lee" })
    );
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/users/user-2/module-roles/compliance/compliance_manager`
      )
    );
  },
};

/** A user cannot revoke their own organisation role (the backend blocks self-targeting); `orgUser` is the signed-in user (`user-1`). */
export const UsersSectionCannotRevokeOwnRole: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const alexRoles = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await expect(within(alexRoles).getByRole("checkbox", { name: "Revoke Org admin from Alex Morgan" })).toBeDisabled();
  },
};

/** The Users table Actions column (docs/decisions.md) is one `ActionMenu` (View access, lock/unlock display name), the kebab pattern of
 * `ExportOrgBundleViaActionMenu`. Exercised on the signed-in user's own row, where "Remove from {org}" is withheld (self-removal
 * goes through "Leave organisation", matching the backend's self-targeting guard). */
export const UsersActionsMenuConsolidatesViewAndLock: Story = {
  beforeEach: () => mockOrgAdminApis({ users: [orgUser, secondOrgUser] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Alex Morgan's actions" });
    await expect(within(menu).getByRole("menuitem", { name: "View Alex Morgan's access" })).toBeInTheDocument();
    await expect(within(menu).getByRole("menuitem", { name: "Lock display name" })).toBeInTheDocument();
    await expect(within(menu).queryByRole("menuitem", { name: /Remove from/ })).not.toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: "View Alex Morgan's access" }));
    await expect(within(document.body).getByRole("dialog", { name: "Alex Morgan's access" })).toBeInTheDocument();
  },
};

/** "Send password reset link": offered on other people's rows only (the caller uses the sign-in page's
 * "Forgot your password?"), behind a Tier 1 confirmation; the link is emailed to the person, never shown. */
export const UsersActionsMenuSendsAPasswordResetLink: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ users: [orgUser, secondOrgUser] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("jordan@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    await expect(body.queryByRole("menuitem", { name: "Send password reset link" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's actions" }));
    await userEvent.click(body.getByRole("menuitem", { name: "Send password reset link" }));
    const dialog = body.getByRole("dialog", { name: "Send a password reset link to Jordan Lee?" });
    await expect(api.post).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send link" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-2/password-reset`));
    await expect(await body.findByText("Password reset link sent to Jordan Lee")).toBeInTheDocument();
  },
};

/** Locking a display name saves, toasts and updates just that row in place; reopening the menu offers "Unlock". */
export const LockDisplayNameUpdatesRowInPlace: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ users: [orgUser, secondOrgUser] });
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    await userEvent.click(body.getByRole("menuitem", { name: "Lock display name" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      expect.stringContaining("/display-name-lock"), { display_name_locked: true },
    ));
    await expect(await body.findByText("Alex Morgan's display name locked.")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    await expect(body.getByRole("menuitem", { name: "Unlock display name" })).toBeInTheDocument();
  },
};

/** "Remove from {org}" is offered on a user other than the caller, behind the Tier 1 `ConfirmDialog` of `PreferencesPage.tsx`'s "Leave organisation". */
export const UsersActionsMenuRemoveFromOrg: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ users: [orgUser, secondOrgUser] });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("jordan@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Jordan Lee's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Remove from organisation" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Remove Jordan Lee from this organisation?" });
    await expect(api.delete).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-2/membership`)
    );
  },
};

/** "Add to group" uses the `addGroupMember` handler of the group's `SidePanel` member picker, from the user's row through
 * `AddToGroupControl`'s anchored `Popover`. */
export const UsersActionsMenuAddToGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ users: [orgUser, secondOrgUser] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("jordan@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add Jordan Lee to a group" }));
    const popover = within(document.body).getByRole("dialog", { name: "Add Jordan Lee to a group" });
    await userEvent.selectOptions(within(popover).getByLabelText("Group"), "grp1");
    await userEvent.click(within(popover).getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/groups/grp1/members`, { user_id: "user-2" })
    );
  },
};

/** "Invite user" is an email-only `Modal` (the invitee sets the name and password at signup) calling `POST /orgs/{id}/pending-invites`. */
export const InviteUserOpensModalAndCreates: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add user" })).toBeInTheDocument());
    // "New user" and "Invite user" are distinct, clearly-labelled items of the one "Add user" menu.
    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    const addMenu = within(document.body).getByRole("menu", { name: "Add user" });
    await expect(within(addMenu).getByRole("menuitem", { name: "New user" })).toBeInTheDocument();
    await expect(within(addMenu).getByRole("menuitem", { name: "Invite user" })).toBeInTheDocument();
    await expect(within(addMenu).getByRole("menuitem", { name: "New service user" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Invite user" }));
    const dialog = body.getByRole("dialog", { name: "Invite user" });
    // Email only — no password/name field, unlike "New user"'s modal.
    await expect(within(dialog).queryByLabelText("Password")).not.toBeInTheDocument();
    await expect(within(dialog).queryByLabelText("Name")).not.toBeInTheDocument();
    await expect(within(dialog).getByRole("button", { name: "Send invite" })).toBeDisabled();

    await userEvent.type(within(dialog).getByLabelText("Email"), "sam@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send invite" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/pending-invites`, { email: "sam@example.com" })
    );
    await expect(body.getByText("Invite sent")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Cancelling the "Invite user" modal sends nothing. */
export const InviteUserModalCancel: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add user" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Invite user" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Invite user" });
    await userEvent.type(within(dialog).getByLabelText("Email"), "discarded@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Discard changes" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** A pending, not-yet-accepted organisation invite is a `kind: "invited"` row in the Users table: email, invited-by, sent date, a status
 * badge (through `PENDING_INVITE_STATUS_LABEL`) and a Resend button in place of the role/status/last-login/2FA columns. */
const pendingOrgInvite: OrgPendingInvite = {
  id: "invite-1", email: "invitee@example.com", status: "pending",
  created_at: "2026-08-20T00:00:00Z", expires_at: "2026-09-03T00:00:00Z",
  invited_by_display_name: "Alex Morgan",
};

export const UsersSectionShowsInvitedRowWithResend: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ orgInvites: [pendingOrgInvite] });
    spyOn(api, "post").mockResolvedValue(pendingOrgInvite);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("invitee@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Invited by Alex Morgan")).toBeInTheDocument();
    await expect(canvas.getByText("Pending")).toBeInTheDocument();
    // A real user row still shows its role dropdown, not an em-dash or a Resend button.
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Resend invite to invitee@example.com" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/pending-invites/invite-1/resend`)
    );
    // Toasts render via a portal to `document.body`, not inside `canvas`.
    await expect(within(document.body).getByText("Invite resent to invitee@example.com.")).toBeInTheDocument();
  },
};

/** Unchecking "Show invited" (`FilterCheckbox`, default on) hides invited rows without touching real user rows. */
export const UsersSectionHideInvitedFilter: Story = {
  beforeEach: () => mockOrgAdminApis({ orgInvites: [pendingOrgInvite] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("invitee@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("checkbox", { name: "Show invited" }));
    await expect(canvas.queryByText("invitee@example.com")).not.toBeInTheDocument();
    // The real user row stays.
    await expect(canvas.getByText("alex@example.com")).toBeInTheDocument();
  },
};

/** The `FilterField` role filter (`org_role`, supported server-side) narrows the table to users holding the selected `OrgRole`, through
 * `ORG_ROLE_LABEL` rather than a raw enum string. */
export const UsersSectionRoleFilterNarrowsResults: Story = {
  beforeEach: () => mockOrgAdminApis({ users: [orgUser, secondOrgUser] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("jordan@example.com")).toBeInTheDocument();

    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Organisation role" }), "Project creator");
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("org_role=project_creator"))
    );
    await expect(canvas.getByText("jordan@example.com")).toBeInTheDocument();
    await expect(canvas.queryByText("alex@example.com")).not.toBeInTheDocument();
  },
};

/** The `FilterCheckbox`es in the shared `FilterPanel` are independent, so "stale AND no 2FA" is expressible. */
export const UsersSectionMigratedFilterCheckboxesWorkIndependently: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("checkbox", { name: "Stale (180+ days)" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("stale_since_days=180"))
    );
    // Checking a second, independent filter keeps the first one applied —
    // both params present on the same request.
    await userEvent.click(canvas.getByRole("checkbox", { name: "No 2FA" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(
        expect.stringMatching(/stale_since_days=180.*has_2fa=false|has_2fa=false.*stale_since_days=180/)
      )
    );
  },
};

/** Branding sets the report accent colour (separate from the UI accent) and whether reports carry the logo. */
export const BrandingSetsTheReportAccentAndLogo: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    const own = await canvas.findByRole("checkbox", { name: "Give reports their own accent colour" });
    await expect(own).not.toBeChecked();
    await expect(canvas.queryByLabelText("Report accent colour")).not.toBeInTheDocument();
    await userEvent.click(own);
    await canvas.findByLabelText("Report accent colour");
    await userEvent.click(canvas.getByRole("checkbox", { name: /^Include .* logo$/ }));
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/branding`,
        expect.objectContaining({ report_accent_color_hex: expect.stringMatching(/^#[0-9a-fA-F]{6}$/), report_include_logo: false }),
      ),
    );
  },
};

/** The footer position follows the platform unless the organisation chooses its own; choosing the empty option goes back to following. */
export const BrandingChoosesTheSignInFooterPosition: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    const position = await canvas.findByLabelText("Footer position");
    await expect(position).toHaveValue("");
    await expect(within(position).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Platform setting (After the content)", "After the content", "Bottom of the page",
    ]);
    await userEvent.selectOptions(position, "bottom_of_page");
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding`, expect.objectContaining({ footer_position: "bottom_of_page" })),
    );
  },
};

/** An organisation with its own position shows it selected, and returning to the platform setting sends `null`. */
export const ClearingTheFooterPositionSendsNull: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ org: { ...org, footer_position: "bottom_of_page" } });
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    const position = await canvas.findByLabelText("Footer position");
    await expect(position).toHaveValue("bottom_of_page");
    await userEvent.selectOptions(position, "");
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding`, expect.objectContaining({ footer_position: null })),
    );
  },
};

/** An organisation with its own report accent shows it checked, and clearing the box sends `null` (follow the UI accent). */
export const ClearingTheReportAccentSendsNull: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ org: { ...org, report_accent_color_hex: "#aa0000" } });
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    const own = await canvas.findByRole("checkbox", { name: "Give reports their own accent colour" });
    await expect(own).toBeChecked();
    await userEvent.click(own);
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/branding`, expect.objectContaining({ report_accent_color_hex: null }),
      ),
    );
  },
};

/** Column-header sorting on the backend-paginated Users table (`USERS_PAGE_SIZE`/`LoadMoreButton`) refetches with `sort`/`order`
 * rather than reordering the loaded page. */
export const UsersSectionSortByEmail: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=email&order=asc"))
    );
    const th = canvas.getByRole("button", { name: "Email" }).closest("th");
    await expect(th).toHaveAttribute("aria-sort", "ascending");

    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=email&order=desc"))
    );
  },
};

/** "View access" opens a read-only `SidePanel` of every project the user has a role on, their roles there, which project group
 * granted them and which organisation groups they belong to, assembled server-side (`GET /orgs/{id}/users/{id}/access`). Each project
 * row shows `collapseProjectRoles()`'s collapsed summary with a "Show all N roles" toggle for the full set (docs/decisions.md,
 * `docs/ux-style-guide.md` "Pattern: role display"); this story pins the collapsed default (`ViewUserAccessPanelExpandRoles`
 * covers the expanded state). */
export const ViewUserAccessPanel: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      userAccess: {
        org_groups: [{ id: "grp1", name: "Engineering" }],
        projects: [
          {
            project_id: "proj1", project_name: "Atlas Platform",
            roles: ["project_manager", "member"],
            project_groups: [{ id: "pg1", name: "Project Managers" }],
          },
        ],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    const actionsMenu = within(document.body).getByRole("menu", { name: "Alex Morgan's actions" });
    await userEvent.click(within(actionsMenu).getByRole("menuitem", { name: "View Alex Morgan's access" }));
    const panel = within(document.body).getByRole("dialog", { name: "Alex Morgan's access" });
    await waitFor(() => expect(within(panel).getByText("Engineering")).toBeInTheDocument());
    await expect(within(panel).getByText("Atlas Platform")).toBeInTheDocument();
    await expect(within(panel).getByText("Project manager")).toBeInTheDocument();
    await expect(within(panel).getByText(/Project Managers/)).toBeInTheDocument();

    // `["project_manager", "member"]` collapses to `["project_manager"]` (the sole top tier); "Member" stays hidden until the row's expand toggle.
    await expect(within(panel).queryByText("Member")).not.toBeInTheDocument();
    await expect(within(panel).getByRole("button", { name: "Show all 2 roles" })).toBeInTheDocument();
  },
};

/** Expanding a project row's "Show all N roles" toggle reveals the full role set (the audit detail), and the toggle becomes "Show fewer". */
export const ViewUserAccessPanelExpandRoles: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      userAccess: {
        org_groups: [],
        projects: [
          {
            project_id: "proj1", project_name: "Atlas Platform",
            // Held through different group memberships (see `collapseProjectRoles()`); collapses to `["project_manager"]`, hiding the other three,
            // which the toggle recovers.
            roles: ["project_manager", "project_administrator", "stakeholder", "member"],
            project_groups: [],
          },
        ],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    const actionsMenu = within(document.body).getByRole("menu", { name: "Alex Morgan's actions" });
    await userEvent.click(within(actionsMenu).getByRole("menuitem", { name: "View Alex Morgan's access" }));
    const panel = within(document.body).getByRole("dialog", { name: "Alex Morgan's access" });
    await waitFor(() => expect(within(panel).getByText("Atlas Platform")).toBeInTheDocument());

    await expect(within(panel).getByText("Project manager")).toBeInTheDocument();
    await expect(within(panel).queryByText("Project administrator")).not.toBeInTheDocument();
    await expect(within(panel).queryByText("Stakeholder")).not.toBeInTheDocument();
    await expect(within(panel).queryByText("Member")).not.toBeInTheDocument();

    const toggle = within(panel).getByRole("button", { name: "Show all 4 roles" });
    await userEvent.click(toggle);
    await expect(within(panel).getByText("Project manager")).toBeInTheDocument();
    await expect(within(panel).getByText("Project administrator")).toBeInTheDocument();
    await expect(within(panel).getByText("Stakeholder")).toBeInTheDocument();
    await expect(within(panel).getByText("Member")).toBeInTheDocument();
    await expect(within(panel).getByRole("button", { name: "Show fewer" })).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("button", { name: "Show fewer" }));
    await expect(within(panel).getByRole("button", { name: "Show all 4 roles" })).toBeInTheDocument();
    await expect(within(panel).queryByText("Project administrator")).not.toBeInTheDocument();
  },
};

/** A server administrator who is not a member of this organisation gets the degraded view (join as admin, or bootstrap an admin user) instead of the normal page. */
export const NotAMemberServerAdminDegradedView: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-2", is_server_admin: true }))],
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(403, "You are not a member of this organisation."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("You are not a member of this organisation")).toBeInTheDocument());
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

/** The entity quick-switch chevron is also the way off this degraded page: a server administrator stuck here (the organisation is
 * disabled) can jump to another organisation through the `?mine=true` sibling list Organisation Overview uses. */
export const DisabledOrgEntitySwitcherOffersOtherOrgs: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-2", is_server_admin: true }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === `/api/v1/orgs/${ORG_ID}`) return org;
      if (path === "/api/v1/orgs?mine=true") return [org, { ...org, id: "org-2", name: "Globex Corporation" }];
      throw new ApiError(403, "This organisation is disabled.");
    });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("This organisation is disabled.")).toBeInTheDocument());

    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getByRole("link", { name: "Globex Corporation" })).toHaveAttribute(
      "href",
      "/orgs/org-2/admin"
    );
  },
};

/** The entity quick-switch chevron is also on the normal admin header, whose title renders through `ResourceMenu`'s `titleAdornment` slot. */
export const EntitySwitcherOffersOtherOrgs: Story = {
  beforeEach: () => mockOrgAdminApis({ orgs: [org, { ...org, id: "org-2", name: "Globex Corporation" }] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());

    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getByRole("link", { name: "Globex Corporation" })).toHaveAttribute(
      "href",
      "/orgs/org-2/admin"
    );
  },
};

/** The name is edited on the Details group; Save renames through the name endpoint and sends no company details. */
export const OrganisationDetailsRenamesTheOrganisation: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockImplementation(async (path: string) =>
      path === `/api/v1/orgs/${ORG_ID}/name` ? { ...org, name: "Renamed Corp" } : org
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Organisation actions" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Organisation details" }));
    const name = await canvas.findByLabelText(/^Name/);
    await expect(name).toHaveValue("Acme Corp");
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed Corp");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/name`, { name: "Renamed Corp" }));
    await expect(api.put).toHaveBeenCalledTimes(1);
    await expect(canvas.getByRole("heading", { name: "Renamed Corp" })).toBeInTheDocument();
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Details saved")).toBeInTheDocument();
  },
};

/** The company details show the platform values as placeholders, and Save sends only the field that changed. */
export const OrganisationDetailsSavesOnlyTheChangedCompanyField: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue({ ...org, email_footer_company_name: "Acme Pty Ltd" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Organisation details" }));
    const company = await canvas.findByLabelText("Company name");
    await expect(company).toHaveValue("");
    // With no logo of its own the platform logo is shown under a muted caption, and there is nothing to remove.
    await expect(canvas.getByText("Platform default")).toBeVisible();
    await expect(canvas.queryByRole("button", { name: /^Remove/ })).toBeNull();
    await expect(company).toHaveAttribute("placeholder", "Platform Co");
    await expect(canvas.getByLabelText("Postal address")).toHaveAttribute("placeholder", "1 Platform Way");
    await userEvent.type(company, "Acme Pty Ltd");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding`, { email_footer_company_name: "Acme Pty Ltd" }),
    );
    await expect(api.put).toHaveBeenCalledTimes(1);
  },
};

/** The logo and the company details are on Organisation details; Branding & defaults keeps the appearance only. */
export const BrandingNoLongerHoldsTheLogoOrCompanyDetails: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Organisation details" }));
    await canvas.findByLabelText("Organisation logo");
    await expect(canvas.getByLabelText("Company name")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    await canvas.findByLabelText(/^Header title/);
    await expect(canvas.queryByLabelText("Organisation logo")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText("Company name")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText("Postal address")).not.toBeInTheDocument();
    await expect(canvas.getByLabelText("Login page background image")).toBeInTheDocument();
    await userEvent.type(canvas.getByLabelText(/^Header title/), "Acme");
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const [, body] = (api.put as unknown as { mock: { calls: [string, Record<string, unknown>][] } }).mock.calls[0];
    await expect(Object.keys(body).filter((key) => key.startsWith("email_footer"))).toEqual([]);
  },
};

/** The other half of the same `ActionMenu`: "Export {org} bundle" calls the export flow directly, with no modal. */
export const ExportOrgBundleViaActionMenu: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["fake zip"]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Organisation actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Organisation actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Export organisation bundle" }));

    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/export`));
  },
};

export const BrandingSectionSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Branding is under the "Branding & defaults" group, open by default, so selecting the group is enough.
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
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

/** Style guide "Pattern: platform default vs. override": an empty text field uses the platform value, which the
 * field shows as its placeholder; there is no "Custom" pill and no reset link, so emptying the field is the way back. */
export const BrandingSectionPlatformValueIsThePlaceholder: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ org: { ...org, header_title: "Acme Requirements", email_footer_company_name: null } });
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    await waitFor(() => expect(canvas.getByLabelText(/^Header title/)).toBeInTheDocument());

    await expect(canvas.queryByText("Custom")).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Reset to platform default" })).toBeNull();
    // With no login background of its own there is nothing to remove.
    await expect(canvas.queryByRole("button", { name: /^Remove/ })).toBeNull();

    // Emptying a field and saving sends null, which is the platform value again.
    const header = canvas.getByLabelText(/^Header title/);
    await expect(header).toHaveValue("Acme Requirements");
    await expect(header).toHaveAttribute("placeholder", "Platform Requirements");
    await userEvent.clear(header);
    await userEvent.click(canvas.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding`, expect.objectContaining({ header_title: null }))
    );
  },
};

/** The logo and the login background cannot be emptied, so each has a Remove button (no pill) while the
 * organisation has its own file; the logo is on Organisation details and the login background on Branding & defaults. */
export const LogoAndLoginBackgroundRemove: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ org: { ...org, logo_file_id: "file-logo-1", login_background_file_id: "file-bg-1" } });
    spyOn(api, "delete").mockImplementation(async (path: string) =>
      path.includes("kind=logo") ? { ...org, logo_file_id: null } : { ...org, login_background_file_id: null }
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Organisation details" }));
    await waitFor(() => expect(canvas.getAllByRole("button", { name: /^Remove/ })).toHaveLength(1));
    await expect(canvas.queryByText("Custom")).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: /^Remove/ }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding-image?kind=logo`));
    await expect(within(document.body).getByText("Logo removed.")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    await waitFor(() => expect(canvas.getAllByRole("button", { name: /^Remove/ })).toHaveLength(1));
    await userEvent.click(canvas.getByRole("button", { name: /^Remove/ }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/branding-image?kind=login_background`)
    );
    await expect(within(document.body).getByText("Background image removed.")).toBeInTheDocument();
  },
};

/** The company details are saved together, each field that changed. */
export const OrganisationDetailsSaveSeveralCompanyFields: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Organisation details" }));
    await waitFor(() => expect(canvas.getByLabelText("Company name")).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText("Company name"), "Acme Requirements Ltd");
    await userEvent.type(canvas.getByLabelText("Website"), "https://acme.example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/branding`,
        { email_footer_company_name: "Acme Requirements Ltd", email_footer_website: "https://acme.example.com" },
      )
    );
  },
};

/**
 * Ticking "Allow self-signup" on an SSO-only organisation shows an inline warning and disables Save instead of failing with a 422
 * (the backend rejection is covered by `test_update_advanced_settings_rejects_self_signup_for_sso_only_org`).
 */
export const SelfSignupSsoConflictBlocksSave: Story = {
  beforeEach: () => mockOrgAdminApis({ sso: { ...ssoConfig, sso_only: true } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Self-signup is in the "Security" group, open by default.
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Allow self-signup" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Allow self-signup" }));
    await expect(
      canvas.getByText("Self-signup cannot be enabled while this organisation is SSO-only — turn off \"SSO only\" in the SSO configuration below first, or turn off self-signup here.")
    ).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save security settings" })).toBeDisabled();
  },
};

/** The hierarchical-projects organisation toggle (docs/decisions.md) defaults to enabled (project managers can create sub-projects
 * without Project creator or Org admin rights); an organisation administrator can turn it off for the stricter behaviour. */
export const AdvancedSettingsAllowRelaxedChildProjectCreation: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    const toggle = await waitFor(() => canvas.getByRole("switch", { name: /Allow \S+ managers to create sub-\S+s/ }));
    await expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    await userEvent.click(canvas.getByRole("button", { name: "Save security settings" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/advanced-settings`,
        expect.objectContaining({ allow_relaxed_child_project_creation: false })
      )
    );
  },
};

/** Defaults off; an organisation administrator turning it on forces every project's `require_change_request_for_approved_links`
 * unless the project is marked exempt (`ProjectAdminPage.stories.tsx`'s `OverviewTabForcedByOrgPolicy`). */
export const AdvancedSettingsForceRequireChangeRequestForApprovedLinks: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    const toggle = await waitFor(() =>
      canvas.getByRole("switch", { name: "Require a change request for link changes on approved requirements, organisation-wide" })
    );
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await userEvent.click(canvas.getByRole("button", { name: "Save security settings" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/advanced-settings`,
        expect.objectContaining({ force_require_change_request_for_approved_links: true })
      )
    );
  },
};

export const AdvancedSettingsAllowAiApprovals: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    const toggle = await waitFor(() => canvas.getByRole("switch", { name: "Allow AI approval via MCP" }));
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);

    // Enabling opens the acknowledgment dialog (docs/decisions.md "AI approval via MCP"); its confirm button is disabled until the checkbox is checked.
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Allow AI approval for this organisation?" }));
    const confirmButton = dialog.getByRole("button", { name: "Allow AI approval" });
    await expect(confirmButton).toBeDisabled();
    await userEvent.click(dialog.getByRole("checkbox"));
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    await expect(toggle).toBeChecked();

    await userEvent.click(canvas.getByRole("button", { name: "Save security settings" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/advanced-settings`,
        expect.objectContaining({ allow_ai_approvals: true })
      )
    );
  },
};

export const AdvancedSettingsRequire2fa: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Require two-factor authentication" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Require two-factor authentication" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save security settings" }));
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
    // The test email is in the "SMTP & email" card of the "Email" group.
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Send test email" })).toBeEnabled());
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/test-email`, {})
    );
    await expect(canvas.getByText(/Test email sent/)).toBeInTheDocument();
  },
};

/** SMTP fields save through the `OrgAdvancedSettings` PUT that the Security group's save button also submits; the Email group has its own save button. */
export const EmailSettingsSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByLabelText("SMTP host")).toBeInTheDocument());
    await userEvent.type(canvas.getByLabelText("SMTP host"), "smtp.example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Save email settings" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/advanced-settings`,
        expect.objectContaining({ smtp_host: "smtp.example.com" })
      )
    );
  },
};

export const SsoSectionSaveDisabledWhenNotConfigured: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // SSO/OIDC and SCIM share the "OAuth/SSO" group (both identity-provisioning integrations; docs/decisions.md).
    await userEvent.click(canvas.getByRole("link", { name: "OAuth/SSO" }));
    await waitFor(() => expect(canvas.getByLabelText("OIDC issuer URL")).toHaveValue("https://idp.example.com"));
  },
};

/** In Org Groups a `DirectoryTable` row's Name cell opens a `SidePanel`, as Project Groups do. */
export const GroupsSectionOpensSidePanel: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    // Members column shows the count without opening anything.
    await expect(canvas.getByRole("cell", { name: "1 member(s)" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    await expect(within(document.body).getByRole("dialog", { name: "Engineering details" })).toBeInTheDocument();
  },
};

/** Organisation groups are deletable: the side panel's Delete opens a Tier 1 confirmation naming the group; confirming calls the delete
 * endpoint, closes the panel and toasts. */
export const GroupsSectionDeleteGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = body.getByRole("dialog", { name: "Engineering details" });
    await userEvent.click(within(panel).getByRole("button", { name: "Delete group" }));

    const confirm = body.getByRole("dialog", { name: 'Delete "Engineering"?' });
    await expect(within(confirm).getByText(/Members lose every role and project access/)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete group" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/groups/grp1`));
    await expect(body.getByText("Group deleted")).toBeInTheDocument();
    await waitFor(() => expect(body.queryByRole("dialog", { name: "Engineering details" })).not.toBeInTheDocument());
  },
};

/** A refused delete (e.g. a module relies on the group) shows the server's reason as an error toast and leaves the group. */
export const GroupsSectionDeleteGroupRefused: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "delete").mockRejectedValue(
      new ApiError(400, "This group is this organisation's designated fallback compliance-managers group."),
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    await userEvent.click(within(body.getByRole("dialog", { name: "Engineering details" })).getByRole("button", { name: "Delete group" }));
    await userEvent.click(within(body.getByRole("dialog", { name: 'Delete "Engineering"?' })).getByRole("button", { name: "Delete group" }));
    await expect(await body.findByText(/designated fallback compliance-managers group/)).toBeInTheDocument();
    await expect(body.getByRole("dialog", { name: "Engineering details" })).toBeInTheDocument();
  },
};

/** The SSO group-to-role mapping belongs to the group being synced into: set with its SSO group name and saved by one button in the
 * group's `SidePanel`. The mock's `ssoConfig` has an issuer and client id, so the sync sub-section renders; Engineering is not synced
 * (`idp_synced_group_name: null`), so the toggle starts unchecked and the name and role fields hidden. */
export const GroupsSectionSaveIdpSyncAndGrantedRole: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "patch").mockResolvedValue({ ...groups[0], idp_synced_group_name: "eng-team", granted_org_role: "member" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });

    const toggle = within(panel).getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" });
    await expect(toggle).not.toBeChecked();
    await expect(within(panel).queryByPlaceholderText("e.g. eng-team")).not.toBeInTheDocument();
    await userEvent.click(toggle);

    await userEvent.type(within(panel).getByPlaceholderText("e.g. eng-team"), "eng-team");
    await userEvent.selectOptions(within(panel).getByLabelText("Grants role on sync"), "member");
    await userEvent.click(within(panel).getByRole("button", { name: "Save sync settings" }));

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/groups/grp1`,
        { idp_synced_group_name: "eng-team", granted_org_role: "member" }
      )
    );
    // Principle 7: every mutation ends with feedback.
    await expect(within(document.body).getByText("Sync settings updated")).toBeInTheDocument();
  },
};

/** An already synced group (`idp_synced_group_name` non-null) opens with the toggle checked and the name and role fields populated. */
export const GroupsSectionSyncToggleDefaultsCheckedWhenAlreadySynced: Story = {
  beforeEach: () =>
    mockOrgAdminApis({
      groups: [{ ...groups[0], idp_synced_group_name: "eng-team", granted_org_role: "member" }, groups[1]],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });

    await expect(within(panel).getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" })).toBeChecked();
    await expect(within(panel).getByPlaceholderText("e.g. eng-team")).toHaveValue("eng-team");
    await expect(within(panel).getByLabelText("Grants role on sync")).toHaveValue("member");
  },
};

/** Unchecking the toggle clears the sync name and granted role at once through the `PATCH` Save uses, since no fields remain to edit. */
export const GroupsSectionToggleSyncOffClearsFields: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      groups: [{ ...groups[0], idp_synced_group_name: "eng-team", granted_org_role: "member" }, groups[1]],
    });
    spyOn(api, "patch").mockResolvedValue({ ...groups[0], idp_synced_group_name: null, granted_org_role: null });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });

    const toggle = within(panel).getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" });
    await expect(toggle).toBeChecked();
    await userEvent.click(toggle);

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/groups/grp1`,
        { idp_synced_group_name: null, granted_org_role: null }
      )
    );
    await expect(within(panel).queryByPlaceholderText("e.g. eng-team")).not.toBeInTheDocument();
  },
};

/** Without SSO configured for the organisation the whole sync sub-section (name input, role select, toggle and Save) is absent,
 * not just the role select; only the muted hint renders. */
export const GroupsSectionSsoSyncSectionHiddenWithoutSso: Story = {
  beforeEach: () => mockOrgAdminApis({ sso: { slug: null, sso_enabled: false, sso_only: false, oidc_issuer_url: null, oidc_client_id: null, oidc_required_group: null, oidc_allow_account_creation: true } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });

    await expect(within(panel).queryByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" })).not.toBeInTheDocument();
    await expect(within(panel).queryByPlaceholderText("e.g. eng-team")).not.toBeInTheDocument();
    await expect(within(panel).queryByLabelText("Grants role on sync")).not.toBeInTheDocument();
    await expect(within(panel).queryByRole("button", { name: "Save sync settings" })).not.toBeInTheDocument();
    await expect(within(panel).getByText(/Set up SSO\/OIDC/)).toBeInTheDocument();
  },
};

export const ScimSectionGenerateToken: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue({ token: "rtm_scim_fake-secret-value", token_prefix: "rtm_scim_fak" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "OAuth/SSO" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    // A group's member list renders only once its row is opened (style guide "Pattern: directories at scale").
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });
    await expect(within(panel).getByText(/Alex Morgan/)).toBeInTheDocument();
  },
};

export const GroupsSectionNestGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Engineering" }));
    const panel = within(document.body).getByRole("dialog", { name: "Engineering details" });

    // Exactly one <option>Platform</option> exists (Engineering's nest-picker): Platform's own row excludes itself and offers "Engineering".
    const platformOption = within(panel).getByText("Platform", { selector: "option" });
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

/** Style guide "Pattern: modal dialog for entity create/rename" (Principle 3): "+ New group" opens a Modal with just a name field. */
export const GroupsSectionCreateGroupViaModal: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Groups" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByText("No tokens currently reach this organisation.")).toBeInTheDocument());
  },
};

const onePat: OrgPersonalAccessToken = {
  id: "pat-1", user_id: "user-1", user_email: "alex@example.com", user_display_name: "Alex Morgan",
  name: "MCP server", token_prefix: "rtm_pat_abcd", expires_at: "2027-01-01T00:00:00Z",
  other_org_count: 0, last_used_at: null, created_at: "2026-01-01T00:00:00Z",
};

/** Revoking an organisation-scoped PAT opens the shared `ConfirmDialog`, then shows a success toast. */
export const PatsSectionRevokeOneConfirms: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ pats: [onePat] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByText("MCP server")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Revoke" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Revoke this token outright?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/pats/pat-1/revoke`));
  },
};

/** Cancelling the revoke confirmation leaves the token untouched. */
export const PatsSectionRevokeOneCancelled: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ pats: [onePat] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByText("MCP server")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Revoke" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Revoke this token outright?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
    await expect(canvas.getByText("MCP server")).toBeInTheDocument();
  },
};

export const ProjectStatusesAddAndReorder: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Projects$/ }));
    await waitFor(() => expect(canvas.getByDisplayValue("Proposed")).toBeInTheDocument());
    const dialog = await openAddDialog(canvas, "New status");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Deprecated");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/project-statuses`,
        { name: "Deprecated" }
      )
    );
  },
};

/** With one project status left, the delete control is disabled (§4.0's minimum-one-remaining rule) rather than offered and then rejected. */
export const ProjectStatusesDeleteDisabledAtLastRow: Story = {
  beforeEach: () => mockOrgAdminApis({ projectStatuses: [buildProjectStatus({ id: "st1", name: "Active", sort_order: 0 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Projects$/ }));
    await waitFor(() => expect(canvas.getByDisplayValue("Active")).toBeInTheDocument());
    // Scope to the Active row itself: the project statuses are the only list with this "only one left" title here.
    const row = canvas.getByDisplayValue("Active").closest<HTMLElement>(".stack")!;
    await expect(within(row).getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
  },
};

/** Deleting a status assigned to a project returns 409; the UI opens the shared in-use dialog with the server's in-use message (§4.0). */
export const ProjectStatusesDeleteInUseOpensDialog: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "delete").mockRejectedValue(new ApiError(409, "This status is used by 3 project(s). Pass reassign_to_id to move them to another status before deleting."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Projects$/ }));
    await waitFor(() => expect(canvas.getByDisplayValue("Proposed")).toBeInTheDocument());
    const row = canvas.getByDisplayValue("Proposed").closest<HTMLElement>(".stack")!;
    await userEvent.click(within(row).getByTitle("Delete this status"));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByText(/used by 3 project\(s\)/)).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Confirm delete" })).toBeDisabled();
  },
};

export const LinkTypesAddAndRename: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Workflow$/ }));
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    // The list shows only the existing rows; the new link type is made in the dialog the Add button opens.
    const dialog = await openAddDialog(canvas, "New link type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Forward name" }), "Supersedes");
    await userEvent.type(dialog.getByRole("textbox", { name: "Reverse name" }), "Is superseded by");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/link-types`,
        { forward_name: "Supersedes", reverse_name: "Is superseded by" }
      )
    );
  },
};

/** Setting a link type's direction PATCHes it at once (names unchanged) and toasts; the select shows the stored direction. */
export const LinkTypesSetDirection: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      linkTypes: [buildLinkType({ id: "lt1", forward_name: "Derives from", reverse_name: "Is the source of", flow: "forward_is_upstream" })],
    });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Workflow$/ }));
    const select = await canvas.findByRole("combobox", { name: "Direction: Derives from" });
    await expect(select).toHaveValue("forward_is_upstream");
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "No direction", "Target is upstream", "Target is downstream",
    ]);
    await userEvent.selectOptions(select, "forward_is_downstream");
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/link-types/lt1`, {
        forward_name: "Derives from", reverse_name: "Is the source of", flow: "forward_is_downstream",
      })
    );
    await waitFor(() => expect(within(document.body).getByText("Link type direction updated.")).toBeInTheDocument());
  },
};

/** The minimum-one-remaining rule of project statuses applies to link types. */
export const LinkTypesDeleteDisabledAtLastRow: Story = {
  beforeEach: () =>
    mockOrgAdminApis({ linkTypes: [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of", sort_order: 0 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: /^Workflow$/ }));
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
  },
};

/** The "Modules" group of a deployment with no registered modules shows the empty state, not an empty table. */
export const ModulesSectionEmptyState: Story = {
  beforeEach: () => mockOrgAdminApis({ modules: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() =>
      expect(canvas.getByText("No modules are registered on this deployment yet.")).toBeInTheDocument()
    );
  },
};

const entitledEnabledModule: OrgModule = {
  module_key: "fake_module", name: "Fake Module", description: "A fixture module used only by this story.",
  version: "0.1.0", implemented: true, entitled: true, enabled: true, default_project_enabled: true,
  default_enabled: true, frontend_manifest: null,
};

/** An entitled, implemented module has one three-state availability select; "Available, off for new projects" sends both levers in one
 * `PUT` and toasts (feedback-on-every-mutation). */
export const ModulesSectionChangeAvailability: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ modules: [entitledEnabledModule] });
    spyOn(api, "put").mockResolvedValue({ ...entitledEnabledModule, default_project_enabled: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    const select = canvas.getByRole("combobox", { name: "Fake Module availability" });
    await expect(select).toHaveValue("default_on");
    await expect(select).toBeEnabled();

    await userEvent.selectOptions(select, "opt_in");
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/modules/fake_module`, { enabled: true, default_project_enabled: false },
      )
    );
    await expect(
      within(document.body).getByText("Fake Module: Available, off for new projects")
    ).toBeInTheDocument();
  },
};

/** A hard-disabled module reads "Off": one control, with no separate default lever. */
export const ModulesSectionHardDisabledModuleShowsOff: Story = {
  beforeEach: () =>
    mockOrgAdminApis({
      modules: [{ ...entitledEnabledModule, enabled: false, default_project_enabled: true }],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());
    await expect(canvas.getByRole("combobox", { name: "Fake Module availability" })).toHaveValue("off");
  },
};

const fixtureSubComponent = (overrides: Partial<OrgModuleSubComponent> = {}): OrgModuleSubComponent => ({
  module_key: "fake_module", subcomponent_key: "widget", name: "Widget",
  default_enabled: true, enabled: true, default_project_enabled: true, has_org_override: false,
  ...overrides,
});

/** Sub-components start collapsed behind a one-line summary; expanding shows one availability select per sub-component, which
 * `PUT`s the sub-component endpoint with both levers. */
export const ModulesSectionSubComponentAvailability: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      modules: [entitledEnabledModule],
      moduleSubComponents: { fake_module: [fixtureSubComponent()] },
    });
    spyOn(api, "put").mockResolvedValue(fixtureSubComponent({ enabled: false, has_org_override: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());
    await expect(canvas.queryByText("Widget")).not.toBeInTheDocument();

    const disclosure = canvas.getByRole("button", { name: "1 component · all on" });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(disclosure);
    await expect(canvas.getByText("Widget")).toBeInTheDocument();

    const select = canvas.getByRole("combobox", { name: "Widget (Fake Module) availability" });
    await expect(select).toHaveValue("default_on");
    await userEvent.selectOptions(select, "off");
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/modules/fake_module/subcomponents/widget`,
        { enabled: false, default_project_enabled: false },
      )
    );
    await expect(within(document.body).getByText("Widget: Off")).toBeInTheDocument();
  },
};

/** A module with no declared sub-components renders no disclosure at all. */
export const ModulesSectionNoSubComponentsRendersNoDisclosure: Story = {
  beforeEach: () => mockOrgAdminApis({ modules: [entitledEnabledModule] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: /components/ })).not.toBeInTheDocument();
  },
};

/** Non-entitled modules are shown unavailable with an explanatory note (not hidden) and a disabled select, so an administrator cannot self-enable them. */
export const ModulesSectionNonEntitledModuleIsGreyedOut: Story = {
  beforeEach: () =>
    mockOrgAdminApis({
      modules: [{ ...entitledEnabledModule, entitled: false, enabled: false }],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    await expect(
      canvas.getByText("Not available on this organisation's current plan. Contact your server administrator to request access.")
    ).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Fake Module availability" })).toBeDisabled();
  },
};

/** A registered-but-not-implemented module is disabled with its own note, distinct from the non-entitled case. */
export const ModulesSectionNotYetImplementedModuleIsDisabled: Story = {
  beforeEach: () =>
    mockOrgAdminApis({
      modules: [{ ...entitledEnabledModule, implemented: false, enabled: false }],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    await expect(canvas.getByText("Not yet available in this version of the application.")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Fake Module availability" })).toBeDisabled();
  },
};

/** An enabled installed module's `orgAdminSections` entry renders as a `ResourceMenu` group beside the ten core groups, and its
 * `render({ orgId })` receives this organisation's id: the generic mechanism needs no hardcoded `activeGroup === "..."` block or
 * static import for the fixture module. */
export const ModuleContributedOrgAdminSectionRendersWhenEnabled: Story = {
  beforeEach: () => mockOrgAdminApis({ modules: [fixtureOrgModule()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Fixture admin section" }));
    await waitFor(() =>
      expect(canvas.getByText(`Fixture admin section content for org ${ORG_ID}`)).toBeInTheDocument()
    );
  },
};

/** A module-contributed section disappears from the navigation when the organisation's module-enablement toggle turns it off. Here the
 * fixture module is entitled but not enabled (the Modules section's "toggled off" state) and its section must not appear. */
export const ModuleContributedOrgAdminSectionHiddenWhenModuleDisabled: Story = {
  beforeEach: () => mockOrgAdminApis({ modules: [fixtureOrgModule({ enabled: false })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await expect(canvas.queryByRole("link", { name: "Fixture admin section" })).not.toBeInTheDocument();
  },
};

/** The same disappearance when a module is not reported at all (absent from `GET /orgs/{id}/modules`), not just present but disabled. */
export const ModuleContributedOrgAdminSectionHiddenWhenModuleNotReported: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await expect(canvas.queryByRole("link", { name: "Fixture admin section" })).not.toBeInTheDocument();
  },
};

// --- Fine-Grained Access Control (core): Role Management ---------------

const fixturePermissions: Permission[] = [
  { key: "requirement:view:", label: "requirement — view", artefact_type: "requirement", level: "view", subtype: null },
  { key: "requirement:manage:", label: "requirement — manage", artefact_type: "requirement", level: "manage", subtype: null },
  { key: "grant_roles", label: "Grant Roles", artefact_type: null, level: null, subtype: null },
];

const fixtureCustomRole: CustomRoleDefinition = {
  id: "role-1", organization_id: ORG_ID, name: "Reviewer", description: "Reviews requirements.",
  scope: "org", created_by: "user-1", created_at: "2026-02-01T00:00:00Z", permissions: ["requirement:view:"],
};

/** An organisation administrator defines a custom role: the Modal (style guide "Pattern: modal dialog for entity create/rename") takes
 * a name and a permission atom from `PermissionPicker`, saves with `POST .../custom-roles` and the role appears without a reload. */
export const RoleManagementCreateCustomRole: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ permissions: fixturePermissions });
    spyOn(api, "post").mockResolvedValue({ ...fixtureCustomRole, id: "role-new", permissions: ["grant_roles"] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Role management" }));
    // "No custom roles defined yet." appears twice (definitions table and assignment section), so assert on the "New custom role" button.
    await waitFor(() => expect(canvas.getByRole("button", { name: "New custom role" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New custom role" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New custom role" });
    await userEvent.type(within(dialog).getByLabelText("Name"), "Reviewer");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Grant Roles" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles`, {
        name: "Reviewer", description: "", scope: "org", permissions: ["grant_roles"],
      })
    );
    await expect(within(document.body).getByText("Custom role created")).toBeInTheDocument();
    await waitFor(() => expect(canvas.getAllByText("Reviewer").length).toBeGreaterThan(0));
  },
};

/** Starting from a preset (the Link editor) fills the form with the preset's name,
 * description, scope and its "all record types" permissions; the admin can still change
 * anything before saving. */
export const RoleManagementCreateFromLinkEditorPreset: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      permissions: [
        { key: "*:link:", label: "all record types — link", artefact_type: "*", level: "link", subtype: null },
        ...fixturePermissions,
      ],
      customRolePresets: [{
        key: "link_editor", name: "Link editor", description: "Set and remove links on any record of a project.",
        scope: "project", permissions: ["*:link:"],
      }],
    });
    spyOn(api, "post").mockResolvedValue({ ...fixtureCustomRole, id: "role-new", name: "Link editor" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Role management" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New custom role" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "New custom role" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New custom role" });
    await userEvent.selectOptions(await within(dialog).findByLabelText("Start from a preset"), "Link editor");

    await expect(within(dialog).getByLabelText("Name")).toHaveValue("Link editor");
    await expect(within(dialog).getByRole("checkbox", { name: "all record types — link" })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles`, {
        name: "Link editor", description: "Set and remove links on any record of a project.",
        scope: "project", permissions: ["*:link:"],
      })
    );
  },
};

/** Deleting a custom role asks a Tier 1 `ConfirmDialog` (style guide Principle 6), not type-to-confirm. */
export const RoleManagementDeleteCustomRoleConfirm: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ permissions: fixturePermissions, customRoles: [fixtureCustomRole] });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Role management" }));
    // "Reviewer" appears twice (definitions row and the assignment section's card); wait for both.
    await waitFor(() => expect(canvas.getAllByText("Reviewer").length).toBe(2));

    await userEvent.click(canvas.getByRole("button", { name: "Delete Reviewer" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Delete custom role?" });
    await expect(within(dialog).getByText(/This removes "Reviewer"/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles/role-1`)
    );
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.queryAllByText("Reviewer").length).toBe(0));
  },
};

/** An organisation-scoped custom role merges into the Users table's Roles dropdown beside the fixed and module roles, as
 * `UsersSectionModuleRoleGrantAndRevoke` proves for module roles. Jordan holds it (revoke path); Alex does not (grant path). */
export const UsersSectionCustomRoleGrantAndRevoke: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      users: [orgUser, { ...secondOrgUser, custom_roles: [{ custom_role_id: "role-1", name: "Reviewer" }] }],
      customRoles: [fixtureCustomRole],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const alexRoles = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(alexRoles).getByRole("checkbox", { name: "Grant Reviewer to Alex Morgan" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles/role-1/users/user-1`, {})
    );

    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's roles" }));
    const jordanRoles = within(document.body).getByRole("group", { name: "Jordan Lee's roles" });
    await userEvent.click(within(jordanRoles).getByRole("checkbox", { name: "Revoke Reviewer from Jordan Lee" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles/role-1/users/user-2`)
    );
  },
};

/** The entity-scope picker is generic (Compliance's `"standard"` scope is its first use): the scope dropdown's "Standard" option
 * comes from `GET .../entity-scopes`, the assignment card's entity picker is disabled until an entity is chosen, and granting sends
 * `scope_entity_id` (never `project_id`). */
const fixtureEntityScopeStandard = { key: "standard", label: "Standard", entities: [{ id: "std-1", name: "ISO 27001" }] };
const fixtureStandardScopedRole: CustomRoleDefinition = {
  id: "role-2", organization_id: ORG_ID, name: "Standard Reviewer", description: "Reviews one standard's content.",
  scope: "standard", created_by: "user-1", created_at: "2026-02-01T00:00:00Z",
  permissions: ["project_compliance_requirement:manage:"],
};

export const RoleManagementEntityScopedGrantAndRevoke: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      permissions: [
        ...fixturePermissions,
        {
          key: "project_compliance_requirement:manage:", label: "project_compliance_requirement — manage",
          artefact_type: "project_compliance_requirement", level: "manage", subtype: null,
        },
      ],
      customRoles: [fixtureStandardScopedRole],
      entityScopes: [fixtureEntityScopeStandard],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Role management" }));
    await waitFor(() => expect(canvas.getAllByText("Standard Reviewer").length).toBe(2));

    // The definitions table's scope column shows the registered scope's label, not the raw "standard" key.
    await expect(canvas.getByRole("cell", { name: "Standard" })).toBeInTheDocument();

    const grantBox = canvas.getByRole("combobox", { name: "Grant Standard Reviewer — search a user or group" });
    await expect(grantBox).toHaveAttribute("placeholder", "Select a Standard first");

    const entityPicker = canvas.getByLabelText("Standard", { selector: "select" });
    await userEvent.selectOptions(entityPicker, "std-1");

    await userEvent.type(grantBox, "Alex");
    const grantOption = await canvas.findByRole("option", { name: /Alex Morgan/ });
    await userEvent.click(grantOption);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/custom-roles/role-2/users/user-1`, {
        project_id: null, scope_entity_id: "std-1",
      })
    );
    await waitFor(() => expect(within(document.body).getByText("Granted to Alex Morgan")).toBeInTheDocument());

    const revokeBox = canvas.getByRole("combobox", { name: "Revoke Standard Reviewer — search a user or group" });
    await userEvent.type(revokeBox, "Alex");
    const revokeOption = await canvas.findByRole("option", { name: /Alex Morgan/ });
    await userEvent.click(revokeOption);
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/custom-roles/role-2/users/user-1?scope_entity_id=std-1`
      )
    );
    await waitFor(() => expect(within(document.body).getByText("Revoked from Alex Morgan")).toBeInTheDocument());
  },
};

/** A caller for whom `GET .../advanced-settings` 403s (the signal for every ORG_ADMIN-only section) sees the assignment half of Role
 * Management but not the role-definition half: they can grant or revoke a defined role, not create, edit or delete one. */
export const RoleManagementDefinitionsHiddenForNonAdmin: Story = {
  beforeEach: () => mockOrgAdminApis({ advancedForbidden: true, customRoles: [fixtureCustomRole] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Role management" }));

    await expect(canvas.queryByRole("button", { name: "New custom role" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("No custom roles defined yet.")).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.getByText("Grant roles to users or groups")).toBeInTheDocument());
    await expect(canvas.getByText("Reviewer")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "dark" } };

/** The body of the n-th `api.put` call the story's spy has recorded. */
function putBody(n: number): Record<string, unknown> {
  return (api.put as unknown as { mock: { calls: unknown[][] } }).mock.calls[n][1] as Record<string, unknown>;
}

/** Each Save under Security, Email and Reports sends only its own group's fields, so an unsaved edit in another
 * group is neither saved nor reset. */
export const SavesSendOnlyTheirOwnGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByLabelText("SMTP host")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save email settings" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const emailBody = putBody(0);
    await expect(emailBody).toHaveProperty("smtp_host");
    await expect(emailBody).not.toHaveProperty("require_2fa");
    await expect(emailBody).not.toHaveProperty("pat_max_lifetime_days");

    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Save security settings" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    const securityBody = putBody(1);
    await expect(securityBody).toHaveProperty("require_2fa");
    await expect(securityBody).not.toHaveProperty("smtp_host");
    await expect(securityBody).not.toHaveProperty("pat_max_lifetime_days");

    await userEvent.click(canvas.getByRole("button", { name: "Save token lifetime" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(3));
    await expect(putBody(2)).toEqual({ pat_max_lifetime_days: null });
  },
};

/** The SSO save is confirmed with a toast. */
export const SsoSaveShowsAToast: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(ssoConfig);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "OAuth/SSO" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Save SSO settings" }));
    await expect(await within(document.body).findByText("SSO settings saved.")).toBeInTheDocument();
  },
};

/** Regenerating or revoking the live SCIM token asks first, and each outcome ends in a toast. */
export const ScimRegenerateAndRevokeAskFirst: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ scim: { enabled: true, token_prefix: "rtm_scim_abc" } });
    spyOn(api, "post").mockResolvedValue({ token: "rtm_scim_new-secret", token_prefix: "rtm_scim_new" });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "OAuth/SSO" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Regenerate SCIM token" }));
    const regenerate = within(await within(document.body).findByRole("dialog", { name: "Regenerate the SCIM token?" }));
    await userEvent.click(regenerate.getByRole("button", { name: "Cancel" }));
    await expect(api.post).not.toHaveBeenCalled();

    await userEvent.click(canvas.getByRole("button", { name: "Regenerate SCIM token" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog")).getByRole("button", { name: "Regenerate SCIM token" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/scim-token`));
    await expect(await canvas.findByDisplayValue("rtm_scim_new-secret")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Revoke" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Revoke the SCIM token?" })).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/scim-token`));
  },
};

/** A group with a single section shows it as a headed card with no accordion toggle. */
export const SingleSectionGroupHasNoAccordion: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByLabelText("SMTP host")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: /section$/ })).toBeNull();
  },
};

/** Projects and Workflow are separate entries; the earlier combined address lands on Projects. */
export const ProjectsAndWorkflowAreSeparateGroups: Story = {
  beforeEach: () => mockOrgAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link", { name: "Projects & workflow" })).toBeNull();
    await userEvent.click(canvas.getByRole("link", { name: /^Workflow$/ }));
    await expect(await canvas.findByRole("heading", { name: "Stage workflows" })).toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Link types" })).toBeInTheDocument();
    await expect(canvas.queryByRole("heading", { name: "Project statuses" })).toBeNull();
    await userEvent.click(canvas.getByRole("link", { name: /^Projects$/ }));
    await expect(await canvas.findByRole("heading", { name: "Project statuses" })).toBeInTheDocument();
    await expect(canvas.queryByRole("heading", { name: "Stage workflows" })).toBeNull();
  },
};
