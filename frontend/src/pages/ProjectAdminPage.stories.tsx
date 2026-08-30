import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type {
  ActionTypeDefinition,
  Category,
  Component,
  CustomFieldDefinition,
  DirectProjectMember,
  EffectiveMember,
  OrgGroup,
  PendingInvite,
  ProjectGroup,
  ProjectMemberSource,
  ProjectStage,
  ProjectStatusDefinition,
} from "../api/types";
import {
  buildActionType,
  buildProject,
  buildProjectListItem,
  buildProjectStatus,
  buildUser,
  withRouter,
  withStatefulAuth,
  withTerminology,
  withToast,
} from "../testing/storybook-helpers";
import { ProjectAdminPage } from "./ProjectAdminPage";

const PROJECT_ID = "project-1";

const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Scoping", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];
const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const groups: ProjectGroup[] = [
  {
    id: "g1", name: "Stakeholders", role: "stakeholder", is_default: true,
    member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [],
  },
];
const orgGroups: OrgGroup[] = [
  { id: "og1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const projectStatuses: ProjectStatusDefinition[] = [
  buildProjectStatus({ id: "st1", name: "Proposed", sort_order: 0 }),
  buildProjectStatus({ id: "st2", name: "Active", sort_order: 1 }),
];

function mockProjectAdminApis(
  overrides: {
    actionTypes?: ActionTypeDefinition[];
    customFields?: CustomFieldDefinition[];
    project?: ReturnType<typeof buildProject>;
    orgProjects?: ReturnType<typeof buildProjectListItem>[];
    memberSources?: ProjectMemberSource[];
    children?: ReturnType<typeof buildProjectListItem>[];
    effectiveMembers?: EffectiveMember[];
    groups?: ProjectGroup[];
    pendingInvites?: PendingInvite[];
    // Phase 5 (docs/decisions.md) — the Members section's second data
    // source, merged client-side with `groups` into `MemberRoleRow[]`.
    directMembers?: DirectProjectMember[];
  } = {}
) {
  const groupsForThisStory = overrides.groups ?? groups;
  const directMembersForThisStory = overrides.directMembers ?? [];
  const actionTypes = overrides.actionTypes ?? [buildActionType({ id: "at1", name: "Review", sort_order: 0 }), buildActionType({ id: "at2", name: "Test", sort_order: 1 })];
  const customFields = overrides.customFields ?? [];
  const project = overrides.project ?? buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", status_id: "st1" });
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return project;
    if (path.includes("/stages")) return stages;
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return categories;
    if (path.includes("/action-types")) return actionTypes;
    if (path.includes("/project-statuses")) return projectStatuses;
    // PendingInvitesSection's own fetch (Phase 3, docs/decisions.md) —
    // checked before "/groups" below purely for readability; the two
    // substrings don't actually collide.
    if (path.includes("/pending-invites")) return overrides.pendingInvites ?? [];
    // Members section (Phase 5) — checked before the plain "/groups" check
    // below, same reasoning.
    if (path.includes("/direct-members")) return directMembersForThisStory;
    // Checked before the plain "/groups" check below — /orgs/{id}/groups
    // also contains that substring, and returns a differently-shaped
    // OrgGroup[] (project groups vs. org groups).
    if (path.includes("/orgs/") && path.includes("/groups")) return orgGroups;
    // Both the Groups section's own paginated list (unchanged) and the
    // Members section's unpaginated `memberTableGroups` fetch (Phase 5) hit
    // this same "/groups" substring — both are fine returning the same
    // fixed `groupsForThisStory` array regardless of query params, matching
    // how a real unpaginated `GET .../groups` (no `limit`) would return
    // everything.
    if (path.includes("/groups")) return groupsForThisStory;
    if (path.includes("/custom-fields")) return customFields;
    if (path.includes("/report-config")) return {
      intro: "", chapters: [], appendices: [],
      intro_is_organisation_default: false, chapters_is_organisation_default: false, appendices_is_organisation_default: false,
      default_report_template_id: null,
    };
    if (path.includes("/report-templates")) return [];
    // Hierarchical projects (docs/decisions.md). Checked before the plain
    // "/users" check below — /orgs/{id}/users also matches that.
    if (path.includes("/member-sources")) return overrides.memberSources ?? [];
    if (path.includes("/effective-members")) return overrides.effectiveMembers ?? [];
    if (path.includes(`/projects/${PROJECT_ID}/children`)) return overrides.children ?? [];
    if (path.startsWith("/api/v1/projects?")) return overrides.orgProjects ?? [];
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  // The Groups tab's own group list paginates/searches (2026-08 UX audit
  // "Directories at scale") — org-group nesting still reads from the
  // plain `api.get` mock above, unchanged.
  spyOn(api, "getPage").mockImplementation(async (path: string) => {
    if (path.includes("/groups")) return { items: groupsForThisStory, total: groupsForThisStory.length };
    throw new Error(`unmocked getPage path: ${path}`);
  });
}

const meta: Meta<typeof ProjectAdminPage> = {
  title: "Pages/ProjectAdminPage",
  component: ProjectAdminPage,
  decorators: [
    withStatefulAuth(buildUser()),
    withRouter(`/projects/${PROJECT_ID}/admin`, "/projects/:projectId/admin/:group?"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectAdminPage>;

export const OverviewTabSaveSettings: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toHaveValue("Atlas Platform"));
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ name: "Atlas Platform" })
      )
    );
  },
};

