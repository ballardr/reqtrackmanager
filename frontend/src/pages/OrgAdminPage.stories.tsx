import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { LinkTypeDefinition, OrgAdvancedSettings, OrgGroup, OrgModule, OrgPendingInvite, OrgPersonalAccessToken, OrgRole, OrgSsoConfig, OrgUser, Organization, ProjectStatusDefinition, UserAccess } from "../api/types";
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
  smtp_host: null, smtp_port: null, smtp_username: null, smtp_use_tls: true,
  pat_max_lifetime_days: null, require_2fa: false, allow_self_signup: false, auto_accept_email_domain: null,
  external_user_policy: "disabled", allow_relaxed_child_project_creation: true,
};

const ssoConfig: OrgSsoConfig = {
  slug: "acme", sso_enabled: true, sso_only: false, oidc_issuer_url: "https://idp.example.com",
  oidc_client_id: "client-1", oidc_required_group: null,
};

const groups: OrgGroup[] = [
  { id: "grp1", name: "Engineering", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "grp2", name: "Platform", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

function mockOrgAdminApis(overrides: {
  advanced?: OrgAdvancedSettings; sso?: OrgSsoConfig; org?: Organization;
  projectStatuses?: ProjectStatusDefinition[]; linkTypes?: LinkTypeDefinition[]; userAccess?: UserAccess;
  pats?: OrgPersonalAccessToken[]; users?: OrgUser[]; orgInvites?: OrgPendingInvite[]; groups?: OrgGroup[];
  modules?: OrgModule[];
} = {}) {
  const statuses = overrides.projectStatuses ?? [buildProjectStatus({ id: "st1", name: "Proposed", sort_order: 0 }), buildProjectStatus({ id: "st2", name: "Active", sort_order: 1 })];
  const types = overrides.linkTypes ?? [buildLinkType({ id: "lt1", forward_name: "Depends on", reverse_name: "Is a dependency of", sort_order: 0 })];
  const orgUsers = overrides.users ?? [orgUser];
  const orgPendingInvites = overrides.orgInvites ?? [];
  const orgGroups = overrides.groups ?? groups;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return overrides.org ?? org;
    if (path.includes("/project-statuses")) return statuses;
    if (path.includes("/link-types")) return types;
    // Phase A's org-only pending-invites list (follow-up UX batch).
    if (path.includes("/pending-invites")) return orgPendingInvites;
    if (path.includes("/groups")) return orgGroups;
    if (path.includes("/resources")) return [];
    if (path.includes("archived=false")) return [];
    if (path.includes("/report-templates")) return [];
    if (path.includes("/report-defaults")) throw new ApiError(403, "Forbidden");
    if (path.includes("/advanced-settings")) return overrides.advanced ?? advanced;
    if (path.includes("/pats")) return overrides.pats ?? [];
    // Module system Phase 1: fetched inside the same try/catch-403 block
    // as `/advanced-settings` above — must be mocked here or every story
    // that doesn't override it would otherwise throw on the "unmocked
    // path" fallback below and fail `reload()` as a whole.
    if (path.includes("/modules")) return overrides.modules ?? [];
    if (path.includes("/projects")) return [];
    if (path.includes("/sso-config")) return overrides.sso ?? ssoConfig;
    if (path.includes("/scim-token")) return { enabled: false, token_prefix: null };
    // Checked before the plain "/users" branch below — a user-access
    // summary request also contains that substring.
    if (path.includes("/access")) return overrides.userAccess ?? { org_groups: [], projects: [] };
    if (path.includes("/users")) return orgUsers;
    throw new Error(`unmocked path: ${path}`);
  });
  // Users and Groups both paginate/search (2026-08 UX audit "Directories
  // at scale") — `api.get` above still serves the *unpaginated* groups
  // fetch (`allGroups`, used to resolve nested-group names regardless of
  // the Groups section's own search/page state); this is the paginated
  // view each section actually renders. The `/users` branch also honours
  // an `org_role` query param (Phase A, follow-up UX batch) so a story can
  // actually exercise the new role filter narrowing results, the same way
  // the real backend does.
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

export const UsersSectionAndCreateUser: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    // Users is its own top-level resource-menu group (previously combined
    // with Groups under "People" — split 2026-08-25) and is open by
    // default there (the resource-menu selection does the "focus" job the
    // accordion collapse used to do), so selecting the group is enough —
    // no separate section-toggle click needed.
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByText("alex@example.com")).toBeInTheDocument());
    // Scoped to the roles dropdown trigger itself, not a page-wide
    // `getByText` — Phase A's new role `FilterField` also has an "Org
    // admin" `<option>` on the same page, which would otherwise make this
    // ambiguous.
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toHaveTextContent("Org admin");
    // Follow-up UX fix: this table's 6 columns (Email, Name, Role, Last
    // login, 2FA, Actions) crowded the old `.side-grid` sidebar, so its
    // `FilterPanel` now renders `layout="top"` (a full-width bar above the
    // table) instead — see docs/ux-style-guide.md's "Pattern: filter panel
    // placement — side vs. top".
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** Style guide "Pattern: modal dialog for entity create/rename" (revised
 * Principle 3): "New user" now opens a `Modal` instead of the permanently-
 * visible three-field inline form it used to be — the first real usage of
 * that pattern in this codebase (items 519/521 in the same roadmap batch
 * follow the shape this establishes). */
