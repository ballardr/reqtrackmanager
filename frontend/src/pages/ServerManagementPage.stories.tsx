import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ServerAccess, ServerSettings, SignupConfig, SystemUser } from "../api/types";
import { buildPolicySummary, buildUser, withAuth, withRouter, withToast } from "../testing/storybook-helpers";
import { ServerManagementPage } from "./ServerManagementPage";

function systemUser(overrides: Partial<SystemUser>): SystemUser {
  return {
    user_id: "u1", email: "orphan@example.com", display_name: "Orphan User", is_active: true,
    is_banned: false, last_login_at: "2026-02-01T09:00:00Z", is_2fa_enabled: false,
    created_at: "2026-01-01T09:00:00Z", is_server_admin: false, server_roles: [],
    has_org_membership: false,
    organization_count: 0, organization_names: [], group_names: [],
    ...overrides,
  };
}

const SERVER_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null,
  default_login_background_file_id: null,
  email_footer_company_name: "ReqTrackManager", email_footer_website: "https://reqtrackmanager.example.com",
  email_footer_address: "1 Example Street\nExample City, EX1 1AA",
  footer_prefix: null, company_id_label: null, company_id: null,
  org_label_singular: null, org_label_plural: null,
  file_uploads_enabled: true,
};

const ADMIN_ACCESS: ServerAccess = {
  roles: ["server_admin"], can_view_organizations: true, can_create_organizations: true, can_delete_organizations: true,
  can_manage_entitlements: true, can_administer_server: true,
};

const SIGNUP_CONFIG: SignupConfig = { signup_mode: "disabled", self_signup_organizations: [] };

function mockServerManagementApis(users: SystemUser[], settings: ServerSettings = SERVER_SETTINGS) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/system/branding")) return settings;
    if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
    if (path.includes("/system/default-storage-quota")) return { default_storage_quota_bytes: null };
    if (path === "/api/v1/system/access") return ADMIN_ACCESS;
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockImplementation(async (path: string) => {
    if (path.includes("/system/users")) return { items: users, total: users.length };
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ServerManagementPage> = {
  title: "Pages/ServerManagementPage",
  component: ServerManagementPage,
  decorators: [withRouter("/server/management", "/server/management/:group?"), withToast(), withAuth(buildUser({ is_server_admin: true }))],
};
export default meta;

type Story = StoryObj<typeof ServerManagementPage>;

export const AccessReviewOrphanedAccounts: Story = {
  beforeEach: () => mockServerManagementApis([systemUser({})]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("None")).toBeInTheDocument();

    // Deactivate/ban/assign-roles now all sit behind one `ActionMenu` kebab
    // instead of separate always-visible buttons/columns — style guide
    // "Pattern: action menu", same "OrgAdminPage.tsx" consolidation applied
    // here. "Assign server roles" lives here, not in its own always-visible "Server roles" dropdown column
    // — see `AccessReviewGrantServerAdmin` below.
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await expect(within(menu).getByRole("menuitem", { name: "Deactivate" })).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: "Assign server roles" }));
    const rolesGroup = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await expect(
      within(rolesGroup).getByRole("checkbox", { name: "Grant Server admin to Orphan User" })
    ).not.toBeChecked();
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
    // 2 groups fits the compact summary as-is, no "+N more"/modal needed.
    await expect(canvas.getByText("Engineering, Platform")).toBeInTheDocument();
  },
};

/** Past 2 groups the row shows a "+N
 * more" summary instead of an unbounded joined string, with the full list
 * reachable via "View groups" on the row's `ActionMenu`. */
export const AccessReviewGroupsShowMoreAndViewGroups: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({
        user_id: "u1",
        email: "grouped@example.com",
        display_name: "Grouped User",
        group_names: ["Engineering", "Platform", "Security", "Data"],
      }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("grouped@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Engineering, Platform, +2 more")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Grouped User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Grouped User's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "View groups" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Grouped User's groups" });
    for (const name of ["Engineering", "Platform", "Security", "Data"]) {
      await expect(within(dialog).getByText(name)).toBeInTheDocument();
    }
  },
};

/** The Organisations column stays inline
 * (unlike Groups above) but gains a "Show all N" toggle past 2 orgs. */
export const AccessReviewOrganisationsShowMore: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({
        user_id: "u1",
        email: "multiorg@example.com",
        display_name: "Multi Org User",
        has_org_membership: true,
        organization_count: 3,
        organization_names: ["Alpha Robotics", "Beta Systems", "Gamma Labs"],
      }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("multiorg@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Alpha Robotics, Beta Systems")).toBeInTheDocument();
    await expect(canvas.queryByText("Gamma Labs")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Show all 3" }));
    await expect(canvas.getByText("Alpha Robotics, Beta Systems, Gamma Labs")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Show fewer" }));
    await expect(canvas.getByText("Alpha Robotics, Beta Systems")).toBeInTheDocument();
  },
};