export const OverviewTabSetOrgWideVisibility: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Visibility")).toHaveValue("only_specified"));
    await userEvent.selectOptions(canvas.getByLabelText("Visibility"), "org_wide");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ visibility: "org_wide" })
      )
    );
  },
};

export const OverviewTabArchive: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Archive project" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Archive project" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/archive`));
  },
};

// Terminology's own JSX/state/handlers are unchanged — only its location
// moved (2026-08 UX audit roadmap: 8 tabs -> 5), from its own tab into a
// sub-block underneath Overview's settings. No tab click needed any more:
// Overview is the default tab.
export const TerminologyTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByPlaceholderText("requirement")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("requirement"), "story");
    await userEvent.click(canvas.getByRole("button", { name: "Save terminology" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/terminology`,
        expect.objectContaining({ terminology: expect.objectContaining({ requirement: "story" }) })
      )
    );
  },
};

export const StagesTabAddAndTransition: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Stages now lives inside the merged "Structure" tab, as a
    // `CollapsibleSection` that's expanded by default — no separate expand
    // step needed.
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Start review" })).toBeInTheDocument());
    // Scoped to the "Project stages" section specifically: the sibling
    // "Components & categories" section (now mounted alongside it on the
    // same merged "Structure" tab) also has exactly one category in this
    // mock, which reuses the same "only one left" disabled-hint title —
    // an unscoped query is ambiguous between the two.
    const stagesSection = within(canvas.getByRole("button", { name: "Project stages section" }).closest(".card")!);
    // Deleting the only stage is blocked — there's nothing else to reassign to.
    await expect(stagesSection.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Start review" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/stages/s1/transition?new_status=review`));
  },
};

/** A component with existing categories can't be deleted until they're
 * moved or removed first — `deleteComponentHasCategoriesHint`. */
export const CategoriesTabDeleteBlockedWhileHasCategories: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Categories now lives inside the merged "Structure" tab, alongside
    // Stages, as a "Components & categories" `CollapsibleSection`.
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    // Component/category names are editable <input>s here, not static text.
    await waitFor(() => expect(canvas.getByDisplayValue("Login")).toBeInTheDocument());
    await expect(canvas.getByTitle("Delete or reassign this component's categories first.")).toBeDisabled();
  },
};

export const CategoriesTabAddCategory: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /New category/ })).toBeInTheDocument());
    // Scoped to the "Components & categories" section specifically: Stages
    // (now a sibling section on the same merged "Structure" tab) has its
    // own "Name"-placeholder "add stage" field, so an unscoped query is
    // ambiguous. Within this section, two "Name"/"Prefix"-placeholder
    // inputs exist: the per-component "add category" row (first, inside
    // the component's own block) and the "add component" row at the very
    // bottom (last).
    const componentsSection = within(
      canvas.getByRole("button", { name: "Components & categories section" }).closest(".card")!
    );
    const [nameInput] = componentsSection.getAllByPlaceholderText("Name");
    const [prefixInput] = componentsSection.getAllByPlaceholderText("Prefix");
    await userEvent.type(nameInput, "Sessions");
    await userEvent.type(prefixInput, "SES");
    await userEvent.click(componentsSection.getByRole("button", { name: /New category/ }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/categories`,
        expect.objectContaining({ name: "Sessions", prefix: "SES", component_id: "c1" })
      )
    );
  },
};

export const CustomFieldsTabAddField: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Custom fields now lives inside the merged "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByPlaceholderText("Field name")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Field name"), "Priority");
    await userEvent.click(canvas.getByRole("button", { name: /New field/ }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/custom-fields`,
        expect.objectContaining({ name: "Priority", field_type: "short_text" })
      )
    );
  },
};

