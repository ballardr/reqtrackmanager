import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { EffectiveMember, ModuleRoleDefinition, OrgGroupProjectRoleSummary, PendingInvite } from "../api/types";
import { ProjectMembersTable } from "./ProjectMembersTable";

const MEMBERS: EffectiveMember[] = [
  {
    user_id: "u-alex",
    display_name: "Alex Morgan",
    email: "alex@example.com",
    effective_role: "project_manager",
    sources: [
      {
        kind: "direct_role", role: "project_manager", via_project_id: null, via_project_name: null,
        via_mode: null, via_group_id: null, via_group_name: null,
      },
    ],
    module_roles: [],
  },
  {
    user_id: "u-priya",
    display_name: "Priya Shah",
    email: "priya@example.com",
    effective_role: "stakeholder",
    // Named-group provenance (PR1: `via_group_id`/`via_group_name`) — the
    // Source column must say *which* group granted the role, not just "Via
    // group". See the `NamedGroupSourceLine` story below.
    sources: [
      {
        kind: "direct_group", role: "stakeholder", via_project_id: null, via_project_name: null,
        via_mode: null, via_group_id: "g-reviewers", via_group_name: "Reviewers",
      },
    ],
    module_roles: [],
  },
  {
    user_id: "u-jordan",
    display_name: "Jordan Lee",
    email: "jordan@example.com",
    effective_role: "member",
    sources: [
      {
        kind: "direct_role", role: "member", via_project_id: null, via_project_name: null,
        via_mode: null, via_group_id: null, via_group_name: null,
      },
      {
        kind: "forward_inherited", role: "stakeholder", via_project_id: "p-parent", via_project_name: "Parent Project",
        via_mode: "mirror_all", via_group_id: null, via_group_name: null,
      },
    ],
    module_roles: [],
  },
  {
    user_id: "u-morgan",
    display_name: "Morgan Casey",
    email: "morgan@example.com",
    effective_role: "member",
    // `direct_org_group_role` (PR4/PR5) — an org group holding this role
    // *directly*, distinct from `direct_group`/`direct_org_group`'s nested
    // mechanisms above. See `NamedOrgGroupRoleSourceLine` below.
    sources: [
      {
        kind: "direct_org_group_role", role: "member", via_project_id: null, via_project_name: null,
        via_mode: null, via_group_id: "og-engineering", via_group_name: "Engineering",
      },
    ],
    module_roles: [],
  },
];

const INVITES: PendingInvite[] = [
  {
    id: "inv-1",
    email: "invitee@example.com",
    role: "member",
    status: "pending",
    created_at: "2026-08-01T00:00:00Z",
    expires_at: "2026-09-01T00:00:00Z",
  },
];

const meta: Meta<typeof ProjectMembersTable> = {
  title: "Components/ProjectMembersTable",
  component: ProjectMembersTable,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
  args: {
    members: MEMBERS,
    invites: INVITES,
    onToggleRole: fn(),
    onResendInvite: fn(),
    ariaLabel: "Project members",
  },
};
export default meta;

type Story = StoryObj<typeof ProjectMembersTable>;

/** Real member rows and an invited row render in one table, distinguished
 * by the Role cell's content: a member gets a `MultiSelectDropdown`, an
 * invited row gets a status badge + Resend button. */