export const AccessReviewBannedAndAdminBadges: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({ user_id: "u1", email: "banned@example.com", display_name: "Banned User", is_banned: true, is_active: false }),
      systemUser({ user_id: "u2", email: "admin@example.com", display_name: "Admin User", is_server_admin: true }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Banned")).toBeInTheDocument());
    // The old standalone "Server admin" badge, and the "Server roles"
    // dropdown's own closed-state summary that replaced it, are both gone —
    // role state sits behind an "Assign server roles" modal with no row-level summary
    // at all, so this now opens the modal to confirm the checked state.
    await userEvent.click(canvas.getByRole("button", { name: "Admin User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Admin User's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Assign server roles" }));
    const rolesGroup = within(document.body).getByRole("group", { name: "Admin User's server roles" });
    await expect(
      within(rolesGroup).getByRole("checkbox", { name: "Revoke Server admin from Admin User" })
    ).toBeChecked();
  },
};

/** Account state is a Status column of pills (Active, Deactivated, Banned), not muted text in the actions cell. */
export const AccessReviewStatusColumn: Story = {
  beforeEach: () =>
    mockServerManagementApis([
      systemUser({ user_id: "u1", email: "active@example.com", display_name: "Active User" }),
      systemUser({ user_id: "u2", email: "off@example.com", display_name: "Off User", is_active: false }),
      systemUser({ user_id: "u3", email: "banned@example.com", display_name: "Banned User", is_active: false, is_banned: true }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("active@example.com")).toBeInTheDocument());
    const table = canvas.getByRole("table", { name: "Users" });
    await expect(within(table).getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    await expect(within(table).getByText("Active")).toBeInTheDocument();
    await expect(within(table).getByText("Deactivated")).toBeInTheDocument();
    await expect(within(table).getByText("Banned")).toBeInTheDocument();
  },
};

/** Revoking every Personal Access Token on the deployment cannot be undone, so it needs the typed word (Tier 2). */
export const RevokeAllTokensNeedsTypedConfirmation: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "post").mockResolvedValue({ revoked_count: 4 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Revoke all Personal Access Tokens platform-wide" }));
    const dialog = within(document.body).getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Revoke all Personal Access Tokens platform-wide" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole("textbox"), "Revoke");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/pats/revoke-all"));
    await expect(await within(document.body).findByText("Revoked 4 token(s) platform-wide.")).toBeInTheDocument();
  },
};

/** A person with no server role is told so, with a way home, instead of being redirected silently. */
export const NoServerAccessShowsAMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/system/access") {
        return { roles: [], can_view_organizations: false, can_create_organizations: false, can_delete_organizations: false, can_manage_entitlements: false, can_administer_server: false };
      }
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("You do not have access to server management.")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Return to the home page" })).toHaveAttribute("href", "/");
  },
};

/** Granting server admin opens the shared `ConfirmDialog` (sixth-pass audit
 * — this used to fire via `window.confirm`), then shows a success toast
 * once the role change completes. Role
 * checkboxes moved from an always-visible "Server roles" dropdown column
 * into an "Assign server roles" modal opened from
 * the `ActionMenu`, rendered directly rather than via `MultiSelectDropdown`
 * — see `docs/decisions.md`. Still confirms via `ConfirmDialog` first,
 * since this grant is cross-tenant. */
export const AccessReviewGrantServerAdmin: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Assign server roles" }));
    const rolesGroup = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await userEvent.click(within(rolesGroup).getByRole("checkbox", { name: "Grant Server admin to Orphan User" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Grant server admin to this user?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Grant server admin" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/users/u1/server-admin", { is_server_admin: true }));
    await expect(within(document.body).getByText("Server admin granted")).toBeInTheDocument();
  },
};

/** Granting `MODULE_ADMINISTRATOR` follows the exact
 * same modal-then-`ConfirmDialog` flow as server admin above, via the new
 * `/server-roles` grant endpoint rather than `/server-admin`. */
export const AccessReviewGrantModuleAdministrator: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Assign server roles" }));
    const rolesGroup = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await userEvent.click(
      within(rolesGroup).getByRole("checkbox", { name: "Grant Module administrator to Orphan User" })
    );

    const dialog = within(document.body).getByRole("dialog", { name: "Grant module administrator to this user?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Grant module administrator" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/users/u1/server-roles", { role: "module_administrator" })
    );
    await expect(within(document.body).getByText("Module administrator granted")).toBeInTheDocument();
  },
};