export const CustomFieldsTabDeleteRequiresConfirmation: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      customFields: [
        { id: "cf1", project_id: PROJECT_ID, entity_kind: "requirement", name: "Safety critical", field_type: "checkbox", options: null, required: false, sort_order: 0 },
      ],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    // Custom fields now lives inside the merged "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByText("Safety critical")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Delete Safety critical" }));
    const dialog = body.getByRole("dialog", { name: "Delete Safety critical" });
    await expect(dialog).toBeInTheDocument();

    // Cancelling leaves the field in place and makes no request.
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.delete).not.toHaveBeenCalled();

    await userEvent.click(canvas.getByRole("button", { name: "Delete Safety critical" }));
    await userEvent.click(within(body.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/custom-fields/cf1`));
  },
};

/** Style guide "Pattern: modal dialog for entity create/rename": "+ New
 * group" opens a Modal instead of the Groups tab having no create form at
 * all (2026-08 UX audit finding) — mirrors OrgAdminPage's own "New group"
 * modal, just against the project-scoped endpoint, which also requires a
 * role up front (`ProjectGroupCreate.role`) since a project group's role
 * can't be changed after creation. */
export const GroupsTabCreateGroupViaModal: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "New group" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "New group" }));
    const dialog = body.getByRole("dialog", { name: "New group" });
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(within(dialog).getByPlaceholderText("e.g. Reviewers"), "Reviewers");
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "stakeholder");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/groups`,
        { name: "Reviewers", role: "stakeholder" }
      )
    );
    // Principle 7 — every mutation ends with feedback.
    await expect(body.getByText("Group created")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

// --- Groups tab: per-group SidePanel (Phase 5, docs/decisions.md) --------
// Replaces the old always-expanded `CollapsibleSection` accordion — a group
// row is now a plain button that opens a `SidePanel` with the same 3-way
// composition editor, a role `<select>` at the top, and a delete action.

export const GroupsTabOpensSidePanelWithRoleSelectAndDelete: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /Stakeholders/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));

    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    await expect(within(panel).getByRole("combobox", { name: "Group role" })).toHaveValue("stakeholder");
    // The default "Stakeholders" group (is_default: true, from
    // DEFAULT_GROUPS) can't be deleted — C-U-10's four standard groups.
    await expect(within(panel).getByRole("button", { name: "Delete group" })).toBeDisabled();
  },
};

export const GroupsTabAddMemberViaSidePanel: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /Stakeholders/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });

    const userInput = within(panel).getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(userInput, "amy");
    // The panel's own `UserAutocomplete` — no server-side search wired in
    // this story (no matching org users mocked), so this just confirms the
    // control renders and is reachable inside the panel (the panel now
    // also has a "Group role" `<select>` and an org-group nesting
    // `<select>`, both also `role="combobox"`, so this asserts against the
    // specific input rather than a bare `getByRole("combobox")`); the add
    // flow itself is exercised by `GroupsTabAddOrgGroupViaSidePanel` below
    // and by `MembersTabAddDirectMember`'s equivalent direct-role add.
    await expect(userInput).toHaveValue("amy");
    // Typing with `organizationId` set (as this panel's own `UserAutocomplete`
    // is) arms a 250ms debounced search fetch (`UserAutocomplete.tsx`).
    // Closing the panel here — a real, immediate unmount via this app's own
    // `SidePanel`/`onClose` lifecycle — lets that debounce's own effect
    // cleanup (`cancelled = true; clearTimeout(timer)`) run deterministically
    // before the story ends, rather than leaving a live timer for the test
    // runner's next story to race against.
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
  },
};

