import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { EffectiveMember, ModuleRoleDefinition, OrgGroupProjectRoleSummary, PendingInvite } from "../api/types";
import { expectTooltip, reasonTarget } from "../testing/tooltips";
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
    // Named-group provenance (`via_group_id`/`via_group_name`) — the
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
    // `direct_org_group_role` — an org group holding this role
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
    // The Role (`MultiSelectDropdown`) and Source (multi-line provenance text) columns are too wide for a side
    // panel, so the table's `FilterPanel` renders `layout="top"` (docs/ux-style-guide.md, "Pattern: filter panel
    // placement — side vs. top"); both call sites inherit it from this shared component.
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** A service user carries the Service badge beside its name, so an integration is never mistaken for a person. */
export const ServiceUserMember: Story = {
  args: {
    members: [
      ...MEMBERS,
      {
        user_id: "u-agent", display_name: "Build agent", email: "svc-1@service.invalid", effective_role: "member",
        is_service_account: true,
        sources: [
          {
            kind: "direct_role", role: "member", via_project_id: null, via_project_name: null,
            via_mode: null, via_group_id: null, via_group_name: null,
          },
        ],
        module_roles: [],
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Service")).toBeInTheDocument();
    await expect(canvas.getAllByText("Service")).toHaveLength(1);
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

/** A `direct_group` source names the granting `ProjectGroup` (`via_group_name`) instead of the generic "Via group".
 * Priya's fixture source carries `via_group_id`/`via_group_name` for the "Reviewers" group. That detail is inside the
 * Source column's click-to-open popover; the cell shows the "Group" summary word (`SourceSummaryDirectAndGroup`
 * covers the mixed case). */
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

/** Alex Morgan's only source is `direct_role`: the Source cell reads "Direct" with no popover button. Jordan Lee
 * holds a `direct_role` (member) and a `forward_inherited` (stakeholder) source: the cell reads "Direct and group"
 * and its popover lists both lines, so the summary and detail split loses neither source. */
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

/** `direct_org_group_role`: an org group holding a role directly on this project, granted from the Members section's
 * "Add member" autocomplete. Its wording "(direct)" differs from `direct_org_group`'s "Via nested org group" (nesting
 * inside a `ProjectGroup`), and like every non-`direct_role` kind it is checked but disabled with an explanatory
 * title (`DisabledRoleWithExplanatoryTitle`). */
export const NamedOrgGroupRoleSourceLine: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = canvas.getByRole("button", { name: "Morgan Casey's roles" }).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Group" }));
    const detail = within(document.body).getByRole("dialog", { name: "Morgan Casey's access sources" });
    await expect(within(detail).getByText(/Via group 'Engineering' \(direct\)/)).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Morgan Casey's roles" }));
    const group = within(document.body).getByRole("group", { name: "Morgan Casey's roles" });
    // The backing `OrgGroupProjectRole` belongs to the group, not this user (`isDirectRoleKind`), so the option is
    // checked but disabled, with the "(by group)" suffix inline as for every other non-`direct_role` kind.
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Member from Morgan Casey" });
    await expect(checkbox).toBeDisabled();
    await expectTooltip(reasonTarget(checkbox), /is not a direct grant/);
    await expect(within(group).getByText("Member (by group)")).toBeInTheDocument();
  },
};

/** A role sourced from a group (not a `direct_role` grant) shows checked but disabled, with a title and a visible
 * "(by group)" label suffix saying it must be changed at its source: `DELETE /roles` would not affect it, so it must
 * not look togglable. */
export const DisabledRoleWithExplanatoryTitle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Priya Shah's roles" }));
    const group = within(document.body).getByRole("group", { name: "Priya Shah's roles" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Priya Shah" });
    await expect(checkbox).toBeDisabled();
    await expectTooltip(reasonTarget(checkbox), /is not a direct grant/);
    await expect(within(group).getByText("Stakeholder (by group)")).toBeInTheDocument();
  },
};

/** This table's only `direct_role`-sourced `project_manager` has its role control disabled (a client-side
 * last-manager hint; the backend guard is authoritative), with the distinct "(only manager)" suffix: the option is
 * a direct grant, just not currently revocable. */
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
    await expectTooltip(reasonTarget(checkbox), /only manager source/);
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

/** The role `FilterField` narrows to members holding the selected role through any source: Jordan Lee's
 * forward-inherited stakeholder source counts like Priya's group-derived one. */
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

/** The caller-supplied `addControl` slot renders above the table; the story uses a plain button because the real
 * controls (`UserAutocomplete` and a role `<select>`) are exercised by the pages that compose them. */
export const WithAddControl: Story = {
  args: {
    addControl: <button className="btn btn-primary">Add member…</button>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Add member…" })).toBeInTheDocument();
  },
};

/** The per-row Actions column is hidden unless the caller supplies a handler, so this and the next two stories opt in
 * through `onRemoveAllAccess`/`onConvertToDirect`. Alex's only source is a `direct_role` grant, so "Remove all
 * access" is offered but "Convert inherited access to direct roles" is not; confirming the `ConfirmDialog` calls
 * `onRemoveAllAccess`. */
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

/** Jordan holds a `direct_role` (member) and a `forward_inherited` (stakeholder) source, so "Remove all access" is
 * withheld (it would leave the inherited access in place) while "Convert inherited access to direct roles" is
 * offered and, being additive, calls straight through with no confirm step. */
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

/** Priya's only source is `direct_group`: not a direct grant (so not "remove all"-able) and not inherited (nothing
 * to convert), so her row renders no Actions trigger rather than an empty menu. */
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

/** `availableModuleRoles` merges module-contributed role options into the Role `MultiSelectDropdown` beside the
 * four core `ProjectRole` options. Alex holds one (checked) and not the other (unchecked); neither is ever disabled,
 * because module roles are direct-grant-only. Without `availableModuleRoles` (every other story) it defaults to `[]`
 * and only the four core roles show. */
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

// --- Group rows -----------
//
// An org group holding a direct `OrgGroupProjectRole` grant on this project has its own `kind: "group"` row;
// `NamedOrgGroupRoleSourceLine` above pins the provenance line the same grant gives a member.

const GROUP_ROLES: OrgGroupProjectRoleSummary[] = [
  { org_group_id: "og-engineering", org_group_name: "Engineering", roles: ["stakeholder", "member"] },
];

/** The group row's Name cell carries a "Group" badge (the table has no Type column), its Email cell is blank and its
 * Source cell states "Direct" with no per-role breakdown or popover, because nothing upstream of the group's direct
 * grant exists to disclose and the Role column names the roles. */
export const GroupRow: Story = {
  args: { groupRoles: GROUP_ROLES },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Scoped through the group's own role-dropdown trigger: a `getByRole("row", { name: /Engineering/ })` lookup
    // is ambiguous because Morgan Casey's row also mentions "Engineering" in its Source popover.
    const row = canvas.getByRole("button", { name: "Engineering's roles" }).closest("tr")!;
    await expect(within(row).getByText("Group")).toBeInTheDocument();
    await expect(within(row).getByText("Direct")).toBeInTheDocument();
  },
};

/** A group row's Role options are always togglable both ways, with no `purelyDirect`/last-manager disabling: the
 * row's existence means every option is the group's own direct grant, so a client-side last-manager hint would
 * mislead. */
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

/** "Remove group" revokes every role the group holds at once, behind the Tier 1 `ConfirmDialog` that "Remove all
 * access" uses; `onRemoveGroup` is called only after confirming. */
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
    // Not a `getByRole("row", { name: /Engineering/ })` lookup: before filtering, Morgan Casey's row also mentions
    // "Engineering" in its Source line (see `GroupRow`).
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

/** A member whose only source is one direct role cannot have it cleared from the dropdown: the row exists only
 * through its grants, so clearing it would remove the member at once (a person changing roles clears the old one
 * after granting the new one). Removal stays the confirmed "Remove all access" action. Once a second role is held,
 * the first is clearable again. */
export const OnlyRoleCannotBeCleared: Story = {
  args: {
    members: [
      {
        user_id: "u-sam",
        display_name: "Sam Ortiz",
        email: "sam@example.com",
        effective_role: "member",
        sources: [
          {
            kind: "direct_role", role: "member", via_project_id: null, via_project_name: null,
            via_mode: null, via_group_id: null, via_group_name: null,
          },
        ],
        module_roles: [],
      },
    ],
    invites: [],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Sam Ortiz's roles" }));
    const only = within(document.body).getByRole("checkbox", { name: "Revoke Member from Sam Ortiz" });
    await expect(only).toBeChecked();
    await expect(only).toBeDisabled();
    await expectTooltip(reasonTarget(only), /only role/);
    await expect(within(document.body).getByRole("checkbox", { name: "Grant Stakeholder to Sam Ortiz" })).toBeEnabled();
  },
};

/** A member with many roles reads "N roles" in the Role cell instead of widening the column; the names stay in the
 * trigger's tooltip and the opened list. A short list still shows the names. */
export const ManyRolesCollapseToCount: Story = {
  args: {
    members: [
      { ...MEMBERS[0], user_id: "u-many", display_name: "Riley Park", email: "riley@example.com",
        sources: (["project_manager", "project_administrator", "stakeholder", "member"] as const).map((role) => ({
          kind: "direct_role" as const, role, via_project_id: null, via_project_name: null,
          via_mode: null, via_group_id: null, via_group_name: null,
        })),
        module_roles: [] },
      MEMBERS[1],
    ],
    invites: [],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const many = canvas.getByRole("button", { name: "Riley Park's roles" });
    await expect(many).toHaveTextContent("4 roles");
    await expectTooltip(many, /Project administrator/);
    await expect(canvas.getByRole("button", { name: "Priya Shah's roles" })).toHaveTextContent("Stakeholder");
  },
};