/** The Platform subscription manager and Subscription removal authority are granted through the same dialog, each
 * with its own confirmation naming what the role can do. */
export const AccessReviewGrantSubscriptionRoles: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Assign server roles" }));
    const rolesGroup = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await userEvent.click(
      within(rolesGroup).getByRole("checkbox", { name: "Grant Subscription removal authority to Orphan User" })
    );

    const dialog = within(document.body).getByRole("dialog", { name: "Grant Subscription removal authority to this user?" });
    await expect(within(dialog).getByText(/permanently delete an organisation and all of its data/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Grant Subscription removal authority" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/users/u1/server-roles", { role: "subscription_removal_authority" })
    );
    await expect(within(document.body).getByText("Subscription removal authority granted")).toBeInTheDocument();
  },
};

/** A Platform subscription manager sees only per-organisation availability: no other group, no policy or defaults. */
export const SubscriptionManagerSeesOnlyModules: Story = {
  decorators: [withAuth(buildUser({ is_server_admin: false }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/system/access") {
        return {
          roles: ["subscription_manager"], can_view_organizations: true, can_create_organizations: true,
          can_delete_organizations: false, can_manage_entitlements: true, can_administer_server: false,
        } satisfies ServerAccess;
      }
      if (path === "/api/v1/orgs") return [];
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // One group only, so the menu is not drawn and the Modules content shows directly.
    await expect(await canvas.findByText("Availability per organisation")).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Access review" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Entitlement policy")).not.toBeInTheDocument();
  },
};

/** Deactivating an account also confirms via `ConfirmDialog`; cancelling
 * leaves the account untouched (the pilot pattern's paired cancel story). */