export const MixedMembersAndInvited: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
    await expect(canvas.getByText("invitee@example.com")).toBeInTheDocument();
    await expect(canvas.getByText("Pending")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Resend invite to invitee@example.com" })).toBeInTheDocument();
    // Follow-up UX fix: this table's Role (`MultiSelectDropdown`) and
    // Source (multi-line provenance text) columns crowded the old
    // `.side-grid` sidebar on both call sites, so its own `FilterPanel`
    // now renders `layout="top"` (a full-width bar above the table) —
    // see docs/ux-style-guide.md's "Pattern: filter panel placement —
    // side vs. top". Both call sites (`ProjectAdminPage.tsx`'s Members
    // section, `OrgAdminPage.tsx`'s "Manage users" modal) inherit this
    // automatically since it's composed inside this shared component.
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** No members and no invites at all — a distinct empty-state message from
 * "search/filter matched nothing" (below). */
export const EmptyState: Story = {
  args: { members: [], invites: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No members yet.")).toBeInTheDocument();
  },
};

/** More rows than one page — `LoadMoreButton` appears, and clicking it
 * reveals the rest without a network request (the whole array is already
 * in memory; see the component's own docstring). */
export const AtScalePaginated: Story = {
  args: {
    invites: [],
    members: Array.from({ length: 45 }, (_, i): EffectiveMember => ({
      user_id: `u-${i}`,
      display_name: `User ${String(i).padStart(2, "0")}`,
      email: `user${i}@example.com`,
      effective_role: "member",
      sources: [
        {
          kind: "direct_role", role: "member", via_project_id: null, via_project_name: null,
          via_mode: null, via_group_id: null, via_group_name: null,
        },
      ],
      module_roles: [],
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("row")).toHaveLength(21); // header + 20
    await expect(canvas.getByRole("button", { name: /Load more/ })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await expect(canvas.getAllByRole("row")).toHaveLength(41); // header + 40
  },
};

/** A `direct_group` source names the actual granting `ProjectGroup`
 * (`via_group_name`) instead of the generic "Via group" — PR1 of the
 * members/groups directory rework. Priya's fixture source carries
 * `via_group_id`/`via_group_name` for the "Reviewers" group. That detail
 * now lives inside the Source column's click-to-open popover (platform
 * review 2026-09 follow-up) rather than always-visible in the cell — the
 * cell itself just shows the "Group" summary word (see
 * `SourceSummaryDirectAndGroup` below for the mixed-sources case). */
export const NamedGroupSourceLine: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByRole("button", { name: "Priya Shah's roles" }).closest("tr")!;
    await expect(within(row).getByText("Group")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Group" }));
    const detail = within(document.body).getByRole("dialog", { name: "Priya Shah's access sources" });
    await expect(within(detail).getByText(/Via group 'Reviewers'/)).toBeInTheDocument();
  },
};

/** Alex Morgan's only source is `direct_role` — the Source cell reads
 * plain "Direct", with no popover-opening button at all (nothing to
 * disclose beyond the one word). Jordan Lee holds both a `direct_role`
 * (member) and a `forward_inherited` (stakeholder) source at once — the
 * mixed case reads "Direct and group" and its popover lists both lines,
 * confirming the summary/detail split doesn't lose either source when a
 * member's access comes from more than one place. */
export const SourceSummaryDirectAndGroup: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const alexRow = canvas.getByRole("button", { name: "Alex Morgan's roles" }).closest("tr")!;
    await expect(within(alexRow).getByText("Direct")).toBeInTheDocument();
    await expect(within(alexRow).queryByRole("button", { name: "Direct" })).not.toBeInTheDocument();

    const jordanRow = canvas.getByRole("button", { name: "Jordan Lee's roles" }).closest("tr")!;
    await expect(within(jordanRow).getByText("Direct and group")).toBeInTheDocument();
    await userEvent.click(within(jordanRow).getByRole("button", { name: "Direct and group" }));
    const detail = within(document.body).getByRole("dialog", { name: "Jordan Lee's access sources" });
    await expect(within(detail).getByText(/^Direct \(Member\)$/)).toBeInTheDocument();
    await expect(within(detail).getByText(/Inherited from 'Parent Project'/)).toBeInTheDocument();
  },
};

/** `direct_org_group_role` (PR4/PR5 of the members/groups directory rework
 * plan) — an org group holding a role *directly* on this project, granted
 * from the Members section's own "Add member" autocomplete (PR5). Distinct
 * wording ("(direct)") from `direct_org_group`'s "Via nested org group"
 * (a different mechanism — nesting inside a `ProjectGroup`), and — like
 * every non-`direct_role` kind — checked-but-disabled with an explanatory
 * title, never a silently-broken toggle (see
 * `DisabledRoleWithExplanatoryTitle` below for that shared behaviour). */
export const NamedOrgGroupRoleSourceLine: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByRole("button", { name: "Morgan Casey's roles" }).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Group" }));
    const detail = within(document.body).getByRole("dialog", { name: "Morgan Casey's access sources" });
    await expect(within(detail).getByText(/Via group 'Engineering' \(direct\)/)).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Morgan Casey's roles" }));
    const group = within(document.body).getByRole("group", { name: "Morgan Casey's roles" });
    // Never a freely toggle-off-able direct grant from this row (the
    // backing `OrgGroupProjectRole` belongs to the *group*, not this one
    // user — see `isDirectRoleKind`'s own doc comment for why) — checked
    // but disabled, same as every other non-`direct_role` kind, and its
    // own label now carries the same "(by group)" suffix inline (platform
    // review 2026-09 follow-up) rather than relying on the `title` alone.
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Member from Morgan Casey" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("isn't a direct grant"));
    await expect(within(group).getByText("Member (by group)")).toBeInTheDocument();
  },
};