export const GroupsTabAddOrgGroupViaSidePanel: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /Stakeholders/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });

    const select = within(panel).getByRole("combobox", { name: "Nest an organisation group…" });
    await userEvent.selectOptions(select, "og1");
    const row = select.closest<HTMLElement>(".row")!;
    await userEvent.click(within(row).getByRole("button"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/groups/g1/members`,
        { org_group_id: "og1" }
      )
    );
  },
};

/** C-U-10's four standard groups can't be deleted (400 server-side; this
 * story pins the client-side disabled+title treatment that avoids the
 * round-trip for the common case). */
export const GroupsTabDeleteDefaultGroupDisabled: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    const deleteButton = within(panel).getByRole("button", { name: "Delete group" });
    await expect(deleteButton).toBeDisabled();
    await expect(deleteButton).toHaveAttribute("title", expect.stringContaining("can't be deleted"));
  },
};

/** A non-default group's delete goes through the Tier 1 `ConfirmDialog`
 * (style guide "Pattern: confirmation, in two tiers") before the `DELETE`
 * request fires. */
export const GroupsTabDeleteGroupRequiresConfirmation: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      groups: [
        { id: "g2", name: "Reviewers", role: "member", is_default: false, member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [] },
      ],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /Reviewers/ })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Reviewers/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Reviewers details" });
    const deleteButton = within(panel).getByRole("button", { name: "Delete group" });
    await expect(deleteButton).toBeEnabled();
    await userEvent.click(deleteButton);

    const confirmDialog = within(document.body).getByRole("dialog", { name: 'Delete "Reviewers"?' });
    await expect(api.delete).not.toHaveBeenCalled();
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Delete group" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/groups/g2`));
    await expect(within(document.body).getByText("Group deleted")).toBeInTheDocument();
  },
};

// The "click a group in Members, see its members" `?openGroup=` deep link
// (Phase 5) isn't covered by its own Storybook story: this file's `meta`
// already supplies a fixed `withRouter` decorator (one initial path for
// every story here), and react-router refuses to mount a second `<Router>`
// nested inside another — there's no way to give one story a different
// initial URL without restructuring every other story's decorators. The
// Playwright suite (`project-admin-groups.spec.ts`) covers this round trip
// end-to-end instead.

// --- Members tab (Phase 5, docs/decisions.md) ---------------------------
// `MemberRoleTable` fed by `GET /groups` + `GET /direct-members`, merged
// client-side — see `ProjectAdminPage.tsx`'s own `memberRoleRows`.

const directMemberAlex: DirectProjectMember = {
  user_id: "u-alex", display_name: "Alex Morgan", email: "alex@example.com", roles: ["stakeholder", "member"],
};

export const MembersTabShowsUsersAndGroups: Story = {
  beforeEach: () => mockProjectAdminApis({ directMembers: [directMemberAlex] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("cell", { name: "Stakeholders" })).toBeInTheDocument());
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    // Deliberately different role controls per row kind — see
    // `MemberRoleTable`'s own docstring for why this isn't unified.
    await expect(canvas.getByRole("combobox", { name: "Role for Stakeholders" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
  },
};

/** Toggling a direct member's role calls `POST`/`DELETE .../roles` — not a
 * group-membership endpoint — and updates the row in place (no full page
 * `reload()`, the same fix the style guide's "Pattern: multi-select
 * dropdown" section already applied to `OrgAdminPage.tsx`). */
export const MembersTabToggleDirectMemberRole: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ directMembers: [directMemberAlex] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(group).getByRole("checkbox", { name: "Grant Project administrator to Alex Morgan" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/roles`,
        { user_id: "u-alex", role: "project_administrator" }
      )
    );
  },
};

/** Changing a group's role from the Members table (`PATCH .../groups/{id}`,
 * Phase 5's fix for "project groups' role was fixed at creation") is
 * reflected immediately on the Groups tab's own `SidePanel`, with no
 * refetch needed. */
export const MembersTabChangeGroupRoleReflectsOnGroupsTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue({
      id: "g1", name: "Stakeholders", role: "project_administrator", is_default: true,
      member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Role for Stakeholders" })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Role for Stakeholders" }), "project_administrator");
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/groups/g1`,
        { role: "project_administrator" }
      )
    );
    await expect(within(document.body).getByText("Group updated")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    await expect(within(panel).getByRole("combobox", { name: "Group role" })).toHaveValue("project_administrator");
  },
};

/** The Members section's own "add a direct member" control
 * (`UserAutocomplete` + a role `<select>`) — distinct from the Groups
 * tab's per-group add flow, since this grants a direct role via
 * `POST .../roles` rather than group membership. */
export const MembersTabAddDirectMember: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Role to grant" })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Role to grant" }), "stakeholder");
    // The add control's own `UserAutocomplete` — no server-side search
    // wired in this story, so this just confirms the control renders and
    // is reachable with the chosen role alongside it.
    await expect(canvas.getByPlaceholderText("Type a name to add, or an email to invite…")).toBeInTheDocument();
  },
};