export const NewUserOpensModalAndCreates: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New user" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "New user" }));
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

/** Cancelling the "New user" modal creates nothing and leaves the Users
 * table untouched. */
export const NewUserModalCancel: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New user" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New user" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New user" });
    await userEvent.type(within(dialog).getByLabelText("Email"), "discarded@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** The "New user" modal's role select (added alongside the hierarchical-
 * projects org-role-management fix — `createUser()` used to hardcode
 * `role: "member"` even though the backend always accepted the field). */
export const NewUserModalRoleSelect: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New user" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "New user" }));
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

/** Per-row role grant/revoke (2026-08 org-role-management fix, reworked
 * 2026-08-27 from an always-visible checkbox stack to a `MultiSelectDropdown`
 * — see docs/decisions.md's "Org Users role picker" entry): the roles cell
 * used to be a read-only `ORG_ROLE_LABEL.join(", ")` with no way to change
 * anything — the only UI path to `assign_org_role`/the revoke endpoint.
 * Granting a role the user doesn't hold calls `POST .../roles`; revoking one
 * they do hold calls `DELETE .../roles/{role}`. The dropdown stays a
 * multi-select (not a single-value `<select>`) because `UserOrgRole` allows
 * a user to hold more than one org role at once — see that same decisions.md
 * entry for why collapsing it to one value would be a real behaviour change,
 * not just a reskin. */
const secondOrgUser: OrgUser = {
  user_id: "user-2", email: "jordan@example.com", display_name: "Jordan Lee", is_active: true,
  is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null,
  is_2fa_enabled: false,
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
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/user-1/roles`, { role: "project_creator" })
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

/** A user can never revoke their own org role via this control (mirrors the
 * backend's self-targeting block on the revoke endpoint) — `orgUser` here is
 * also the logged-in user (`user-1`, per `withStatefulAuth` in `meta`). */
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

/** Users table Actions column (PR6 of the members/groups directory rework
 * plan, docs/decisions.md) — the two previously-bare buttons (View access,
 * lock/unlock display name) consolidated into one `ActionMenu`, same
 * "kebab over adjacent buttons" pattern `ExportOrgBundleViaActionMenu`
 * already proved out for the Overview group. Exercised on Alex's own row
 * (the logged-in user, `user-1`): "Remove from {org}" is withheld there
 * (self-removal routes to the existing "Leave organisation" flow
 * instead, matching the backend's own self-targeting guard), so this also
 * pins that omission. */
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

/** "Remove from {org}" (new, access-mutating) — offered on a user other
 * than the caller, behind the same Tier-1 `ConfirmDialog` pattern
 * `PreferencesPage.tsx`'s own "Leave organisation" flow already uses. */
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

/** "Add to group" (pure UI reachability fix — no new endpoint) — the same
 * existing `addGroupMember` handler the group's own `SidePanel` member
 * picker already calls, now reachable from the user's own row too, via
 * `AddToGroupControl`'s own anchored `Popover`. */
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

/** "Invite user" (Phase A, follow-up UX batch) — a second, distinct way to
 * add a user alongside "New user": an email-only `Modal` (no password/name
 * fields, since the invitee sets those themselves at signup) calling the
 * new `POST /orgs/{id}/pending-invites`. */
export const InviteUserOpensModalAndCreates: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Users" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Invite user" })).toBeInTheDocument());
    // "New user" and "Invite user" are distinct, clearly-labelled actions
    // (2026-08-31 UX ask: tell the two flows apart) — both present at once.
    await expect(canvas.getByRole("button", { name: "New user" })).toBeInTheDocument();

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Invite user" }));
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Invite user" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Invite user" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Invite user" });
    await userEvent.type(within(dialog).getByLabelText("Email"), "discarded@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** A pending, not-yet-accepted org-only invite merges into the same Users
 * table as real users (`kind: "invited"` rows) — email/invited-by/sent-date
 * plus a status badge (through `PENDING_INVITE_STATUS_LABEL`, never a raw
 * "pending"/"expired" string) and a Resend button in place of the roles/
 * status/last-login/2FA columns a real user row shows. */
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
    // A real user row is unchanged — still shows its role dropdown, not an
    // em-dash or a Resend button.
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Resend invite to invitee@example.com" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/pending-invites/invite-1/resend`)
    );
    // Toasts render via a portal to `document.body`, not inside `canvas`.
    await expect(within(document.body).getByText("Invite resent to invitee@example.com.")).toBeInTheDocument();
  },
};