/** A role sourced from a group (not a genuine `direct_role` grant) shows
 * checked but disabled, with a title explaining it must be changed at its
 * actual source — the core Phase D fix: `DELETE /roles` would silently
 * no-op against this option, so it must never look freely toggle-off-able.
 * Its own visible label also carries the "(by group)" suffix inline
 * (platform review 2026-09 follow-up) so the reason is visible without
 * hovering for the `title`. */
export const DisabledRoleWithExplanatoryTitle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Priya Shah's roles" }));
    const group = within(document.body).getByRole("group", { name: "Priya Shah's roles" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Priya Shah" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("isn't a direct grant"));
    await expect(within(group).getByText("Stakeholder (by group)")).toBeInTheDocument();
  },
};

/** This table's only `direct_role`-sourced `project_manager` has its role
 * control disabled (a fast client-side C-U-08 hint — see the component's
 * own docstring for why the backend guard remains authoritative
 * regardless), its visible label carrying the distinct "(only manager)"
 * suffix (platform review 2026-09 follow-up) rather than "(by group)" —
 * this option *is* a genuine direct grant, just not currently revocable. */
export const LastManagerRoleControlDisabled: Story = {
  args: {
    invites: [],
    members: [MEMBERS[0]],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Project manager from Alex Morgan" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("only manager source"));
    await expect(within(group).getByText("Project manager (only manager)")).toBeInTheDocument();
  },
};

/** Typing into `FilterPanel`'s own search box narrows both member and
 * invited rows by name/email at once, with its own distinct "no results"
 * message from the true-empty state above. */
export const SearchNarrowed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Search by name or email" }), "priya");
    await expect(canvas.getByRole("cell", { name: "Priya Shah" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("invitee@example.com")).not.toBeInTheDocument();
  },
};

/** The role `FilterField` narrows to only members holding the selected role
 * via *any* source — Jordan Lee's forward-inherited stakeholder source
 * counts just like Priya's group-derived one, even though neither is a
 * `direct_role` grant. */
export const RoleFiltered: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Role"), "stakeholder");
    await expect(canvas.getByRole("cell", { name: "Priya Shah" })).toBeInTheDocument();
    await expect(canvas.getByRole("cell", { name: "Jordan Lee" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

/** Unchecking "Show invited" hides pending-invite rows entirely, leaving
 * only real members. */
export const ShowInvitedToggledOff: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("invitee@example.com")).toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Show invited"));
    await expect(canvas.queryByText("invitee@example.com")).not.toBeInTheDocument();
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
  },
};

/** The caller-supplied `addControl` slot renders above the table — this
 * story stands in a plain button since the real controls
 * (`UserAutocomplete` + a role `<select>`) are exercised by the pages that
 * actually compose them. */
export const WithAddControl: Story = {
  args: {
    addControl: <button className="btn btn-primary">Add member…</button>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Add member…" })).toBeInTheDocument();
  },
};

/** Per-row Actions column (PR6 of the members/groups directory rework
 * plan) — hidden entirely when the caller doesn't supply either handler
 * (every story above), so this and the following two stories opt in via
 * `onRemoveAllAccess`/`onConvertToDirect` args. Alex's only source is a
 * genuine `direct_role` grant, so "Remove all access" is offered but
 * "Convert inherited access to direct roles" is not (nothing inherited to
 * convert) — confirming the `ConfirmDialog` calls `onRemoveAllAccess`. */
