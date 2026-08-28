import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { MyMemberships, NotificationPreference, Organization, OrgUser, PersonalAccessToken, PersonalAccessTokenCreateResult } from "../api/types";
import { ThemeProvider } from "../context/ThemeContext";
import { buildProjectListItem, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { PreferencesPage } from "./PreferencesPage";

const org: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
};

const notificationPrefs: NotificationPreference[] = [
  { type: "comment_added", ui_enabled: true, email_enabled: true },
  { type: "change_request_submitted", ui_enabled: true, email_enabled: false },
];

const myMemberships: MyMemberships = {
  organizations: [
    {
      organization_id: "org-1", organization_name: "Acme Corp", org_roles: ["org_admin"],
      groups: [
        { id: "g1", name: "Engineering", direct: true },
        { id: "g2", name: "Platform", direct: false },
      ],
      projects: [{ id: "p1", name: "Atlas Platform", roles: ["project_manager"] }],
    },
  ],
};

function mockPreferencesApis(userId: string, opts: { pats?: PersonalAccessToken[] } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/notifications/preferences")) return notificationPrefs;
    if (path.includes("archived=false")) return [buildProjectListItem({ id: "p1", organization_id: "org-1", name: "Atlas Platform" })];
    // Must come before the generic "/me/pats" check below — that check's
    // `.includes` would otherwise also match this path (a real
    // unmocked-route bug found via a story: it silently returned `[]`
    // instead of the expected `{max_expires_at}` shape).
    if (path.includes("/me/pats/max-lifetime")) return { max_expires_at: "2027-01-01T00:00:00Z" };
    if (path.includes("/me/pats")) return opts.pats ?? [];
    if (path === "/api/v1/orgs") return [org];
    if (path.includes("/auth/me/memberships")) return myMemberships;
    if (path.includes("/users")) return [{ user_id: userId, email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false, roles: ["org_admin"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false }] satisfies OrgUser[];
    throw new Error(`unmocked path: ${path}`);
  });
}

const withThemeProvider: Decorator = (Story) => <ThemeProvider>{Story()}</ThemeProvider>;

const meta: Meta<typeof PreferencesPage> = {
  title: "Pages/PreferencesPage",
  component: PreferencesPage,
  decorators: [withStatefulAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })), withThemeProvider, withRouter("/preferences", "/preferences/:group?"), withToast()],
};
export default meta;

type Story = StoryObj<typeof PreferencesPage>;

export const ProfileTabSave: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Display name")).toHaveValue("Alex Morgan");
    await userEvent.clear(canvas.getByLabelText("Display name"));
    await userEvent.type(canvas.getByLabelText("Display name"), "Alexis Morgan");
    await userEvent.click(canvas.getByRole("button", { name: "Save preferences" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        "/api/v1/auth/me/preferences",
        expect.objectContaining({ display_name: "Alexis Morgan" })
      )
    );
    await expect(canvas.getByText("Preferences saved.")).toBeInTheDocument();
  },
};

export const SecurityTabChangePassword: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    // "Change password" is a `variant="plain"` CollapsibleSection with no
    // `defaultCollapsed`, so it's already expanded — no click needed.
    await userEvent.type(canvas.getByPlaceholderText("Current password"), "old-password");
    await userEvent.type(canvas.getByPlaceholderText("New password"), "new-password-123");
    await userEvent.click(canvas.getByRole("button", { name: "Change password" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/auth/change-password", {
        current_password: "old-password",
        new_password: "new-password-123",
      })
    );
  },
};

export const SecurityTabStart2FAEnrollment: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "post").mockResolvedValue({ secret: "ABCD1234", qr_code_png_base64: "" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await expect(canvas.getByText("Not enabled")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("switch", { name: "Enable 2FA" }));
    await waitFor(() => expect(canvas.getByText(/Scan this QR code/)).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Confirm code")).toBeInTheDocument();
  },
};

export const AccessTabShowsOrgsAndProjects: Story = {
  beforeEach: () => mockPreferencesApis("user-1"),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Your access" }));
    await waitFor(() => expect(canvas.getByText("Acme Corp")).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Manage organisation" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Atlas Platform" })).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByText("Engineering")).toBeInTheDocument());
    await expect(canvas.getByText("Platform")).toBeInTheDocument();
    await expect(canvas.getByText("(via a nested group)")).toBeInTheDocument();
  },
};

/** "Leave organisation" (2026-08 UX audit roadmap item 520) moved here
 * from Org Admin — it's about this user's own membership, not an org-level
 * setting. Previously fired with zero confirmation; now Tier 1
 * `ConfirmDialog` + `Toast`, matching every other ordinary/reversible
 * mutation in the app. */
export const AccessTabLeaveOrganisationConfirms: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Your access" }));
    await waitFor(() => expect(canvas.getByText("Acme Corp")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Leave Acme Corp" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Leave Acme Corp?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Leave" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1/membership"));
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Left organisation")).toBeInTheDocument();
  },
};