/** Unchecking "Show invited" (`FilterCheckbox`, defaulting on) hides
 * invited rows again without touching the real user rows. */
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

/** The new `FilterField` role filter (`org_role` — already supported
 * server-side, previously with no frontend control wired up to it) narrows
 * the table to only users holding the selected `OrgRole`, through
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

/** Migrated from three ad-hoc toggle `<button>`s to `FilterCheckbox`es
 * inside the shared `FilterPanel` (Phase A) — each now genuinely
 * independent (the old single-select state made "stale AND no 2FA"
 * inexpressible even though the backend params always were). */
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

/** Roadmap item 526's remaining "org report-template nested-accordion
 * create flow" case: "New template" now opens a `Modal` (a brand-new
 * `ReportTemplate` entity, per the revised Principle 3) instead of an
 * always-visible nested `CollapsibleSection` form. */
export const NewReportTemplateOpensModalAndCreates: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("link", { name: "Templates & reports" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New template" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "New template" }));
    const dialog = body.getByRole("dialog", { name: "New template" });
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(within(dialog).getByPlaceholderText("Name", { exact: true }), "Corporate Template");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/report-templates`,
        expect.objectContaining({ name: "Corporate Template" })
      )
    );
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Cancelling the "New template" modal creates nothing. */
export const NewReportTemplateModalCancel: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Templates & reports" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New template" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New template" }));
    const dialog = within(document.body).getByRole("dialog", { name: "New template" });
    await userEvent.type(within(dialog).getByPlaceholderText("Name", { exact: true }), "Discarded Template");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** Column-header sorting (2026-08 UX audit roadmap) — the Users table is
 * backend-paginated (`USERS_PAGE_SIZE`/`LoadMoreButton`), so a header click
 * refetches with `sort`/`order` query params rather than reordering just
 * the loaded page. */
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

/** "View access" (2026-08 UX audit, sixth pass: "No way to view a user's
 * access") opens a read-only `SidePanel` summarising every project the
 * user has a role on, their role(s) there, which project group granted
 * it, and which org groups they directly belong to — assembled server-
 * side (`GET /orgs/{id}/users/{id}/access`) rather than pieced together
 * from the frontend.
 *
 * **2026-08-30 revision** (reverses the 2026-08-24/25 "always show the
 * full, uncollapsed role set" decision — see `docs/decisions.md` and
 * `docs/ux-style-guide.md`'s "Pattern: role display" section): each
 * project row now shows `collapseProjectRoles()`'s collapsed summary by
 * default, with a "Show all N roles" toggle revealing the full,
 * uncollapsed set on demand — this story pins the collapsed default. See
 * `ViewUserAccessPanelExpandRoles` below for the expand-on-demand state. */
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

    // `["project_manager", "member"]` collapses to `["project_manager"]`
    // alone (project_manager is the sole top tier) — "Member" stays hidden
    // until the row's own expand toggle is used.
    await expect(within(panel).queryByText("Member")).not.toBeInTheDocument();
    await expect(within(panel).getByRole("button", { name: "Show all 2 roles" })).toBeInTheDocument();
  },
};

/** Expanding a project row's "Show all N roles" toggle reveals the full,
 * uncollapsed role set (the audit detail the panel's whole purpose is to
 * preserve — just not as the default view), and the toggle itself becomes
 * "Show fewer" to collapse it back. */
export const ViewUserAccessPanelExpandRoles: Story = {
  beforeEach: () => {
    mockOrgAdminApis({
      userAccess: {
        org_groups: [],
        projects: [
          {
            project_id: "proj1", project_name: "Atlas Platform",
            // Held via different group memberships — a genuinely real case
            // per `collapseProjectRoles()`'s own doc comment. Collapses to
            // `["project_manager"]` alone (the sole top tier), hiding the
            // other three — the toggle exists specifically to recover them.
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

/** Style guide "Pattern: action menu": rename now lives behind the
 * Overview group's kebab (`ActionMenu`, "Organisation actions") instead of an
 * always-visible inline input — selecting "Rename" from the menu opens a
 * `Modal` containing the rename field and its own Save/Cancel row. */
export const RenameOrganization: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockImplementation(async (path: string) =>
      path === `/api/v1/orgs/${ORG_ID}/name` ? { ...org, name: "Renamed Corp" } : org
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Organisation actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Organisation actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rename" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Rename" });
    await expect(within(dialog).getByLabelText("Rename")).toHaveValue("Acme Corp");
    await userEvent.clear(within(dialog).getByLabelText("Rename"));
    await userEvent.type(within(dialog).getByLabelText("Rename"), "Renamed Corp");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/name`, { name: "Renamed Corp" })
    );
    await expect(canvas.getByRole("heading", { name: "Renamed Corp" })).toBeInTheDocument();
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Renamed")).toBeInTheDocument();
    await expect(within(document.body).queryByRole("dialog", { name: "Rename" })).not.toBeInTheDocument();
  },
};