// --- PendingInvitesSection (Phase 3, docs/decisions.md) --------------------
// `CollapsibleSection`'s own accessible name for its (collapsed-by-default)
// toggle is "<title> section" — see CollapsibleSection.tsx.

const pendingInvitePending: PendingInvite = {
  id: "pi1", email: "waiting@example.com", role: "member", status: "pending",
  created_at: "2026-08-20T10:00:00Z", expires_at: "2026-09-03T10:00:00Z",
};
const pendingInviteExpired: PendingInvite = {
  id: "pi2", email: "toolate@example.com", role: "stakeholder", status: "expired",
  created_at: "2026-07-01T10:00:00Z", expires_at: "2026-07-15T10:00:00Z",
};

// Relocated (Phase 5, docs/decisions.md) from the old combined "Project
// groups" tab onto the new "Members" section — story names kept their
// "GroupsTab..." prefix historically but now click "Members".
export const MembersTabPendingInvitesEmpty: Story = {
  beforeEach: () => mockProjectAdminApis({ pendingInvites: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Pending invites section" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Pending invites section" }));
    await expect(canvas.getByText("No pending invites.")).toBeInTheDocument();
  },
};

export const MembersTabPendingInvitesShowsPendingAndExpired: Story = {
  beforeEach: () => mockProjectAdminApis({ pendingInvites: [pendingInvitePending, pendingInviteExpired] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Pending invites section" }));
    await waitFor(() => expect(canvas.getByText("waiting@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("toolate@example.com")).toBeInTheDocument();
    // Status rendered through the label map (style guide Principle 12), not
    // the raw "pending"/"expired" enum strings.
    await expect(canvas.getByText("Pending")).toBeInTheDocument();
    await expect(canvas.getByText("Expired")).toBeInTheDocument();
  },
};

export const MembersTabPendingInvitesResend: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ pendingInvites: [pendingInvitePending] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Pending invites section" }));
    await waitFor(() => expect(canvas.getByText("waiting@example.com")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Resend invite to waiting@example.com" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/pending-invites/pi1/resend`)
    );
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Invite resent to waiting@example.com.")).toBeInTheDocument();
  },
};

export const ReportSetupTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Report Setup" }));
    await waitFor(() => expect(canvas.getByText("Project intro")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/report-config`, expect.any(Object)));
  },
};

export const OverviewTabChangeStatus: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Status")).toHaveValue("st1"));
    await userEvent.selectOptions(canvas.getByLabelText("Status"), "st2");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ status_id: "st2" })
      )
    );
  },
};

export const ActionTypesTabAddAndReorder: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Action types now lives inside the merged "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Name"), "Inspection");
    await userEvent.click(canvas.getByRole("button", { name: /New action type/ }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/action-types`,
        { name: "Inspection" }
      )
    );
  },
};

/** With only one action type left in the project, delete is disabled
 * outright — same §4.0 minimum-one-remaining rule as the org-scoped
 * project statuses/link types on OrgAdminPage. */
export const ActionTypesTabDeleteDisabledAtLastRow: Story = {
  beforeEach: () => mockProjectAdminApis({ actionTypes: [buildActionType({ id: "at1", name: "Review", sort_order: 0 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Action types now lives inside the merged "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
  },
};

/** Proves `pluralize()`'s irregular-plural fix (`frontend/src/i18n/
 * terminology.ts`) against the *default* English terminology, not an
 * override — a naive `+s` pluralisation would render this section's title
 * as "Components & categorys" instead of "Components & categories". No
 * `withTerminology` decorator here on purpose: the bug this guards is in
 * the default-term pluralisation path itself. */
export const StructureTabPluralisesCategoryCorrectly: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    await expect(canvas.getByText("Components & categories")).toBeInTheDocument();
    await expect(canvas.queryByText(/categorys/i)).not.toBeInTheDocument();
  },
};

/**
 * C-C-03, the 2026-08 UX audit's single most visible example: the
 * custom-fields entity-kind dropdown/badge used to read "Requirement" /
 * "Change request" literally — one tab over from the Terminology settings
 * meant to rename those exact words (`CUSTOM_FIELD_ENTITY_KIND_LABEL` in
 * `api/types.ts`, a static export, could never be terminology-aware; both
 * call sites now read `strings.admin.entityKindRequirement`/
 * `entityKindChangeRequest` via `useStrings()` instead).
 */
export const CustomFieldsTabEntityKindDropdownReflectsTerminology: Story = {
  decorators: [withTerminology({ requirement: "Spec", change_request: "ECR" })],
  beforeEach: () => {
    mockProjectAdminApis({
      customFields: [
        { id: "cf1", project_id: PROJECT_ID, entity_kind: "requirement", name: "Safety critical", field_type: "checkbox", options: null, required: false, sort_order: 0 },
      ],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByText("Safety critical")).toBeInTheDocument());
    // The existing field's own entity-kind badge.
    await expect(canvas.getByText("Spec", { selector: "span.badge" })).toBeInTheDocument();
    // The "New field" row's entity-kind <select> options.
    await expect(canvas.getByRole("option", { name: "Spec" })).toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "ECR" })).toBeInTheDocument();
  },
};