export const ActionsMenuOffersRemoveAllAccess: Story = {
  args: {
    invites: [],
    members: [MEMBERS[0]],
    onRemoveAllAccess: fn(),
    onConvertToDirect: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Alex Morgan's actions" });
    await expect(within(menu).getByRole("menuitem", { name: /Remove all access/ })).toBeInTheDocument();
    await expect(within(menu).queryByRole("menuitem", { name: /Convert inherited access/ })).not.toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: /Remove all access/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "Remove all access for Alex Morgan?" });
    await expect(args.onRemoveAllAccess).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove access" }));
    await expect(args.onRemoveAllAccess).toHaveBeenCalledWith("u-alex");
  },
};

/** Jordan holds a `direct_role` (member) alongside a `forward_inherited`
 * (stakeholder) source — mixed, so "Remove all access" is withheld (it
 * would silently leave the inherited access behind while claiming to
 * remove "all" of it), but "Convert inherited access to direct roles" is
 * offered and, unlike the destructive action above, calls straight
 * through with no confirm step. */
export const ActionsMenuOffersConvertToDirect: Story = {
  args: {
    invites: [],
    members: [MEMBERS[2]],
    onRemoveAllAccess: fn(),
    onConvertToDirect: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Jordan Lee's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Jordan Lee's actions" });
    await expect(within(menu).getByRole("menuitem", { name: /Convert inherited access/ })).toBeInTheDocument();
    await expect(within(menu).queryByRole("menuitem", { name: /Remove all access/ })).not.toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: /Convert inherited access/ }));
    await expect(args.onConvertToDirect).toHaveBeenCalledWith("u-jordan");
  },
};

/** Priya's only source is `direct_group` — neither a genuine direct grant
 * (so not safely "remove all"-able) nor an inherited one (nothing to
 * convert) — so the Actions column renders no trigger at all for her row,
 * rather than an empty, useless menu. */
export const ActionsMenuHiddenWhenNoEligibleAction: Story = {
  args: {
    invites: [],
    members: [MEMBERS[1]],
    onRemoveAllAccess: fn(),
    onConvertToDirect: fn(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Priya Shah's actions" })).not.toBeInTheDocument();
  },
};

/** Module system Phase 2: `availableModuleRoles` merges module-contributed
 * role options into the same Role `MultiSelectDropdown` as the four core
 * `ProjectRole` options — Alex holds one (checked) and not the other
 * (unchecked), and neither is ever disabled the way a group/inherited-
 * sourced core-role option would be, since module roles are direct-grant-
 * only with no inheritance concept (see the component's own docstring).
 * Every other story on this page implicitly covers the opposite,
 * real-world-default case — `availableModuleRoles` simply isn't passed, so
 * it defaults to `[]` and the dropdown shows only the four core roles,
 * unchanged from before this phase (no module has any roles registered
 * until Phase 5). */
const MODULE_ROLES: ModuleRoleDefinition[] = [
  { module_key: "compliance", role_key: "compliance_officer", name: "Compliance Officer", description: "Manages this project's compliance assessments." },
  { module_key: "compliance", role_key: "evidence_reviewer", name: "Evidence Reviewer", description: "Reviews submitted compliance evidence." },
];

export const ModuleRolesAvailable: Story = {
  args: {
    invites: [],
    members: [{ ...MEMBERS[0], module_roles: [{ module_key: "compliance", role_key: "compliance_officer" }] }],
    availableModuleRoles: MODULE_ROLES,
    onToggleModuleRole: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await expect(within(group).getByText("Compliance Officer")).toBeInTheDocument();
    const checked = within(group).getByRole("checkbox", { name: /Revoke Compliance Officer/ });
    await expect(checked).not.toBeDisabled();
    const unchecked = within(group).getByRole("checkbox", { name: /Grant Evidence Reviewer/ });
    await expect(unchecked).not.toBeDisabled();
    await userEvent.click(unchecked);
    await expect(args.onToggleModuleRole).toHaveBeenCalledWith("u-alex", "compliance", "evidence_reviewer", true);
  },
};

// --- Group rows (Phase 6, docs/platform-review-2026-09-plan.md) -----------
//
// An org group holding a direct `OrgGroupProjectRole` grant on this project
// now gets its own `kind: "group"` row (previously visible only through a
// member's own `direct_org_group_role` Source line — see
// `NamedOrgGroupRoleSourceLine` above, which pins that provenance line's
// own continued existence unchanged).

const GROUP_ROLES: OrgGroupProjectRoleSummary[] = [
  { org_group_id: "og-engineering", org_group_name: "Engineering", roles: ["stakeholder", "member"] },
];

/** The group row's Name cell carries a "Group" badge (this table has no
 * dedicated Type column — see the component's own docstring for why a
 * badge in an existing cell was chosen instead), its Email cell is blank
 * (a group has none), and its Source column just states "Direct" plainly
 * — no per-role breakdown or popover, unlike a member row (platform review
 * 2026-09 follow-up), since there's nothing upstream of the group's own
 * direct grant to disclose and the Role column already names which roles
 * it holds. */
export const GroupRow: Story = {
  args: { groupRoles: GROUP_ROLES },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Scoped via the group's own (unique) role-dropdown trigger, not a
    // `getByRole("row", { name: /Engineering/ })` lookup — Morgan Casey's
    // fixture row also mentions "Engineering" in its own Source popover
    // (`NamedOrgGroupRoleSourceLine`'s `direct_org_group_role` provenance),
    // which would otherwise match too and make the row lookup ambiguous.
    const row = canvas.getByRole("button", { name: "Engineering's roles" }).closest("tr")!;
    await expect(within(row).getByText("Group")).toBeInTheDocument();
    await expect(within(row).getByText("Direct")).toBeInTheDocument();
  },
};