/** The other half of the same `ActionMenu`: "Export {org} bundle" calls
 * the existing export flow directly — no modal, it's a relocated button,
 * not a create/rename flow (roadmap item 519's own scope note). */
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
    // Branding now lives under the "Branding & defaults" resource-menu
    // group and is open by default there, so selecting the group is
    // enough — no separate "Branding section" toggle click needed.
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

/** Style guide "Pattern: platform default vs. override" (2026-08 UX audit):
 * a field with a saved custom value shows a "Custom" pill and an explicit
 * "Reset to platform default" action, instead of the field just quietly
 * accepting an emptied-out value with no indication of what that does. */
export const BrandingSectionOverridePillAndReset: Story = {
  beforeEach: () => mockOrgAdminApis({ org: { ...org, header_title: "Acme Requirements", email_footer_company_name: "Acme Ltd" } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
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

/** Roadmap "Logo & login-background reset": unlike the text-based branding
 * fields above, logo/login-background have no local "clear the input" edit
 * state to revert — the reset action calls the new `DELETE` endpoints
 * directly and immediately, the same way the upload itself commits
 * immediately (no separate Save step). Login-background now lives inside
 * the same Branding card as the logo (moved there from the old SSO
 * section, since it's a branding concern, not an SSO/OIDC one — see the
 * "Org Admin resource-menu restructure" roadmap item) — both resets are
 * exercised without leaving the Branding & defaults group. */
export const BrandingSectionLogoAndLoginBackgroundReset: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ org: { ...org, logo_file_id: "file-logo-1", login_background_file_id: "file-bg-1" } });
    spyOn(api, "delete").mockImplementation(async (path: string) =>
      path.endsWith("/logo") ? { ...org, logo_file_id: null } : { ...org, login_background_file_id: null }
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
    await waitFor(() => expect(canvas.getAllByText("Custom").length).toBeGreaterThanOrEqual(1));

    await userEvent.click(canvas.getAllByRole("button", { name: "Reset to platform default" })[0]);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/logo`));
    await expect(within(document.body).getByText("Logo reset to the platform default.")).toBeInTheDocument();

    await waitFor(() => expect(canvas.getByLabelText("Login page background image")).toBeInTheDocument());
    const backgroundReset = canvas.getAllByRole("button", { name: "Reset to platform default" }).find((btn) =>
      btn.closest("div")?.textContent?.includes("Login page background image")
    );
    await userEvent.click(backgroundReset!);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/login-background`));
    await expect(within(document.body).getByText("Background image reset to the platform default.")).toBeInTheDocument();
  },
};

export const BrandingSectionEmailFooterSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(org);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Branding & defaults" }));
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
    // "Integrations & security" later split into three top-level groups
    // (2026-08 UX audit roadmap item 523) — self-signup now lives in its
    // own "Security" group, open by default there.
    await userEvent.click(canvas.getByRole("link", { name: "Security" }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Allow self-signup" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Allow self-signup" }));
    await expect(
      canvas.getByText("Self-signup can't be enabled while this organisation is SSO-only — turn off \"SSO only\" in the SSO configuration below first, or turn off self-signup here.")
    ).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save security settings" })).toBeDisabled();
  },
};

/** The hierarchical-projects org toggle (decision 13): defaults to enabled
 * (project managers can create sub-projects without Project creator/Org
 * admin rights); an org admin can opt back into the stricter status-quo
 * behaviour by turning it off. */
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
    // Test email lives in the "SMTP & email" card under its own "Email"
    // top-level group now, split out of the old "Integrations & security"
    // combination (2026-08 UX audit roadmap item 523).
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

/** SMTP fields are saved via the same `OrgAdvancedSettings` PUT the
 * Security group's own save button also submits (2026-08 UX audit roadmap
 * item 523) — the Email group needs its own explicit save button now that
 * they're on separate pages. */
export const EmailSettingsSave: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    spyOn(api, "put").mockResolvedValue(advanced);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Email" }));
    await waitFor(() => expect(canvas.getByPlaceholderText("SMTP host")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("SMTP host"), "smtp.example.com");
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
    // SSO/OIDC and SCIM share the "OAuth/SSO" top-level group (both
    // identity-provisioning integrations) — see docs/decisions.md for the
    // SCIM-placement call.
    await userEvent.click(canvas.getByRole("link", { name: "OAuth/SSO" }));
    await waitFor(() => expect(canvas.getByLabelText("OIDC issuer URL")).toHaveValue("https://idp.example.com"));
  },
};

/** Org Groups (Phase B, follow-up UX batch, 2026-08-31): the accordion is
 * gone — a `DirectoryTable` row's Name cell opens a `SidePanel`, matching
 * Project Groups' own row + panel shape. */
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

/** SSO group→role mapping (2026-08 UX audit roadmap item 522) is a
 * property of the group being synced into — set alongside its (renamed)
 * SSO group name and saved together via one button in the group's
 * `SidePanel`. The mock's `ssoConfig` already has an issuer/client id set,
 * so the whole sync sub-section renders instead of the "set up SSO first"
 * hint; Engineering isn't synced yet (`idp_synced_group_name: null`), so
 * the toggle starts unchecked and the name/role fields start hidden. */
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
    // Principle 7 — every mutation ends with feedback (this save used to
    // have none at all besides the inline error state).
    await expect(within(document.body).getByText("Sync settings updated")).toBeInTheDocument();
  },
};

/** A group that's already synced (`idp_synced_group_name` non-null) opens
 * with the toggle checked by default and the name/role fields already
 * populated — the toggle's own declaration comment's "checked by default
 * only when already synced" contract. */
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

/** Unchecking the toggle clears both the sync name and granted role
 * immediately via the same `PATCH` the Save button uses — no separate
 * "Save" click needed to actually disable sync, since there's nothing
 * left to edit once the fields are hidden. */
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