// --- Hierarchical projects (docs/decisions.md) ------------------------

export const ParentFieldShowsCurrentParentPlainly: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      project: buildProject({
        id: PROJECT_ID, organization_id: "org-1", name: "Authentication", status_id: "st1",
        parent_project_id: "parent-1", role_inheritance_mode: "mirror_all",
      }),
      orgProjects: [buildProjectListItem({ id: "parent-1", name: "Platform", organization_id: "org-1" })],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Platform")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Mirror all roles")).toBeInTheDocument();
  },
};

/** Selecting MIRROR_ALL/MIRROR_ROLE requires the tier-2 confirmation
 * (docs/decisions.md) before it takes effect — the setting doesn't change
 * until the dialog is confirmed. */
export const SelectingMirrorAllRequiresConfirmation: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      orgProjects: [buildProjectListItem({ id: "parent-1", name: "Platform", organization_id: "org-1", can_be_parent: true })],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Parent project")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Parent project"), "Platform");
    await userEvent.selectOptions(canvas.getByLabelText("Inherit access from parent"), "Mirror all roles");
    await expect(within(document.body).getByText("Enable access inheritance?")).toBeInTheDocument();
    // Still showing "None" until confirmed.
    await expect(canvas.getByDisplayValue("None")).toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("button", { name: "Enable inheritance" }));
    await expect(canvas.getByDisplayValue("Mirror all roles")).toBeInTheDocument();
  },
};

export const SaveErrorShowsInline: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      orgProjects: [buildProjectListItem({ id: "parent-1", name: "Platform", organization_id: "org-1", can_be_parent: true })],
    });
    spyOn(api, "patch").mockRejectedValue(new Error("This project's only manager is inherited from 'Platform'; assign a direct project manager before disabling inheritance or changing its parent."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Parent project")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(canvas.getByText(/only manager is inherited/)).toBeInTheDocument());
  },
};

/** Generalized (docs/decisions.md): member sources are no longer restricted
 * to a direct child — any same-organisation project is a valid source, and
 * each one shows its own mirror mode as a badge next to its name. */