/** A group row's Role options are always freely togglable in both
 * directions — no `purelyDirect`/"last manager" disabling the way a
 * member row's options get, since the row's very existence already means
 * every option reflects this group's own direct grant (see the component's
 * own docstring for why a client-side "last manager" hint would be
 * actively misleading here). */
export const GroupRowRoleToggle: Story = {
  args: { groupRoles: GROUP_ROLES, onToggleGroupRole: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Engineering's roles" }));
    const group = within(document.body).getByRole("group", { name: "Engineering's roles" });

    const checked = within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Engineering" });
    await expect(checked).not.toBeDisabled();
    await userEvent.click(checked);
    await expect(args.onToggleGroupRole).toHaveBeenCalledWith("og-engineering", "stakeholder", false);

    const unchecked = within(group).getByRole("checkbox", { name: "Grant Project manager to Engineering" });
    await expect(unchecked).not.toBeDisabled();
    await userEvent.click(unchecked);
    await expect(args.onToggleGroupRole).toHaveBeenCalledWith("og-engineering", "project_manager", true);
  },
};

/** "Remove group" (Actions column) revokes every role the group holds at
 * once, behind the same Tier-1 `ConfirmDialog` "Remove all access" already
 * uses for a member row — `onRemoveGroup` is only ever called after
 * confirming. */
export const GroupRowRemoveAction: Story = {
  args: { groupRoles: GROUP_ROLES, onRemoveGroup: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Engineering's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Engineering's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Remove group" }));

    const dialog = within(document.body).getByRole("dialog", { name: "Remove Engineering from this project?" });
    await expect(args.onRemoveGroup).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove group" }));
    await expect(args.onRemoveGroup).toHaveBeenCalledWith("og-engineering");
  },
};

/** A group row renders alongside member/invited rows, not instead of them
 * — and the search box matches a group's own name the same way it already
 * matches a member's name/email. */
export const GroupRowAlongsideMembersAndSearch: Story = {
  args: { groupRoles: GROUP_ROLES },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.getByText("invitee@example.com")).toBeInTheDocument();
    // Not a `getByRole("row", { name: /Engineering/ })` lookup here — before
    // filtering, Morgan Casey's fixture row also mentions "Engineering" in
    // its own Source line, making that query ambiguous (see `GroupRow`'s own
    // comment above for the same reason).
    await expect(canvas.getByRole("button", { name: "Engineering's roles" })).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Search by name or email"), "Engin");
    // Unambiguous now — search only matches a group's own name (not a
    // member's unrelated Source-line mention of it), so Morgan Casey's row
    // is filtered out and the group row is the only "Engineering" match left.
    await expect(canvas.getByRole("row", { name: /Engineering/ })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