/** Bug-fix regression pin (2026-08-31, Phase B): without SSO configured for
 * the org, the *entire* sync sub-section — name input, role select, AND
 * the enable/disable toggle and Save action — is absent, not just the
 * granted-role select. Before this fix, the name input and Save button
 * rendered unconditionally regardless of whether SSO was configured at
 * all; only the role select was actually gated. Only the muted hint
 * renders here. */
export const GroupsSectionSsoSyncSectionHiddenWithoutSso: Story = {
  beforeEach: () => mockOrgAdminApis({ sso: { slug: null, sso_enabled: false, sso_only: false, oidc_issuer_url: null, oidc_client_id: null, oidc_required_group: null } }),
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
    // A group's member list only renders once its own row is opened — the
    // whole point of moving this off the old always-expanded accordion
    // (style guide "Pattern: directories at scale").
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

    // Exactly one <option>Platform</option> exists (Engineering's own
    // nest-picker) — Platform's own row excludes itself, so its picker
    // offers "Engineering" instead.
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

/** Style guide "Pattern: modal dialog for entity create/rename": "+ New
 * group" opens a Modal with just a name field, instead of a
 * permanently-visible inline form pinned below the group list (or, as it
 * used to be before the revised Principle 3, a Popover). */
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

/** Revoking a single org-scoped PAT opens the shared `ConfirmDialog`
 * (sixth-pass audit — this used to fire via `window.confirm`), then shows
 * a success toast once revoked. */
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
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Active")).toBeInTheDocument());
    // Project statuses and Link types are both open by default under
    // "Projects & workflow" now, and the mocked link-types fixture also
    // has exactly one row by default — so the same "only one left" disabled
    // title appears twice on screen. Scope to the Active row itself.
    const row = canvas.getByDisplayValue("Active").closest<HTMLElement>(".stack")!;
    await expect(within(row).getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
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
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
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
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Depends on")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
  },
};

// --- "Manage users" Modal (Phase 5, docs/decisions.md; rebuilt in Phase D,
// follow-up UX batch, 2026-08-31) --------------------------------------
// Replaces the old inline expand-in-place (`expandedProjectId`/
// `expandedProjectGroups`/...) with a `Modal` wrapping the same
// `ProjectMembersTable` `ProjectAdminPage.tsx`'s own Members section uses —
// see `OrgAdminPage.tsx`'s own comment on `manageUsersProjectId`.
// `mockOrgAdminApis`'s generic `api.get` mock (above) resolves "/groups" to
// the *org*-scoped `OrgGroup[]` fixture before it can reach a project-scoped
// path (checked earlier in that chain, since both substrings collide) —
// every story below needs its own full `api.get` override, the same reason
// the pre-Phase-5 label-map regression test already did. Groups themselves
// are no longer shown in this modal at all (Phase D) — group management
// stays solely on the project's own Groups tab, reachable only from
// `ProjectAdminPage.tsx` directly.