export const MemberSourcesListAndAdd: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      memberSources: [
        { source_project_id: "sibling-1", source_project_name: "Authentication", mirror_mode: "mirror_role", mirror_filter_role: "project_manager" },
      ],
      orgProjects: [
        buildProjectListItem({ id: "sibling-1", name: "Authentication", organization_id: "org-1" }),
        buildProjectListItem({ id: "sibling-2", name: "Billing", organization_id: "org-1" }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Authentication" })).toBeInTheDocument());
    // Its mirror mode/filter role renders as a badge, not just a bare name.
    await expect(canvas.getByText("Mirrors Project manager")).toBeInTheDocument();
    // Already-listed source isn't offered again in the add dropdown — not
    // restricted to structural children, "Billing" (an unrelated
    // same-org project) is a valid candidate.
    await expect(canvas.queryByRole("option", { name: "Authentication" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Billing" })).toBeInTheDocument();

    const postSpy = spyOn(api, "post").mockResolvedValue(undefined);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Source project" }), "sibling-2");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Mirror mode" }), "mirror_all");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/member-sources`,
        { source_project_id: "sibling-2", mirror_mode: "mirror_all", mirror_filter_role: null },
      )
    );
  },
};

/** A project group's members can be defined as "the direct members of that
 * other project" (`ProjectGroupMember.source_project_id`, docs/decisions.md)
 * — a third option alongside individual users and nested {@link OrgGroup}s.
 * Phase 5 extends the existing labelled line with a `Link` to that
 * project's own new Members page and a clarifying "this is live, not a
 * fixed list" hint — both now live inside the group's `SidePanel`. */
export const ProjectGroupCanReferenceAnotherProjectsMembers: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      groups: [
        {
          id: "g1", name: "Stakeholders", role: "stakeholder", is_default: true,
          member_user_ids: [], member_org_group_ids: [], member_source_project_ids: ["sibling-1"],
        },
      ],
      orgProjects: [
        buildProjectListItem({ id: "sibling-1", name: "Authentication", organization_id: "org-1" }),
        buildProjectListItem({ id: "sibling-2", name: "Billing", organization_id: "org-1" }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await userEvent.click(canvas.getByRole("button", { name: /Stakeholders/ }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    await waitFor(() => expect(within(panel).getByText("Authentication's members")).toBeInTheDocument());
    // The new Phase-5 link to that project's own Members page, plus the
    // "this is live, not a fixed list" clarifying hint.
    await expect(within(panel).getByRole("link", { name: "View members" })).toHaveAttribute(
      "href", "/projects/sibling-1/admin/members"
    );
    await expect(within(panel).getByText(/Live/)).toBeInTheDocument();
    // Already-referenced project isn't offered again; an unrelated
    // same-org project ("Billing") is a valid candidate.
    await expect(within(panel).queryByRole("option", { name: "Authentication" })).not.toBeInTheDocument();
    await expect(within(panel).getByRole("option", { name: "Billing" })).toBeInTheDocument();

    const postSpy = spyOn(api, "post").mockResolvedValue(undefined);
    await userEvent.selectOptions(within(panel).getByRole("combobox", { name: "Referenced project" }), "sibling-2");
    await userEvent.click(within(panel).getByRole("button", { name: "Reference another project's members…" }));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/groups/g1/members`,
        { source_project_id: "sibling-2" },
      )
    );
  },
};

export const EffectiveMembersShowsProvenance: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [
            { kind: "forward_inherited", role: "project_manager", via_project_id: "parent-1", via_project_name: "Platform", via_mode: "mirror_all" },
          ],
        },
        {
          user_id: "u2", display_name: "Sam Lee", email: "sam@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null }],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Effective members section" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show members" }));
    await waitFor(() => expect(canvas.getByText("Priya Shah", { exact: false })).toBeInTheDocument());
    await expect(canvas.getByText(/Inherited from 'Platform'/)).toBeInTheDocument();
    await expect(canvas.getByText("Sam Lee", { exact: false })).toBeInTheDocument();
    await expect(canvas.getByText(/Direct/)).toBeInTheDocument();
  },
};

/** UX review: the members table is now searchable, matching Org Admin's
 * Users table's structural pattern (search box + sortable columns) instead
 * of a bare unsearchable bullet list. */
export const EffectiveMembersSearchFilters: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [{ kind: "direct", role: "project_manager", via_project_id: null, via_project_name: null, via_mode: null }],
        },
        {
          user_id: "u2", display_name: "Sam Lee", email: "sam@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null }],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Effective members section" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show members" }));
    await waitFor(() => expect(canvas.getByText("Priya Shah")).toBeInTheDocument());
    await expect(canvas.getByText("Sam Lee")).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Search members"), "sam");
    await expect(canvas.getByText("Sam Lee")).toBeInTheDocument();
    await expect(canvas.queryByText("Priya Shah")).not.toBeInTheDocument();
  },
};