/** Cancelling the confirm dialog leaves membership untouched. */
export const AccessTabLeaveOrganisationCancel: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Your access" }));
    await waitFor(() => expect(canvas.getByText("Acme Corp")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Leave Acme Corp" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Leave Acme Corp?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.delete).not.toHaveBeenCalled();
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
  },
};

export const PatsTabNoneYet: Story = {
  beforeEach: () => mockPreferencesApis("user-1", { pats: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    await waitFor(() => expect(canvas.getByText("You haven't created any Personal Access Tokens yet.")).toBeInTheDocument());
  },
};

export const PatsTabCreateToken: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1", { pats: [] });
    spyOn(api, "post").mockResolvedValue({
      id: "pat-1", name: "MCP server", token: "rtm_pat_abc123", token_prefix: "rtm_pat_",
      allowed_organizations: [{ id: "org-1", name: "Acme Corp" }], allowed_projects: [],
      expires_at: "2027-01-01T00:00:00Z", created_at: "2026-01-01T00:00:00Z",
    } satisfies PersonalAccessTokenCreateResult);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    // The create form opens in a `Modal` (2026-08 UX audit roadmap item
    // 526 — a brand-new PAT has no "what came before it" to be contextual
    // detail about, per the revised Principle 3), portalled to
    // `document.body` rather than nested inside the tab panel.
    await userEvent.click(canvas.getByRole("button", { name: "New personal access token" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New personal access token" });
    await waitFor(() => expect(within(dialog).getByPlaceholderText('e.g. "MCP server"')).toBeInTheDocument());
    await userEvent.type(within(dialog).getByPlaceholderText('e.g. "MCP server"'), "MCP server");
    // The org checklist populates asynchronously (each org's own
    // membership-confirming fetch), independent of the dialog already
    // being visible.
    await waitFor(() => expect(within(dialog).getByLabelText("Acme Corp")).toBeInTheDocument(), { timeout: 3000 });
    await userEvent.click(within(dialog).getByLabelText("Acme Corp"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create token" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(canvas.getByText("Token created")).toBeInTheDocument());
    await expect(canvas.getByText("rtm_pat_abc123")).toBeInTheDocument();
  },
};

const onePat: PersonalAccessToken = {
  id: "pat-1", name: "MCP server", token_prefix: "rtm_pat_abcd",
  allowed_organizations: [{ id: "org-1", name: "Acme Corp" }], allowed_projects: [],
  expires_at: "2027-01-01T00:00:00Z", revoked_at: null, last_used_at: null, created_at: "2026-01-01T00:00:00Z",
};

/** Revoking a token opens the shared `ConfirmDialog` (sixth-pass audit —
 * this used to fire via `window.confirm`), then shows a success toast. */
export const PatsTabRevokeConfirms: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1", { pats: [onePat] });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    await waitFor(() => expect(canvas.getByText("MCP server")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Revoke" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Revoke this token?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/me/pats/pat-1"));
    await expect(within(document.body).getByText("Token revoked")).toBeInTheDocument();
  },
};

/** Cancelling the revoke confirmation leaves the token untouched. */
export const PatsTabRevokeCancelled: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1", { pats: [onePat] });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    await waitFor(() => expect(canvas.getByText("MCP server")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Revoke" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Revoke this token?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.delete).not.toHaveBeenCalled();
  },
};

export const PatsTabCreateRequiresOrg: Story = {
  beforeEach: () => mockPreferencesApis("user-1", { pats: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    await userEvent.click(canvas.getByRole("button", { name: "New personal access token" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New personal access token" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Create token" })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("button", { name: "Create token" }));
    await waitFor(() => expect(within(dialog).getByText("Select at least one organisation.")).toBeInTheDocument());
  },
};

/** Cancelling the "New personal access token" modal creates nothing. */
export const PatsTabCreateModalCancel: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1", { pats: [] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Personal Access Tokens" }));
    await userEvent.click(canvas.getByRole("button", { name: "New personal access token" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New personal access token" });
    await userEvent.type(within(dialog).getByPlaceholderText('e.g. "MCP server"'), "Discarded token");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

export const NotificationsTabToggleAndSave: Story = {
  beforeEach: () => {
    mockPreferencesApis("user-1");
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Notification preferences" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save preferences" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Save preferences" })).toBeDisabled();
    const [firstCheckbox] = canvas.getAllByRole("checkbox");
    await userEvent.click(firstCheckbox);
    await expect(canvas.getByRole("button", { name: "Save preferences" })).toBeEnabled();
    await userEvent.click(canvas.getByRole("button", { name: "Save preferences" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
  },
};

export const LightTheme: Story = { ...ProfileTabSave, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ProfileTabSave, globals: { theme: "dark" } };