export const AccessReviewDeactivateCancelled: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const actionsMenu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await userEvent.click(within(actionsMenu).getByRole("menuitem", { name: "Deactivate" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Deactivate this account?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** U-P-06 "Scale: two unbounded lists" — the deployment's
 * cross-org user directory previously fetched every matching user with no
 * `limit`/`offset` at all. Clicking "Load more" requests the next page at
 * the correct offset and appends its rows below the first page's. */
export const AccessReviewLoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/system/branding")) return SERVER_SETTINGS;
      if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
      if (path === "/api/v1/system/access") return ADMIN_ACCESS;
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      if (offset === 0) return { items: [systemUser({ user_id: "u1", email: "first@example.com" })], total: 2 };
      return { items: [systemUser({ user_id: "u2", email: "second@example.com" })], total: 2 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("first@example.com")).toBeInTheDocument());
    const loadMore = canvas.getByRole("button", { name: /Load more/ });
    await expect(loadMore).toBeInTheDocument();

    await userEvent.click(loadMore);
    await waitFor(() => expect(canvas.getByText("second@example.com")).toBeInTheDocument());
    // The first page's row is still there — appended, not replaced.
    await expect(canvas.getByText("first@example.com")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

/** Access Review moved onto the
 * shared `DirectoryTable` + `FilterPanel` layout (Org Admin's Users table
 * is the direct composition template). Pins that the pre-existing "view"/
 * "includeDeactivated" filters still behave identically now that they're a
 * `FilterField`/`FilterCheckbox` instead of a bare `<select>`/checkbox row,
 * and that the new search box narrows the request via the new backend
 * `search` param. */
export const AccessReviewFilterPanelSearchAndFilters: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/system/branding")) return SERVER_SETTINGS;
      if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
      if (path === "/api/v1/system/access") return ADMIN_ACCESS;
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      if (!path.includes("/system/users")) throw new Error(`unmocked path: ${path}`);
      return { items: [systemUser({ email: "orphan@example.com" })], total: 1 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());

    // "Show" (view) is now a `FilterField` <select> — same accessible name
    // and options as the old bare <select> it replaced.
    await expect(canvas.getByLabelText("Show")).toBeInTheDocument();
    // "includeDeactivated" is now a `FilterCheckbox` — same accessible name.
    await expect(canvas.getByLabelText("Include deactivated accounts")).toBeInTheDocument();

    const search = canvas.getByPlaceholderText("Search by name or email");
    await userEvent.type(search, "orphan");
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("search=orphan"))
    );

    // Follow-up UX fix: this table's columns (Email, Name, Last login,
    // Created, Organizations, Groups, Actions) crowded the old
    // `.side-grid` sidebar, so its `FilterPanel` now renders `layout="top"`
    // (a full-width bar above the table) instead — see
    // docs/ux-style-guide.md's "Pattern: filter panel placement — side vs.
    // top".
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** Column-header sorting — Email/Name/Last login/Created are
 * sortable via `DirectoryTable`'s `SortableHeader`, backed by
 * `list_system_users`'s new `sort`/`order` params (mirrors `list_org_
 * users`'s pre-existing contract) so the full filtered result re-sorts
 * correctly, not just the currently loaded page. */
export const AccessReviewSortByEmail: Story = {
  beforeEach: () => mockServerManagementApis([systemUser({ user_id: "u1", email: "orphan@example.com" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringMatching(/sort=email&order=asc/))
    );

    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringMatching(/sort=email&order=desc/))
    );
  },
};

export const PlatformBrandingTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
    await waitFor(() => expect(canvas.getByLabelText(/^Default header title/)).toBeInTheDocument());
    await expect(canvas.getByLabelText("Default login page background image")).toBeInTheDocument();
    // Nothing has changed yet, so Save is unavailable.
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** Save sends only the Platform branding fields (a partial update) and confirms with a toast. */
export const PlatformBrandingSave: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ ...SERVER_SETTINGS, default_header_title: "Acme" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
    await userEvent.type(await canvas.findByLabelText(/^Default header title/), "Acme");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/v1/system/branding", {
        default_header_title: "Acme", org_label_singular: null, org_label_plural: null, accent_color_hex: "#475569",
      }),
    );
    await expect(await within(document.body).findByText("Platform branding saved.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** A failed save is drawn beside Save, and the edit stays. */
export const PlatformBrandingSaveFailure: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockRejectedValue(new ApiError(422, "The accent colour is invalid."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
    await userEvent.type(await canvas.findByLabelText(/^Default header title/), "Acme");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The accent colour is invalid.");
    await expect(canvas.getByLabelText(/^Default header title/)).toHaveValue("Acme");
  },
};

/** The footer company details (prefix, name, website, address, company identifier) are on Server details, and saving sends only those fields. */
export const ServerDetailsEmailFooter: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ ...SERVER_SETTINGS, email_footer_company_name: "Acme Platform Inc" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Server details" }));
    // "Company name" also wraps a trailing hint <span>, so its accessible name is longer than "Company name" alone.
    await waitFor(() => expect(canvas.getByLabelText(/^Company name/)).toHaveValue("ReqTrackManager"));
    await expect(canvas.getByLabelText("Website")).toHaveValue("https://reqtrackmanager.example.com");
    await expect(canvas.getByLabelText("Postal address")).toHaveValue("1 Example Street\nExample City, EX1 1AA");
    await userEvent.clear(canvas.getByLabelText(/^Company name/));
    await userEvent.type(canvas.getByLabelText(/^Company name/), "Acme Platform Inc");
    await userEvent.type(canvas.getByLabelText(/^Prefix/), "Hosted by");
    await userEvent.type(canvas.getByLabelText(/^Company identifier label/), "ABN");
    await userEvent.type(canvas.getByLabelText(/^Company identifier$/), "12 345 678 901");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/v1/system/branding", {
        email_footer_company_name: "Acme Platform Inc",
        email_footer_website: "https://reqtrackmanager.example.com",
        email_footer_address: "1 Example Street\nExample City, EX1 1AA",
        footer_prefix: "Hosted by",
        company_id_label: "ABN",
        company_id: "12 345 678 901",
      }),
    );
    await expect(await within(document.body).findByText("Server details saved.")).toBeInTheDocument();
  },
};

/** The platform logo is platform-owned and can be removed again, which reverts to the built-in picture. */
export const ServerDetailsRemoveLogo: Story = {
  beforeEach: () => {
    mockServerManagementApis([], { ...SERVER_SETTINGS, default_logo_file_id: "11111111-1111-1111-1111-111111111111" });
    spyOn(api, "delete").mockResolvedValue({ ...SERVER_SETTINGS, default_logo_file_id: null });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Server details" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/system/branding/image?kind=logo"));
    await expect(await within(document.body).findByText("Logo removed.")).toBeInTheDocument();
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Remove" })).toBeNull());
  },
};

/** The organisation terminology is on Platform branding and the built-in words are the placeholders. */
export const PlatformBrandingOrgLabel: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ ...SERVER_SETTINGS, org_label_singular: "tenant", org_label_plural: "Tenants" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
    const singular = await canvas.findByLabelText(/^Organisation label \(singular\)/);
    await expect(singular).toHaveValue("");
    await expect(singular).toHaveAttribute("placeholder", "organisation");
    await userEvent.type(singular, "tenant");
    await userEvent.type(canvas.getByLabelText(/^Organisation label \(plural\)/), "Tenants");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/v1/system/branding",
        expect.objectContaining({ org_label_singular: "tenant", org_label_plural: "Tenants" }),
      ),
    );
  },
};

/** Sign-up keeps its own Save: unavailable until the mode changes. */
export const SignupModeTab: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ signup_mode: "org_specified", self_signup_organizations: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Public sign-up" }));
    await waitFor(() => expect(canvas.getByLabelText("Sign-up mode")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(canvas.getByLabelText("Sign-up mode"), "org_specified");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/signup-config", { signup_mode: "org_specified" }));
    await expect(await within(document.body).findByText("Sign-up mode saved.")).toBeInTheDocument();
  },
};

/** The deployment-wide file upload switch: turning it off and saving sends the setting and tells the provider to read it again. */
export const FileUploadsSwitch: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ file_uploads_enabled: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "File uploads" }));
    const toggle = await canvas.findByRole("switch", { name: "Allow file uploads" });
    await expect(toggle).toBeChecked();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(toggle);
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/file-uploads", { file_uploads_enabled: false }));
  },
};

/** The default storage limit of organisations that have none: entered in GB and saved in bytes with the switch. */
export const DefaultStorageLimit: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "put").mockResolvedValue({ file_uploads_enabled: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "File uploads" }));
    const amount = await canvas.findByRole("spinbutton", { name: "Default storage limit" });
    await expect(amount).toHaveAttribute("placeholder", "No limit");
    await userEvent.type(amount, "2");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/v1/system/default-storage-quota", { default_storage_quota_bytes: 2 * 1024 ** 3 }),
    );
  },
};

export const TestEmailTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Send test email" })).toBeInTheDocument());
    await expect(canvas.getByLabelText(/^Recipient email/)).toBeInTheDocument();
  },
};

export const TestEmailSendSuccess: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/test-email", {}));
    await expect(await within(document.body).findByText(/Test email sent/)).toBeInTheDocument();
  },
};

export const TestEmailSendFailure: Story = {
  beforeEach: () => {
    mockServerManagementApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(502, "Failed to send test email: connection refused"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await expect(await within(document.body).findByText(/connection refused/)).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "dark" } };

/** Any account can be sent a reset link by a server administrator (Tier 1 confirm, toast). */
export const AccessReviewSendsAPasswordResetLink: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Send password reset link" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Send a password reset link to Orphan User?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send link" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/users/u1/password-reset"));
    await expect(await within(document.body).findByText("Password reset link sent to Orphan User")).toBeInTheDocument();
  },
};

/** Requiring one person to choose a new password goes through the force-reset endpoint with the user scope. */
export const AccessReviewRequiresANewPassword: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Require new password" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Require a new password?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Require new password" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/credentials/force-reset", {
        scope: "user", user_id: "u1", reset_2fa: false, send_links: true,
      }),
    );
  },
};

export const ForceCredentialResetButtonOpensTheDialog: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    const base = api.get as unknown as (path: string) => Promise<unknown>;
    spyOn(api, "get").mockImplementation(async (path: string) => (path === "/api/v1/orgs" ? [] : base(path)));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Force a credential reset…" }));
    await expect(within(document.body).getByRole("dialog", { name: "Force a credential reset" })).toBeInTheDocument();
  },
};

export const AddUserButtonOpensTheDialog: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    const base = api.get as unknown as (path: string) => Promise<unknown>;
    spyOn(api, "get").mockImplementation(async (path: string) => (path === "/api/v1/orgs" ? [] : base(path)));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Add user" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New user" }));
    await expect(within(document.body).getByRole("dialog", { name: "New user" })).toBeInTheDocument();
  },
};

/** The published documents (Policies) and the export rule for personal data are separate groups with distinct names. */
export const PoliciesAndPersonalDataExportAreSeparateGroups: Story = {
  decorators: [withAuth(buildUser({ is_server_admin: true }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/system/access") return ADMIN_ACCESS;
      if (path === "/api/v1/system/policies") {
        return ["privacy", "data"].map((key) => buildPolicySummary({
          id: null, key: key as "privacy" | "data", title: key === "privacy" ? "Privacy policy" : "Data policy",
          has_unpublished_changes: false, updated_at: null,
        }));
      }
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "Personal data in exports" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("link", { name: "Policies" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/system/policies"));
    await expect(await canvas.findByRole("button", { name: "Write Privacy policy" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Write Data policy" })).toBeInTheDocument();
  },
};