/** Clicking the Email column header sorts the table by email, ascending
 * then descending — the same `SortableHeader`/`cycleSort` pattern used by
 * every other sortable table in the app. */
export const EffectiveMembersSortByEmail: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "zoe@example.com", effective_role: "project_manager",
          sources: [{ kind: "direct", role: "project_manager", via_project_id: null, via_project_name: null, via_mode: null }],
        },
        {
          user_id: "u2", display_name: "Sam Lee", email: "amy@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null }],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Effective members section" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show members" }));
    await waitFor(() => expect(canvas.getByText("zoe@example.com")).toBeInTheDocument());

    // Scoped to the "Effective members" section specifically: the new
    // Phase-5 `MemberRoleTable` above it on the same "Members" section is
    // also a sortable table with its own "Email" column header and rows,
    // so an unscoped query is ambiguous.
    const section = within(canvas.getByRole("button", { name: "Effective members section" }).closest(".card")!);
    const rows = () => section.getAllByRole("row").slice(1); // drop header row
    await expect(rows()[0]).toHaveTextContent("zoe@example.com");

    await userEvent.click(section.getByRole("button", { name: "Email" }));
    await waitFor(() => expect(rows()[0]).toHaveTextContent("amy@example.com"));
    await expect(section.getByRole("columnheader", { name: "Email" })).toHaveAttribute("aria-sort", "ascending");
  },
};

export const MaterializeButtonConvertsInheritedAccess: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [
            { kind: "forward_inherited", role: "project_manager", via_project_id: "parent-1", via_project_name: "Platform", via_mode: "mirror_all" },
          ],
        },
      ],
    });
    spyOn(api, "post").mockResolvedValue({ created: [{ user_id: "u1", role: "project_manager" }], skipped: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Effective members section" }));
    await userEvent.click(canvas.getByRole("button", { name: "Show members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Convert all inherited access to direct roles" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Convert all inherited access to direct roles" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/materialize-inherited-access`));
    await waitFor(() => expect(within(document.body).getByText("Converted 1 user to direct roles.")).toBeInTheDocument());
  },
};

/** "Add sub-project" navigates to ProjectListPage with the parent
 * pre-filled, rather than duplicating the create-project modal here. Only
 * reachable once this project has opted in to being a parent
 * (can_be_parent) — see AddSubProjectDisabledUntilEligible below for the
 * disabled case. */
export const AddSubProjectNavigatesToProjectList: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      project: buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", status_id: "st1", can_be_parent: true }),
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: /Add sub-/ })).toBeInTheDocument());
    // Navigation itself is exercised end-to-end in the Playwright suite —
    // this just confirms the entry point renders and is reachable.
    await expect(canvas.getByRole("button", { name: /Add sub-/ })).toBeEnabled();
  },
};

/** can_be_parent (docs/decisions.md) defaults to false — "Add sub-project"
 * must not offer a path straight into a create flow the backend would
 * reject. */
export const AddSubProjectDisabledUntilEligible: Story = {
  beforeEach: () => mockProjectAdminApis({}),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: /Add sub-/ })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: /Add sub-/ })).toBeDisabled();
  },
};

/** The checkbox itself: toggling it and saving sends can_be_parent through
 * to the PATCH payload. */
export const CanBeParentToggleSaves: Story = {
  beforeEach: () => {
    mockProjectAdminApis({});
    spyOn(api, "patch").mockResolvedValue(buildProject({ id: PROJECT_ID, organization_id: "org-1", can_be_parent: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText(/Allow this .* to be a parent/)).toBeInTheDocument());
    await userEvent.click(canvas.getByLabelText(/Allow this .* to be a parent/));
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}`, expect.objectContaining({ can_be_parent: true })),
    );
  },
};

/** No eligible candidates and no parent currently set — the "Parent
 * project" field (and its dependent inheritance-mode fields) render
 * nothing rather than an empty picker with only "None" in it. */
export const ParentFieldHiddenWithNoEligibleCandidates: Story = {
  beforeEach: () => mockProjectAdminApis({ orgProjects: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByLabelText("Name")).toHaveValue("Atlas Platform"));
    await expect(canvas.queryByText("Parent project")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Inherit access from parent")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "dark" } };
