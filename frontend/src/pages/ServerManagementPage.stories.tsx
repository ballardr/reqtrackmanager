import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ServerSettings, SignupConfig, SystemUser } from "../api/types";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ServerManagementPage } from "./ServerManagementPage";

function systemUser(overrides: Partial<SystemUser>): SystemUser {
  return {
    user_id: "u1", email: "orphan@example.com", display_name: "Orphan User", is_active: true,
    is_banned: false, last_login_at: "2026-02-01T09:00:00Z", is_2fa_enabled: false,
    created_at: "2026-01-01T09:00:00Z", is_server_admin: false, is_module_administrator: false,
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
  org_label_singular: null, org_label_plural: null,
};

const SIGNUP_CONFIG: SignupConfig = { signup_mode: "disabled", self_signup_organizations: [] };

function mockServerManagementApis(users: SystemUser[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/system/branding")) return SERVER_SETTINGS;
    if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
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
  decorators: [withRouter("/server/management", "/server/management/:group?"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ServerManagementPage>;

export const AccessReviewOrphanedAccounts: Story = {
  beforeEach: () => mockServerManagementApis([systemUser({})]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("None")).toBeInTheDocument();

    // Deactivate/ban now sit behind one `ActionMenu` kebab instead of
    // separate always-visible buttons — style guide "Pattern: action menu",
    // same "OrgAdminPage.tsx" consolidation applied here. Grant/revoke
    // server admin moved to the "Server roles" `MultiSelectDropdown` column
    // (module system Phase 0) — see `AccessReviewGrantServerAdmin` below.
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Orphan User's actions" });
    await expect(within(menu).getByRole("menuitem", { name: "Deactivate" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Orphan User's server roles" })).toHaveTextContent(
      "No server roles"
    );
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
      systemUser({ user_id: "u1", email: "banned@example.com", display_name: "Banned User", is_banned: true, is_active: false }),
      systemUser({ user_id: "u2", email: "admin@example.com", display_name: "Admin User", is_server_admin: true }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Banned")).toBeInTheDocument());
    // The old standalone "Server admin" badge was dropped once the "Server
    // roles" dropdown's own closed-state summary started showing the same
    // fact (module system Phase 0) — asserted here instead.
    await expect(canvas.getByRole("button", { name: "Admin User's server roles" })).toHaveTextContent("Server admin");

    await userEvent.click(canvas.getByRole("button", { name: "Admin User's server roles" }));
    const rolesPopover = within(document.body).getByRole("group", { name: "Admin User's server roles" });
    await expect(
      within(rolesPopover).getByRole("checkbox", { name: "Revoke Server admin from Admin User" })
    ).toBeChecked();
  },
};

/** Granting server admin opens the shared `ConfirmDialog` (sixth-pass audit
 * — this used to fire via `window.confirm`), then shows a success toast
 * once the role change completes. Module system Phase 0 (docs/compliance-
 * module-plan.md): grant/revoke now lives in the "Server roles"
 * `MultiSelectDropdown` column instead of the `ActionMenu`, mirroring
 * `OrgAdminPage.tsx`'s own roles column — but, unlike that column, still
 * confirms via `ConfirmDialog` first, since this grant is cross-tenant. */
export const AccessReviewGrantServerAdmin: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's server roles" }));
    const rolesPopover = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await userEvent.click(within(rolesPopover).getByRole("checkbox", { name: "Grant Server admin to Orphan User" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Grant server admin to this user?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Grant server admin" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/users/u1/server-admin", { is_server_admin: true }));
    await expect(within(document.body).getByText("Server admin granted")).toBeInTheDocument();
  },
};

/** Module system Phase 0: granting `MODULE_ADMINISTRATOR` follows the exact
 * same dropdown-then-`ConfirmDialog` flow as server admin above, via the
 * new `/server-roles` grant endpoint rather than `/server-admin`. */
export const AccessReviewGrantModuleAdministrator: Story = {
  beforeEach: () => {
    mockServerManagementApis([systemUser({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("orphan@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Orphan User's server roles" }));
    const rolesPopover = within(document.body).getByRole("group", { name: "Orphan User's server roles" });
    await userEvent.click(
      within(rolesPopover).getByRole("checkbox", { name: "Grant Module administrator to Orphan User" })
    );

    const dialog = within(document.body).getByRole("dialog", { name: "Grant module administrator to this user?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Grant module administrator" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/users/u1/server-roles", { role: "module_administrator" })
    );
    await expect(within(document.body).getByText("Module administrator granted")).toBeInTheDocument();
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

/** U-P-06 / 2026-08 UX audit "Scale: two unbounded lists" — the deployment's
 * cross-org user directory previously fetched every matching user with no
 * `limit`/`offset` at all. Clicking "Load more" requests the next page at
 * the correct offset and appends its rows below the first page's. */
export const AccessReviewLoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/system/branding")) return SERVER_SETTINGS;
      if (path.includes("/system/signup-config")) return SIGNUP_CONFIG;
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

/** Phase E (follow-up UX batch, 2026-08-31) — Access Review moved onto the
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

/** Column-header sorting (Phase E) — Email/Name/Last login/Created are
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
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Platform branding" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Public sign-up" }));
    await waitFor(() => expect(canvas.getByLabelText("Sign-up mode")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Sign-up mode"), "org_specified");
    await expect(canvas.getByText(/Organisations opt in/)).toBeInTheDocument();
  },
};

export const TestEmailTab: Story = {
  beforeEach: () => mockServerManagementApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await userEvent.click(canvas.getByRole("button", { name: "Send test email" }));
    await waitFor(() => expect(canvas.getByText(/connection refused/)).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AccessReviewOrphanedAccounts, globals: { theme: "dark" } };