function mockProjectsWorkflowWithOneProject(overrides: {
  effectiveMembers?: unknown[];
  pendingInvites?: unknown[];
} = {}) {
  const effectiveMembers = overrides.effectiveMembers ?? [];
  const pendingInvites = overrides.pendingInvites ?? [];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}`) return org;
    if (path === `/api/v1/orgs/${ORG_ID}/projects`) return [{ id: "proj-1", name: "Beta", is_archived: false }];
    if (path === "/api/v1/projects/proj-1/effective-members") return effectiveMembers;
    if (path === "/api/v1/projects/proj-1/pending-invites") return pendingInvites;
    if (path.includes("/project-statuses")) return [];
    if (path.includes("/link-types")) return [];
    // Phase A's org-only pending-invites list (follow-up UX batch) — no
    // invites in this scenario's fixture.
    if (path.includes("/pending-invites")) return [];
    if (path.includes("/groups")) return groups;
    if (path.includes("/resources")) return [];
    if (path.includes("archived=false")) return [];
    if (path.includes("/report-templates")) return [];
    if (path.includes("/report-defaults")) throw new ApiError(403, "Forbidden");
    if (path.includes("/advanced-settings")) return advanced;
    if (path.includes("/pats")) return [];
    if (path.includes("/modules")) return [];
    if (path.includes("/sso-config")) return ssoConfig;
    if (path.includes("/scim-token")) return { enabled: false, token_prefix: null };
    if (path.includes("/access")) return { org_groups: [], projects: [] };
    // `UserAutocomplete`'s debounced server-side search (organizationId
    // mode) — checked before the plain "/users" catch-all below, which
    // that path also matches.
    if (path.includes("/users/search")) return { members: [], external: null };
    if (path.includes("/users")) return [orgUser];
    throw new Error(`unmocked path: ${path}`);
  });
}

/** The Modal wraps the exact same `ProjectMembersTable` `ProjectAdminPage.
 * tsx`'s Members section uses — effective members with provenance render
 * identically, through `PROJECT_ROLE_LABEL` (2026-08 UX audit roadmap,
 * "Fix raw-enum filter/table text"), never the raw enum value. */
export const ManageUsersModalShowsEffectiveMembers: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    mockProjectsWorkflowWithOneProject({
      effectiveMembers: [
        {
          user_id: "u-alex", display_name: "Alex Morgan", email: "alex@example.com", effective_role: "member",
          sources: [{ kind: "direct_role", role: "member", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
        },
      ],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByText("Beta")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Manage users" }));

    const modal = within(document.body).getByRole("dialog", { name: "Manage users — Beta" });
    await expect(within(modal).getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(within(modal).getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
    // `ProjectMembersTable`'s own `FilterPanel` composition (`layout="top"`)
    // renders identically inside this modal — see
    // `ProjectMembersTable.stories.tsx`'s `MixedMembersAndInvited` for the
    // component covered in isolation, and docs/ux-style-guide.md's
    // "Pattern: filter panel placement — side vs. top".
    await expect(modal.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** Toggling a `direct_role`-kind option from inside the modal calls the same
 * `POST`/`DELETE .../roles` `ProjectAdminPage.tsx`'s own Members section
 * uses — the direct fix for "should show up in a similar way to the
 * project admin page," now with one real shared implementation. */
export const ManageUsersModalToggleDirectRole: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    mockProjectsWorkflowWithOneProject({
      effectiveMembers: [
        {
          user_id: "u-alex", display_name: "Alex Morgan", email: "alex@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct_role", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
        },
      ],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByText("Beta")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Manage users" }));

    const modal = within(document.body).getByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(within(modal).getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(group).getByRole("checkbox", { name: "Grant Member to Alex Morgan" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/projects/proj-1/roles", { user_id: "u-alex", role: "member" })
    );
  },
};

/** The modal's own "add a direct member" control — same `UserAutocomplete`
 * + role `<select>` composition `ProjectAdminPage.tsx`'s Members section
 * uses, scoped to whichever project's modal is open. Style guide "Pattern:
 * modal dialog for entity create/rename" (Principle 3) — as of PR3 of the
 * members/groups directory rework, this sub-form is no longer permanently
 * visible inside the outer "Manage users" modal; "Add member" opens it in
 * a second, nested `Modal` (`useDialogA11y`'s docstring covers why nesting
 * is already handled safely: only the innermost open dialog ever actually
 * contains focus, so Escape/Tab-trap don't cross between the two). */
export const ManageUsersModalAddControlRenders: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    mockProjectsWorkflowWithOneProject();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByText("Beta")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Manage users" }));

    const body = within(document.body);
    const outerModal = body.getByRole("dialog", { name: "Manage users — Beta" });
    await expect(within(outerModal).getByRole("button", { name: "Add member" })).toBeInTheDocument();
    await expect(body.queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();

    await userEvent.click(within(outerModal).getByRole("button", { name: "Add member" }));
    const addMemberModal = body.getByRole("dialog", { name: "Add member" });
    // Both dialogs stay mounted at once — the outer container is still the
    // right home for "manage users for this project" as a whole.
    await expect(body.getByRole("dialog", { name: "Manage users — Beta" })).toBeInTheDocument();
    await expect(within(addMemberModal).getByRole("combobox", { name: "Role to grant" })).toBeInTheDocument();
    await expect(within(addMemberModal).getByPlaceholderText("Type a name to add, or an email to invite…")).toBeInTheDocument();
  },
};

/** Nested-modal-open state on its own — confirms Cancel closes only the
 * inner "Add member" modal (Escape's own containment guard in
 * `dialogA11y.ts` is what makes this safe; this story exercises the
 * mouse-driven Cancel button path instead of Escape). */
export const ManageUsersModalAddMemberNestedModalOpen: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    mockProjectsWorkflowWithOneProject();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByText("Beta")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Manage users" }));

    const body = within(document.body);
    const outerModal = body.getByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(within(outerModal).getByRole("button", { name: "Add member" }));
    const addMemberModal = body.getByRole("dialog", { name: "Add member" });

    await userEvent.click(within(addMemberModal).getByRole("button", { name: "Cancel" }));
    await expect(body.queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();
    // The outer "manage users" modal stays open — only the sub-form closed.
    await expect(body.getByRole("dialog", { name: "Manage users — Beta" })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  },
};

/** PR5 of the members/groups directory rework plan — the same combined
 * user-or-group autocomplete `ProjectAdminPage.tsx`'s own Members section
 * uses (`MembersTabAddMemberAutocompleteMatchesGroup`), reachable from
 * here too since this modal shares the identical `UserAutocomplete` call
 * site, now passed `groups={allGroups}` (every group in the org, the same
 * unpaginated fixture the Groups section itself resolves nested-group
 * names against). Picking a group grants it the role directly on
 * `manageUsersProjectId` via `POST .../group-roles`. */
export const ManageUsersModalAddMemberAutocompleteMatchesGroup: Story = {
  beforeEach: () => {
    mockOrgAdminApis();
    mockProjectsWorkflowWithOneProject();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Projects & workflow" }));
    await waitFor(() => expect(canvas.getByText("Beta")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Manage users" }));

    const body = within(document.body);
    const outerModal = body.getByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(within(outerModal).getByRole("button", { name: "Add member" }));
    const addMemberModal = body.getByRole("dialog", { name: "Add member" });

    await userEvent.type(within(addMemberModal).getByPlaceholderText("Type a name to add, or an email to invite…"), "Eng");
    const groupOption = await within(addMemberModal).findByRole("option", { name: /Engineering/ });
    await expect(groupOption).toHaveTextContent("Org group");

    await userEvent.click(groupOption);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/proj-1/group-roles",
        { org_group_id: "grp1", role: "member" },
      )
    );
    await expect(body.queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();
  },
};

/** Module system Phase 1 (compliance-module-plan.md): the new "Modules"
 * top-level group. A deployment with no modules registered yet (the true
 * state today — no first-party module exists until Phase 5) shows the
 * empty state rather than an empty table. */
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
  version: "0.1.0", implemented: true, entitled: true, enabled: true, default_enabled: true,
};

/** An entitled, implemented module renders with an active toggle — toggling
 * it off calls `PUT .../modules/{key}` and patches local state from the
 * response, with a toast confirming the change (feedback-on-every-mutation). */
export const ModulesSectionToggleEntitledModule: Story = {
  beforeEach: () => {
    mockOrgAdminApis({ modules: [entitledEnabledModule] });
    spyOn(api, "put").mockResolvedValue({ ...entitledEnabledModule, enabled: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    const toggle = canvas.getByRole("switch", { name: "Enable Fake Module" });
    await expect(toggle).toBeChecked();
    await expect(toggle).toBeEnabled();

    await userEvent.click(toggle);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/fake_module`, { enabled: false })
    );
    await expect(within(document.body).getByText("Fake Module disabled")).toBeInTheDocument();
  },
};

/** Non-entitled modules are shown greyed out with an explanatory note
 * rather than hidden entirely (plan requirement — visibility helps future
 * upsell), and the toggle itself stays disabled so an org admin can't
 * self-enable a module their organisation isn't entitled to. */
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
    await expect(canvas.getByRole("switch", { name: "Enable Fake Module" })).toBeDisabled();
  },
};

/** A registered-but-not-yet-implemented module (`implemented: false`, the
 * state every module will be in before Phase 5) also renders with a
 * disabled toggle and its own explanatory note, distinct from the
 * non-entitled case above. */
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
    await expect(canvas.getByRole("switch", { name: "Enable Fake Module" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "light" } };
export const DarkTheme: Story = { ...UsersSectionAndCreateUser, globals: { theme: "dark" } };
