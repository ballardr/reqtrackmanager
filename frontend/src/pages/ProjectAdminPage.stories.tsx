import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type {
  ActionTypeDefinition,
  Category,
  Component,
  CustomFieldDefinition,
  EffectiveMember,
  ModuleRoleDefinition,
  OrgGroup,
  OrgGroupProjectRoleSummary,
  Organization,
  PendingInvite,
  ProjectGroup,
  ProjectLinkType,
  ProjectMemberSource,
  ProjectModuleEnablement,
  ProjectModuleSubComponent,
  ProjectStage,
  ProjectStatusDefinition,
} from "../api/types";
import {
  buildActionType,
  buildProject,
  buildProjectLinkType,
  buildProjectListItem,
  buildProjectStatus,
  buildStageWorkflow,
  buildUser,
  withRouter,
  withStatefulAuth,
  withTerminology,
  withToast,
  openAddDialog,
} from "../testing/storybook-helpers";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { buildUsage, buildVocabulary } from "../testing/tagsFixtures";
import { ProjectAdminPage } from "./ProjectAdminPage";

const PROJECT_ID = "project-1";

const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Scoping", workflow_id: "workflow-1", workflow_name: "Standard", phase_id: "phase-scoping", phase_name: "Scoping", phase_kind: "open", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, owner: null, review_deadline: null },
];
const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const groups: ProjectGroup[] = [
  {
    id: "g1", name: "Stakeholders", roles: ["stakeholder"],
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
    groupRoles?: OrgGroupProjectRoleSummary[];
    groups?: ProjectGroup[];
    pendingInvites?: PendingInvite[];
    moduleRoles?: ModuleRoleDefinition[];
    // The Modules tab's bulk module list and, per module, its declared sub-components (keyed by
    // `module_key`; `[]` when none are declared, as the real `GET .../subcomponents` returns).
    // The "Link types" section of Fields & actions (`LinkTypesPanel`, project scope).
    linkTypes?: ProjectLinkType[];
    projectModules?: ProjectModuleEnablement[];
    projectModuleSubComponents?: Record<string, ProjectModuleSubComponent[]>;
    // The organisation's `force_require_change_request_for_approved_links`, read by a bare `GET /orgs/{id}`.
    organization?: Organization;
    stages?: ProjectStage[];
    categories?: Category[];
  } = {}
) {
  const groupsForThisStory = overrides.groups ?? groups;
  const actionTypes = overrides.actionTypes ?? [buildActionType({ id: "at1", name: "Review", sort_order: 0 }), buildActionType({ id: "at2", name: "Test", sort_order: 1 })];
  const customFields = overrides.customFields ?? [];
  const project = overrides.project ?? buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", status_id: "st1" });
  const organization: Organization = overrides.organization ?? {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
    force_require_change_request_for_approved_links: false,
    allow_ai_approvals: false,
  };
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return project;
    if (path.endsWith(`/projects/${PROJECT_ID}/tags`)) return buildVocabulary();
    if (path.includes(`/projects/${PROJECT_ID}/tags/usage`)) return buildUsage();
    // Checked before the "/orgs/" + "/groups"/"/users" branches below,
    // which this bare org-detail path doesn't match (no further segment).
    if (path === `/api/v1/orgs/${project.organization_id}`) return organization;
    if (path.endsWith("/stage-workflows")) return [buildStageWorkflow()];
    if (path.endsWith("/stage-workflows/hidden")) return [];
    if (path.includes("/stages")) return overrides.stages ?? stages;
    if (path.endsWith("/structure-counts")) {
      const tree = overrides.categories ?? categories;
      return {
        components: Object.fromEntries(components.map((c) => [c.id, { categories: tree.filter((k) => k.component_id === c.id).length, requirements: 0 }])),
        categories: {},
      };
    }
    if (path.includes("/suggest-prefix")) return { prefix: "SES" };
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return overrides.categories ?? categories;
    if (path.includes("/action-types")) return actionTypes;
    if (path.endsWith("/link-types")) return { locked: false, items: overrides.linkTypes ?? [buildProjectLinkType({ id: "lt-related", forward_name: "Related to", reverse_name: "Related to" })] };
    if (path.endsWith("/artefact-types")) return [{ type: "requirement", label: "Requirement" }];
    if (path.endsWith("/artefact-link-rules")) return [];
    if (path.includes("/project-statuses")) return projectStatuses;
    // `ProjectMembersTable`'s own second data source — checked before "/groups" below purely for
    // readability; the two substrings don't actually collide.
    if (path.includes("/pending-invites")) return overrides.pendingInvites ?? [];
    // Checked before the plain "/groups" check below — /orgs/{id}/groups
    // also contains that substring, and returns a differently-shaped
    // OrgGroup[] (project groups vs. org groups).
    if (path.includes("/orgs/") && path.includes("/groups")) return orgGroups;
    // Both the Groups section's paginated list and the Members section's `?openGroup=` lookup hit "/groups";
    // the fixed `groupsForThisStory` answers both, as an unpaginated `GET .../groups` would.
    if (path.includes("/groups")) return groupsForThisStory;
    if (path.includes("/custom-fields")) return customFields;
    if (path.endsWith("/report-layouts")) return [buildLayoutSummary({ project_id: PROJECT_ID })];
    // Report Setup merges these three lists with the layouts: empty is a valid answer for each.
    if (path.endsWith("/report-packs") || path.endsWith("/report-placements") || path.endsWith("/report-folders")) return [];
    // Hierarchical projects (docs/decisions.md). Checked before the plain
    // "/users" check below — /orgs/{id}/users also matches that.
    if (path.includes("/member-sources")) return overrides.memberSources ?? [];
    // Read inside `reload()` with effective-members and pending-invites; unmocked, the Members section's
    // module-role fetch would reject `reload()`'s `Promise.all`.
    if (path.includes("/module-roles")) return overrides.moduleRoles ?? [];
    // Before the generic "/modules" bulk list, whose substring the enablement and subcomponents paths also contain;
    // `moduleKey` is parsed from the path so each module's fixture reaches its own override.
    if (path.includes("/subcomponents")) {
      const moduleKey = path.split("/modules/")[1]?.split("/subcomponents")[0];
      return overrides.projectModuleSubComponents?.[moduleKey ?? ""] ?? [];
    }
    if (path.includes("/modules/") && path.includes("/enablement")) {
      const moduleKey = path.split("/modules/")[1]?.split("/enablement")[0];
      const found = overrides.projectModules?.find((m) => m.module_key === moduleKey);
      if (found) return found;
      throw new Error(`unmocked module enablement fixture for: ${moduleKey}`);
    }
    if (path.endsWith("/modules")) return overrides.projectModules ?? [];
    // `ProjectMembersTable`'s third data source; "/group-roles" does not overlap "/groups", so order does not matter.
    if (path.includes("/group-roles")) return overrides.groupRoles ?? [];
    if (path.includes("/effective-members")) return overrides.effectiveMembers ?? [];
    if (path.includes(`/projects/${PROJECT_ID}/children`)) return overrides.children ?? [];
    if (path.startsWith("/api/v1/projects?")) return overrides.orgProjects ?? [];
    // `UserAutocomplete`'s debounced server search (organizationId mode), before the "/users" catch-all it also
    // matches. No user matches by default; the group-matching story types into it without needing a user result.
    if (path.includes("/users/search")) return { members: [], external: null };
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  // The Groups tab's group list paginates and searches; organisation-group nesting reads from the plain `api.get` mock above.
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

/** The Project report name is a short, optional name: it is sent trimmed on save, a blank one clears it, and its help explains it. */
export const OverviewTabProjectReportName: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      project: buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", report_name: "Atlas", status_id: "st1" }),
    });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = await waitFor(() => {
      const input = canvas.getByLabelText("Project report name");
      expect(input).toHaveValue("Atlas");
      return input;
    });
    await expect(field).toHaveAttribute("maxlength", "255");
    await expect(canvas.getByRole("button", { name: "Help: Project report name" })).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "  Atlas 2  ");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}`, expect.objectContaining({ report_name: "Atlas 2" })),
    );
    await userEvent.clear(field);
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenLastCalledWith(`/api/v1/projects/${PROJECT_ID}`, expect.objectContaining({ report_name: null })),
    );
  },
};

/** Under automatic assignment the code is shown but cannot be edited, and is not sent on save. */
export const OverviewTabCodeIsReadOnlyUnderAutomaticAssignment: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ project: buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", code: "ATL", status_id: "st1" }) });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const code = await waitFor(() => {
      const el = canvas.getByLabelText("Code");
      expect(el).toHaveValue("ATL");
      return el;
    });
    await expect(code).toHaveAttribute("readonly");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    await expect((api.patch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][1]).not.toHaveProperty("code");
  },
};

/** Under manual assignment the code is editable and a changed value is sent upper-cased. */
export const OverviewTabCodeEditableUnderManualAssignment: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      project: buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", code: "ATL", status_id: "st1" }),
      organization: { ...buildForcedOrg(), force_require_change_request_for_approved_links: false,
        project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "manual", locked: false } },
    });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const code = await waitFor(() => {
      const el = canvas.getByLabelText("Code");
      expect(el).toHaveValue("ATL");
      expect(el).not.toHaveAttribute("readonly");
      return el;
    });
    await userEvent.clear(code);
    await userEvent.type(code, "atlas");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}`, expect.objectContaining({ code: "ATLAS" }))
    );
  },
};

/** When the organisation has locked codes, a manager sees the code read-only with the reason, and never sends it. */
export const OverviewTabCodeReadOnlyWhenLocked: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      project: { ...buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", code: "ATL", status_id: "st1" }), code_change_locked: true },
      organization: { ...buildForcedOrg(), force_require_change_request_for_approved_links: false,
        project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "manual", locked: true } },
    });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const code = await waitFor(() => {
      const el = canvas.getByLabelText("Code");
      expect(el).toHaveValue("ATL");
      return el;
    });
    await expect(code).toHaveAttribute("readonly");
    await expect(canvas.getByText(/Locked by your organisation/)).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    await expect((api.patch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][1]).not.toHaveProperty("code");
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

/** The unforced case: the project's opt-in checkbox is enabled and unchecked, and no exemption checkbox shows because the organisation forces nothing. */
export const OverviewTabRequireChangeRequestForLinks: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const checkbox = await waitFor(() =>
      canvas.getByLabelText("Require a change request to add/remove links on approved requirements")
    );
    await expect(checkbox).toBeEnabled();
    await expect(checkbox).not.toBeChecked();
    await expect(canvas.queryByLabelText(/Exempt this project/)).not.toBeInTheDocument();

    await userEvent.click(checkbox);
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ require_change_request_for_approved_links: true })
      )
    );
  },
};

export const OverviewTabAllowAiApprovals: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await waitFor(() => canvas.getByRole("switch", { name: "Allow AI approval via MCP for this project" }));
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);

    const dialog = within(await within(document.body).findByRole("dialog", { name: "Allow AI approval for this project?" }));
    const confirmButton = dialog.getByRole("button", { name: "Allow AI approval" });
    await expect(confirmButton).toBeDisabled();
    await userEvent.click(dialog.getByRole("checkbox"));
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    await expect(toggle).toBeChecked();

    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ allow_ai_approvals: true })
      )
    );
  },
};

/** Once the organisation forces the policy, the project's checkbox is checked and disabled with an explanatory `title`
 * (as in `ProjectMembersTable.tsx`) and an "Exempt this project" checkbox appears as the only way out. */
export const OverviewTabForcedByOrgPolicy: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ organization: { ...buildForcedOrg() } });
    spyOn(api, "patch").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const checkbox = await waitFor(() =>
      canvas.getByLabelText("Require a change request to add/remove links on approved requirements")
    );
    await expect(checkbox).toBeChecked();
    await expect(checkbox).toBeDisabled();
    const exemptCheckbox = canvas.getByLabelText(/Exempt this project/);
    await expect(exemptCheckbox).not.toBeChecked();

    await userEvent.click(exemptCheckbox);
    await expect(checkbox).toBeEnabled();
    await expect(checkbox).not.toBeChecked();

    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}`,
        expect.objectContaining({ exempt_from_org_link_lock: true })
      )
    );
  },
};

function buildForcedOrg(): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: null, report_accent_color_hex: null, report_include_logo: true, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    code: "ACME", project_code_policy: { kind: "alphanumeric", min_length: 2, max_length: 6, assignment: "auto", locked: false }, enforce_code_everywhere: false,
    force_require_change_request_for_approved_links: true,
    allow_ai_approvals: false,
  };
}

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

// Terminology is a sub-block under Overview's settings; Overview is the default tab, so no tab click is needed.
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
    // Stages live under the "Stage phases" group, in a `CollapsibleSection` that is expanded by default.
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Phase of Scoping" })).toBeInTheDocument());
    // Scoped to the "Project stages" section: "Components & categories" on the same Structure tab also has one category here,
    // with the same "only one left" disabled-hint title.
    const stagesSection = within(canvas.getByRole("button", { name: "Project stages section" }).closest(".card")!);
    // Deleting the only stage is blocked — there's nothing else to reassign to.
    await expect(stagesSection.getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Phase of Scoping" }), "Review");
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/stages/s1/transition`, { phase_id: "phase-review", cascade_to_requirements: false }),
    );
  },
};

/** The Stages section draws no empty fields: "New stage" opens the dialog a stage is named and given a workflow in. */
export const StagesTabNewStageIsMadeInADialog: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue({ id: "s-new" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Phase of Scoping" })).toBeInTheDocument());
    await expect(canvas.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    const dialog = await openAddDialog(canvas, "New stage");
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Design");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/stages`, { name: "Design", workflow_id: "workflow-1" }),
    );
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** Moving a stage into a closed phase first asks whether to complete its approved requirements too. */
export const StagesTabClosingAPhaseOffersToCompleteRequirements: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Phase of Scoping" }), "Completed");
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("checkbox"));
    await userEvent.click(dialog.getByRole("button", { name: "Completed" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/stages/s1/transition`, { phase_id: "phase-completed", cascade_to_requirements: true }),
    );
  },
};

/** Without the project manager role the locked phases are listed as unavailable, with why, instead of failing after the choice. */
export const StagesTabLockedPhasesNeedAProjectManager: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ stages: stages.map((st) => ({ ...st, can_lock: false })) });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    const phase = await canvas.findByRole("combobox", { name: "Phase of Scoping" });
    const locked = within(phase).getByRole("option", { name: "Approved (project manager only)" });
    await expect(locked).toBeDisabled();
    await expect(within(phase).getByRole("option", { name: "Review" })).toBeEnabled();
  },
};

/** The workflow picker is always there, and "New workflow" beside it creates a project workflow and selects it. */
export const StagesTabNewWorkflowFromTheNewStageForm: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue({ id: "workflow-new" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    // The workflows list has its own "New workflow" button; this is the one inside the new-stage dialog.
    const stageDialog = await openAddDialog(canvas, "New stage");
    await userEvent.click(stageDialog.getByRole("button", { name: "New workflow" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New workflow" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Workflow name/ }), "Tendered");
    await userEvent.type(dialog.getByRole("textbox", { name: "Phase name 1" }), "Scoping");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/stage-workflows`,
        { name: "Tendered", phases: [{ name: "Scoping", kind: "open" }] },
      ),
    );
  },
};

/** Deleting a stage always asks where its requirements go: the shared in-use dialog lists the other
 * stages, confirm stays disabled until one is chosen, and the delete carries `reassign_to`. */
export const StagesTabDeleteReassignsViaDialog: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      stages: [
        ...stages,
        { id: "s2", project_id: PROJECT_ID, name: "Design", workflow_id: "workflow-1", workflow_name: "Standard", phase_id: "phase-scoping", phase_name: "Scoping", phase_kind: "open", sort_order: 1, is_current: false, approved_at: null, completed_at: null, completed_by: null, owner: null, review_deadline: null },
      ],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Workflows and phases" }));
    await waitFor(() => expect(canvas.getAllByRole("button", { name: "Delete this stage" })).toHaveLength(2));
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete this stage" })[1]);

    const dialog = within(await within(document.body).findByRole("dialog", { name: "Delete “Design”?" }));
    const confirm = dialog.getByRole("button", { name: "Confirm delete" });
    await expect(confirm).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Scoping");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/stages/s2?reassign_to=s1`));
  },
};

/** The Structure group shows the components as a tree; a category is reached by opening its component. */
const openStructureRow = async (canvas: ReturnType<typeof within>, component: string) => {
  await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
  await userEvent.click(await canvas.findByRole("button", { name: `Expand ${component}` }));
};

/** The action menu of a Structure row. */
const openRowMenu = async (canvas: ReturnType<typeof within>, name: string) =>
  userEvent.click(await canvas.findByRole("button", { name: `Actions for ${name}` }));

/** A category is deleted with no target first, after a plain confirmation; an empty one (here the project's
 * only category) goes in one step. */
export const StructureTabDeleteEmptyCategoryNeedsNoTarget: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openStructureRow(canvas, "Authentication");
    await openRowMenu(canvas, "Login");
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Delete" }));

    const dialog = within(await within(document.body).findByRole("dialog", { name: "Delete this category" }));
    await userEvent.click(dialog.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/categories/cat1`));
    await expect(api.delete).toHaveBeenCalledTimes(1);
  },
};

/** A 409 from the plain delete opens the reassignment dialog with the server's own message; the second delete
 * carries `reassign_to`, and the other categories are listed as "Component / Category". */
export const StructureTabDeleteCategoryInUseReassignsViaDialog: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      categories: [
        ...categories,
        { id: "cat2", project_id: PROJECT_ID, component_id: "c1", name: "Logout", prefix: "OUT", sort_order: 1 },
      ],
    });
    spyOn(api, "delete")
      .mockRejectedValueOnce(new ApiError(409, "This category is still in use (requirements: 2, placed records: 0) — move them first."))
      .mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openStructureRow(canvas, "Authentication");
    await openRowMenu(canvas, "Logout");
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Delete this category" })).getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/categories/cat2`));

    const dialog = within(await within(document.body).findByRole("dialog", { name: "Delete “Logout”?" }));
    await expect(dialog.getByText(/requirements: 2, placed records: 0/)).toBeInTheDocument();
    const confirm = dialog.getByRole("button", { name: "Confirm delete" });
    await expect(confirm).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Authentication / Login");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/categories/cat2?reassign_to=cat1`));
  },
};

/** A component with existing categories can't be deleted until they're moved or removed first. */
export const StructureTabDeleteBlockedWhileComponentHasCategories: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    await openRowMenu(canvas, "Authentication");
    await expect(await within(document.body).findByRole("menuitem", { name: "Delete" })).toBeDisabled();
  },
};

/** Add category opens the side panel with the prefix suggested from the name, and Save creates it under that component. */
export const StructureTabAddCategory: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Structure" }));
    await openRowMenu(canvas, "Authentication");
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Add category to Authentication" }));
    const panel = within(await within(document.body).findByRole("dialog", { name: "Add category to Authentication" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Sessions");
    await waitFor(() => expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("SES"));
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
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
    // Custom fields are inside the "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await expect(canvas.queryByRole("textbox", { name: "Field name" })).not.toBeInTheDocument();
    const dialog = await openAddDialog(canvas, "New field");
    await expect(requiredCaptions(document.body)).toEqual(["Field name"]);
    await userEvent.type(dialog.getByRole("textbox", { name: "Field name" }), "Priority");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
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
    // Custom fields are inside the "Fields & actions" tab.
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

/** Style guide "Pattern: modal dialog for entity create/rename": "+ New group" opens a Modal against the project-scoped
 * endpoint (as OrgAdminPage's "New group"). A group is created bare (zero roles; `ProjectGroupCreate` takes no role); roles are
 * granted afterwards from the group row's `MultiSelectDropdown` (`GroupsTabGrantAndRevokeGroupRole`). */
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
    // The modal has only the name field.
    await expect(within(dialog).queryByLabelText("Role")).not.toBeInTheDocument();

    await userEvent.type(within(dialog).getByPlaceholderText("e.g. Reviewers"), "Reviewers");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/groups`, { name: "Reviewers" })
    );
    // Principle 7 — every mutation ends with feedback.
    await expect(body.getByText("Group created")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

// --- Groups tab: DirectoryTable + per-group SidePanel --------------------
// A group row opens its `SidePanel` (3-way composition editor, role select, delete action) through a real `<button>`
// (`DirectoryTable`'s `onRowClick`, not `rowHref`): any two same-named `role="link"` elements on one page are
// ambiguous, e.g. a group named "Members" beside the `ResourceMenu` "Members" link.

export const GroupsTabOpensSidePanelWithRoleSelectAndDelete: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Stakeholders" })).toBeInTheDocument());
    // Role (MultiSelectDropdown, not a plain badge) and Members
    // (count) columns render alongside Name, independent of opening the
    // row.
    await expect(canvas.getByRole("button", { name: "Stakeholders's roles" })).toHaveTextContent("Stakeholder");
    await expect(canvas.getByRole("cell", { name: "0 member(s)" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Stakeholders" }));

    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    // The SidePanel's own role editor is the same MultiSelectDropdown, kept
    // in sync with the Groups tab's row.
    await expect(within(panel).getByRole("button", { name: "Stakeholders's roles" })).toHaveTextContent("Stakeholder");
    // No group is specially protected from deletion; the only guard, C-U-08 (a project keeps at least one manager),
    // does not apply to this stakeholder-role group.
    await expect(within(panel).getByRole("button", { name: "Delete group" })).toBeEnabled();
  },
};

/** A group's role is granted or revoked after creation through the row's `MultiSelectDropdown`
 * (`POST`/`DELETE .../groups/{group_id}/roles`), as `ProjectMembersTable`'s Role column does for a user.
 * A group can hold several roles (checking a second does not uncheck the first). */
export const GroupsTabGrantAndRevokeGroupRole: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Stakeholders's roles" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Stakeholders's roles" }));
    const group = within(document.body).getByRole("group", { name: "Stakeholders's roles" });

    // Granting a second role alongside the one it already holds.
    const grantCheckbox = within(group).getByRole("checkbox", { name: "Grant Member to Stakeholders" });
    await userEvent.click(grantCheckbox);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/groups/g1/roles`, { role: "member" })
    );

    // Revoking its original role — independent of the grant above.
    const revokeCheckbox = within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Stakeholders" });
    await userEvent.click(revokeCheckbox);
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/groups/g1/roles/stakeholder`)
    );
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Stakeholders" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Stakeholders" }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });

    const userInput = within(panel).getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(userInput, "amy");
    // The panel's `UserAutocomplete` has no server search wired here, so this only confirms it renders inside the panel
    // (which also has a role `MultiSelectDropdown` and an org-group `<select>`, hence the specific input query); the add
    // flow is covered by `GroupsTabAddOrgGroupViaSidePanel` and `MembersTabAddDirectMember`.
    await expect(userInput).toHaveValue("amy");
    // With `organizationId` set the autocomplete arms a 250ms debounced search (`UserAutocomplete.tsx`). Closing the panel
    // unmounts it and runs the debounce cleanup (`cancelled = true; clearTimeout(timer)`) before the story ends, so no
    // live timer leaks into the next story.
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
    await waitFor(() => expect(canvas.getByRole("button", { name: "Stakeholders" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Stakeholders" }));
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

/** A group's delete goes through the Tier 1 `ConfirmDialog` (style guide "Pattern: confirmation, in two tiers") before the `DELETE` request. */
export const GroupsTabDeleteGroupRequiresConfirmation: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      groups: [
        { id: "g2", name: "Reviewers", roles: ["member"], member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [] },
      ],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Reviewers" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Reviewers" }));
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

// The `?openGroup=` deep link from Members to a group's members has no story: the `meta` `withRouter` decorator fixes one
// initial path and react-router refuses a nested second `<Router>`. The Playwright suite (`project-admin-members.spec.ts`,
// "?openGroup= deep link") covers the round trip.

// --- Members tab --------------
// `ProjectMembersTable` is fed by `GET /effective-members` (with provenance) and `GET /pending-invites`, merged client-side.
// `ProjectMembersTable.stories.tsx` covers the component; these stories confirm the page wiring (endpoints and callbacks).

const pendingInvitePending: PendingInvite = {
  id: "pi1", email: "waiting@example.com", role: "member", status: "pending",
  created_at: "2026-08-20T10:00:00Z", expires_at: "2026-09-03T10:00:00Z",
};

export const MembersTabShowsEffectiveMembersWithProvenance: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [
            { kind: "forward_inherited", role: "project_manager", via_project_id: "parent-1", via_project_name: "Platform", via_mode: "mirror_all", via_group_id: null, via_group_name: null },
          ],
          module_roles: [],
        },
        {
          user_id: "u2", display_name: "Sam Lee", email: "sam@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct_role", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
          module_roles: [],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByText("Priya Shah")).toBeInTheDocument());
    // The Source column shows a plain-language summary per row; Priya's sole source is `forward_inherited`, so her cell
    // reads "Group" and the "Inherited from 'Platform'" detail is in that cell's click-to-open popover.
    const priyaRow = canvas.getByText("Priya Shah").closest("tr")!;
    await userEvent.click(within(priyaRow).getByRole("button", { name: "Group" }));
    const detail = within(document.body).getByRole("dialog", { name: "Priya Shah's access sources" });
    await expect(within(detail).getByText(/Inherited from 'Platform'/)).toBeInTheDocument();

    await expect(canvas.getByText("Sam Lee")).toBeInTheDocument();
    const samRow = canvas.getByText("Sam Lee").closest("tr")!;
    await expect(within(samRow).getByText("Direct")).toBeInTheDocument();
  },
};

/** The Members section's "add a direct member" control is the shared `AddMembersModal` (staged multi-add); once committed it
 * grants a direct role via `POST .../roles`, unlike the Groups tab's add flow (group membership). "Add member" opens it in a
 * `Modal` (Principle 3). Each staged entry has its own role `<select>`, so the story checks the picker input and that the
 * commit button is disabled while nothing is staged. */
export const MembersTabAddDirectMember: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add member" })).toBeInTheDocument());

    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const dialog = body.getByRole("dialog", { name: "Add member" });
    // No server search is wired here: this confirms the control renders with nothing staged (commit button disabled).
    await expect(within(dialog).getByPlaceholderText("Type a name to add, or an email to invite…")).toBeInTheDocument();
    await expect(within(dialog).getByRole("button", { name: "Add member(s)" })).toBeDisabled();
  },
};

/** "Add member" opens the modal with the table still visible underneath; Cancel closes it without calling the API. */
export const MembersTabAddMemberModalOpen: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [{ kind: "direct_role", role: "project_manager", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
          module_roles: [],
        },
      ],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByText("Priya Shah")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const body = within(document.body);
    const dialog = body.getByRole("dialog", { name: "Add member" });
    // The table underneath stays visible — a layer, not a page reflow.
    await expect(canvas.getByText("Priya Shah")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  },
};

/** The "Add member" autocomplete also matches organisation groups by name (client-side, against `orgGroups`), with an
 * "Organisation group" badge. Picking one stages it; its role is set on the staged row, then the grant
 * (`POST .../group-roles`) fires on commit. */
export const MembersTabAddMemberAutocompleteMatchesGroup: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Add member" });

    await userEvent.type(within(dialog).getByPlaceholderText("Type a name to add, or an email to invite…"), "Eng");
    const groupOption = await within(dialog).findByRole("option", { name: /Engineering/ });
    await expect(groupOption).toHaveTextContent("Organisation group");
    await userEvent.click(groupOption);

    // Staged with the default role ("member") — change it on the staged
    // row itself before committing.
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Role for Engineering" }), "stakeholder");
    expect(api.post).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Add 1 member" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/group-roles`,
        { org_group_id: "og1", role: "stakeholder" },
      )
    );
    // Closes once every staged entry has committed successfully.
    await expect(within(document.body).queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();
  },
};

/** An organisation group with a direct `OrgGroupProjectRole` grant on this project is its own row in the Members table:
 * badge, editable role dropdown and a "Remove group" action (`MembersTabAddMemberAutocompleteMatchesGroup` covers the grant). */
export const MembersTabGroupRowRoleToggleAndRemove: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      groupRoles: [{ org_group_id: "og1", org_group_name: "Engineering", roles: ["stakeholder"] }],
    });
    spyOn(api, "post").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Engineering's roles" })).toBeInTheDocument());

    const row = canvas.getByRole("button", { name: "Engineering's roles" }).closest("tr")!;
    await expect(within(row).getByText("Group")).toBeInTheDocument();
    // The Source cell reads "Direct"; `ProjectMembersTable.stories.tsx`'s `GroupRow` story covers it.
    await expect(within(row).getByText("Direct")).toBeInTheDocument();

    // Granting a second role calls the same `POST .../group-roles` the
    // "Add member" autocomplete's own grant flow uses.
    await userEvent.click(within(row).getByRole("button", { name: "Engineering's roles" }));
    const roleGroup = within(document.body).getByRole("group", { name: "Engineering's roles" });
    await userEvent.click(within(roleGroup).getByRole("checkbox", { name: "Grant Member to Engineering" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/group-roles`,
        { org_group_id: "og1", role: "member" },
      )
    );

    // "Remove group" (Actions column) loops the per-role DELETE over every
    // role the group currently holds, behind a Tier-1 ConfirmDialog.
    await userEvent.click(within(row).getByRole("button", { name: "Engineering's actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Engineering's actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Remove group" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Remove Engineering from this project?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove group" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/group-roles/og1/stakeholder`)
    );
    await expect(within(document.body).getByText("Removed Engineering's access.")).toBeInTheDocument();
  },
};

/** The "Add member" autocomplete also matches this project's groups (client-side, against `memberTableGroups`) with a
 * "Project group" badge, distinct from "Organisation group" (one project vs organisation-wide). Picking one grants no role
 * (a project group's roles are separate grants); the modal moves to a second step, "add someone to this group",
 * using `POST .../groups/{group_id}/members`. */
export const MembersTabAddMemberAutocompleteMatchesProjectGroup: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const dialog = within(document.body).getByRole("dialog", { name: "Add member" });

    await userEvent.type(within(dialog).getByPlaceholderText("Type a name to add, or an email to invite…"), "Stake");
    const groupOption = await within(dialog).findByRole("option", { name: /Stakeholders/ });
    await expect(groupOption).toHaveTextContent("Project group");

    await userEvent.click(groupOption);
    // No grant call yet — the modal is now on its second step.
    expect(api.post).not.toHaveBeenCalled();
    const secondStepDialog = within(document.body).getByRole("dialog", { name: 'Add to "Stakeholders"' });

    await userEvent.type(
      within(secondStepDialog).getByPlaceholderText("Type a name to add, or an email to invite…"), "amy"
    );
    // No server search is wired here: this confirms the second step's control renders, as
    // `GroupsTabAddMemberViaSidePanel` does for the SidePanel.
    await expect(
      within(secondStepDialog).getByPlaceholderText("Type a name to add, or an email to invite…")
    ).toHaveValue("amy");

    // "Back" returns to the first step without adding anything.
    await userEvent.click(within(secondStepDialog).getByRole("button", { name: "Back" }));
    await expect(within(document.body).getByRole("dialog", { name: "Add member" })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  },
};

/** Unchecking a `direct_role` option calls `DELETE .../roles/{user}/{role}` and re-fetches `effective-members` only
 * (as `OrgAdminPage.tsx`'s `grantOrgRole`/`revokeOrgRole` do), not the whole `reload()`. */
export const MembersTabToggleDirectRoleOff: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Alex Morgan", email: "alex@example.com", effective_role: "stakeholder",
          // Two direct roles: the last remaining one is not clearable, so the member would otherwise vanish.
          sources: (["stakeholder", "member"] as const).map((role) => ({ kind: "direct_role" as const, role, via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null })),
          module_roles: [],
        },
      ],
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Alex Morgan" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/roles/u1/stakeholder`)
    );
  },
};

export const MembersTabPendingInviteResend: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ pendingInvites: [pendingInvitePending] });
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByText("waiting@example.com")).toBeInTheDocument());
    await expect(canvas.getByText("Pending")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Resend invite to waiting@example.com" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/pending-invites/pi1/resend`)
    );
    // Principle 7 — every mutation ends with feedback.
    await expect(within(document.body).getByText("Invite resent to waiting@example.com.")).toBeInTheDocument();
  },
};

/** Reports holds layouts, packs and placements only: no report-content editor or default template. */
export const ReportSetupTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Reports" }));
    await canvas.findByRole("treegrid", { name: "Reports, packs and tables" });
    await expect(canvas.queryByLabelText("Report type")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText("Default report template")).not.toBeInTheDocument();
  },
};

/** Reports lists the project's report layouts in one folder list, each opening in the designer. */
export const ReportSetupListsTheReportLayouts: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Reports" }));
    const grid = within(await canvas.findByRole("treegrid", { name: "Reports, packs and tables" }));
    await userEvent.click(grid.getByRole("button", { name: "Expand Custom reports" }));
    await expect(grid.getByRole("button", { name: /^Requirements by component/ })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "New" })).toBeInTheDocument();
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
    // Action types are inside the "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());
    const dialog = await openAddDialog(canvas, "New action type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Inspection");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
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
    // Action types are inside the "Fields & actions" tab.
    await userEvent.click(canvas.getByRole("link", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
  },
};

/** Pins `pluralize()`'s irregular plurals (`frontend/src/i18n/terminology.ts`) against the default English terminology: a naive
 * `+s` would render "Components & categorys". No `withTerminology` decorator, since the default-term path is under test. */
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
 * C-C-03: the custom-fields entity-kind dropdown and badge read "Requirement" / "Change request" through
 * `strings.admin.entityKindRequirement` / `entityKindChangeRequest` (`useStrings()`), so Terminology renames apply; the static
 * `CUSTOM_FIELD_ENTITY_KIND_LABEL` in `api/types.ts` cannot be terminology-aware.
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
    // The "New field" dialog's entity-kind <select> options.
    const dialog = await openAddDialog(canvas, "New field");
    await expect(dialog.getByRole("option", { name: "Spec" })).toBeInTheDocument();
    await expect(dialog.getByRole("option", { name: "ECR" })).toBeInTheDocument();
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

/** Member sources may be any same-organisation project, not only a direct child (docs/decisions.md), each shown with its mirror
 * mode as a badge. The section is on the Groups tab as type-badged rows in the `DirectoryTable` with `ProjectGroup` rows
 * (`GroupsTabShowsGroupsAndMemberSourcesTogether`); this story covers the add-a-source flow. */
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
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByRole("cell", { name: "Authentication" })).toBeInTheDocument());
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

/** The Groups tab's `DirectoryTable` mixes a `ProjectGroup` row and a `ProjectMemberSource` row, each with a "Type" badge
 * ("Project group" vs "Project": a source names another project whose members this one mirrors;
 * docs/ux-style-guide.md "Pattern: type-badged mixed rows in a single directory"). A member-source row is read-only detail
 * (its mode and a Remove action) and does not open a `SidePanel`. */
export const GroupsTabShowsGroupsAndMemberSourcesTogether: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      groups: [
        { id: "g1", name: "Stakeholders", roles: ["stakeholder"], member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [] },
      ],
      memberSources: [
        { source_project_id: "sibling-1", source_project_name: "Authentication", mirror_mode: "mirror_all", mirror_filter_role: null },
      ],
      orgProjects: [buildProjectListItem({ id: "sibling-1", name: "Authentication", organization_id: "org-1" })],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Project groups" }));

    const groupRow = (await canvas.findByRole("cell", { name: "Stakeholders" })).closest("tr")!;
    await expect(within(groupRow).getByText("Project group")).toBeInTheDocument();

    const sourceRow = canvas.getByRole("cell", { name: "Authentication" }).closest("tr")!;
    await expect(within(sourceRow).getByText("Project")).toBeInTheDocument();
    await expect(within(sourceRow).getByText("Mirror all roles")).toBeInTheDocument();
    // Read-only: a Remove action, not the real group's "click to open" panel.
    await expect(within(sourceRow).getByRole("button", { name: "Remove" })).toBeInTheDocument();

    const deleteSpy = spyOn(api, "delete").mockResolvedValue(undefined);
    await userEvent.click(within(sourceRow).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(deleteSpy).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/member-sources/sibling-1`)
    );
  },
};

/** A project group's members can be "the direct members of another project" (`ProjectGroupMember.source_project_id`,
 * docs/decisions.md), alongside users and nested {@link OrgGroup}s. The labelled line, inside the group's `SidePanel`, links to
 * that project's Members page with a hint that the list is live, not fixed. */
export const ProjectGroupCanReferenceAnotherProjectsMembers: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      groups: [
        {
          id: "g1", name: "Stakeholders", roles: ["stakeholder"],
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
    await userEvent.click(canvas.getByRole("button", { name: "Stakeholders" }));
    const panel = within(document.body).getByRole("dialog", { name: "Stakeholders details" });
    await waitFor(() => expect(within(panel).getByText("Authentication's members")).toBeInTheDocument());
    // The link to that project's own Members page, plus the
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

/** The members table is searchable through `FilterPanel`'s search box (as Org Admin's Users table);
 * `ProjectMembersTable.stories.tsx`'s `SearchNarrowed` covers the component, this story the page wiring of `effectiveMembers`. */
export const MembersTabSearchFilters: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [{ kind: "direct_role", role: "project_manager", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
          module_roles: [],
        },
        {
          user_id: "u2", display_name: "Sam Lee", email: "sam@example.com", effective_role: "stakeholder",
          sources: [{ kind: "direct_role", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
          module_roles: [],
        },
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByText("Priya Shah")).toBeInTheDocument());
    await expect(canvas.getByText("Sam Lee")).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Search by name or email"), "sam");
    await expect(canvas.getByText("Sam Lee")).toBeInTheDocument();
    await expect(canvas.queryByText("Priya Shah")).not.toBeInTheDocument();
  },
};

export const MaterializeButtonConvertsInheritedAccess: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      effectiveMembers: [
        {
          user_id: "u1", display_name: "Priya Shah", email: "priya@example.com", effective_role: "project_manager",
          sources: [
            { kind: "forward_inherited", role: "project_manager", via_project_id: "parent-1", via_project_name: "Platform", via_mode: "mirror_all", via_group_id: null, via_group_name: null },
          ],
          module_roles: [],
        },
      ],
    });
    spyOn(api, "post").mockResolvedValue({ created: [{ user_id: "u1", role: "project_manager" }], skipped: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Members" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Convert all inherited access to direct roles" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Convert all inherited access to direct roles" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/materialize-inherited-access`));
    await waitFor(() => expect(within(document.body).getByText("Converted 1 user to direct roles.")).toBeInTheDocument());
  },
};

/** "Add sub-project" opens ProjectListPage with the parent pre-filled instead of duplicating the create modal; it is offered
 * only once the project is a parent (can_be_parent; see AddSubProjectDisabledUntilEligible). */
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

/** With more than one project to switch between, a chevron next
 * to the project name opens a popover listing the others as plain links
 * to their own Project Admin page. */
export const EntitySwitcherOffersSiblingProjects: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      orgProjects: [
        buildProjectListItem({ id: PROJECT_ID, name: "Atlas Platform" }),
        buildProjectListItem({ id: "project-2", name: "Solstice Programme" }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "Atlas Platform" })).toBeInTheDocument());

    const trigger = await canvas.findByRole("button", { name: "Switch project" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch project" });
    await expect(within(dialog).getByRole("link", { name: "Solstice Programme" })).toHaveAttribute(
      "href",
      "/projects/project-2/admin"
    );
  },
};

// --- Modules tab ---------------------------

const usingOrgDefaultModule: ProjectModuleEnablement = {
  module_key: "fake_module", name: "Fake Module", effective_enabled: true,
  org_default_enabled: true, org_hard_enabled: true, has_project_override: false, project_override_enabled: null,
};
const overriddenModule: ProjectModuleEnablement = {
  module_key: "context_strategy", name: "Context & Strategy", effective_enabled: false,
  org_default_enabled: true, org_hard_enabled: true, has_project_override: true, project_override_enabled: false,
};
const usingOrgDefaultSubComponent: ProjectModuleSubComponent = {
  module_key: "context_strategy", subcomponent_key: "pain_point", name: "Pain Point",
  effective_enabled: true, org_default_enabled: true, org_hard_enabled: true, has_project_override: true, project_override_enabled: true,
};
const overriddenSubComponent: ProjectModuleSubComponent = {
  module_key: "context_strategy", subcomponent_key: "strategy", name: "Strategy",
  effective_enabled: false, org_default_enabled: true, org_hard_enabled: true, has_project_override: true, project_override_enabled: false,
};

/** The Tags group shows the project's tag vocabulary; where a tag is used opens from its record count. */
export const TagsGroupShowsTheVocabularyAndUsage: Story = {
  beforeEach: () => mockProjectAdminApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Tags" }));
    await expect(await canvas.findByRole("table", { name: "Tags" })).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Who can add a new tag" })).toHaveValue("free");
    await expect(canvas.queryByRole("table", { name: /Where tags are used/ })).not.toBeInTheDocument();
  },
};

/** One switch per module; a module whose value differs from the org's
 * default for new projects says so in a hint. Sub-components start
 * collapsed behind a summary and expand to their own switches. */
export const ModulesTabShowsStateAndCollapsedSubComponents: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      projectModules: [usingOrgDefaultModule, { ...overriddenModule, effective_enabled: true, project_override_enabled: true, org_default_enabled: false }],
      projectModuleSubComponents: { context_strategy: [overriddenSubComponent, usingOrgDefaultSubComponent] },
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    await expect(canvas.getByRole("switch", { name: "Enable Fake Module for this project" })).toBeChecked();
    await expect(canvas.getByRole("switch", { name: "Enable Context & Strategy for this project" })).toBeChecked();
    await expect(canvas.getByText("Organisation default for new projects: off")).toBeInTheDocument();

    await expect(canvas.queryByText("Strategy")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "2 components · 1 on" }));
    await expect(canvas.getByRole("switch", { name: "Enable Strategy (Context & Strategy) for this project" })).not.toBeChecked();
    await expect(canvas.getByRole("switch", { name: "Enable Pain Point (Context & Strategy) for this project" })).toBeChecked();
  },
};

/** Toggling a module's effective enablement calls `PUT .../enablement`, patches local state from the response and toasts
 * the change (as Org Admin's module toggle one tier up). */
export const ModulesTabToggleWholeModule: Story = {
  beforeEach: () => {
    mockProjectAdminApis({ projectModules: [usingOrgDefaultModule] });
    spyOn(api, "put").mockResolvedValue({ ...usingOrgDefaultModule, effective_enabled: false, has_project_override: true, project_override_enabled: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Fake Module")).toBeInTheDocument());

    const toggle = canvas.getByRole("switch", { name: "Enable Fake Module for this project" });
    await userEvent.click(toggle);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/modules/fake_module/enablement`, { enabled: false },
      )
    );
    await expect(within(document.body).getByText("Fake Module disabled for this project")).toBeInTheDocument();
  },
};

/** No registered modules: the tab shows its empty message, not a blank list. */
export const ModulesTabEmptyShowsMessage: Story = {
  beforeEach: () => mockProjectAdminApis({ projectModules: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("No modules are registered on this deployment yet.")).toBeInTheDocument());
    await expect(canvas.queryByRole("switch")).not.toBeInTheDocument();
  },
};

/** Toggling one sub-component override calls its own `PUT .../subcomponents/{key}`, independent of the parent module's toggle. */
export const ModulesTabToggleSubComponent: Story = {
  beforeEach: () => {
    mockProjectAdminApis({
      projectModules: [{ ...overriddenModule, effective_enabled: true, has_project_override: false, project_override_enabled: null }],
      projectModuleSubComponents: { context_strategy: [usingOrgDefaultSubComponent] },
    });
    spyOn(api, "put").mockResolvedValue({
      ...usingOrgDefaultSubComponent, effective_enabled: false, has_project_override: true, project_override_enabled: false,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await waitFor(() => expect(canvas.getByText("Context & Strategy")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "1 component · all on" }));

    const toggle = canvas.getByRole("switch", { name: "Enable Pain Point (Context & Strategy) for this project" });
    await userEvent.click(toggle);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/subcomponents/pain_point`, { enabled: false },
      )
    );
    await expect(within(document.body).getByText("Pain Point disabled for this project")).toBeInTheDocument();
  },
};

/** A module's organisation-only sub-component (Product Feedback's request inbox) is not in the project's list, so
 * the module shows only its project-level switches. */
export const ModulesTabOmitsOrganisationOnlySubComponent: Story = {
  beforeEach: () => {
    const projectLevel = (key: string, name: string): ProjectModuleSubComponent => ({
      module_key: "product_feedback", subcomponent_key: key, name,
      effective_enabled: true, org_default_enabled: true, org_hard_enabled: true, has_project_override: false, project_override_enabled: null,
    });
    mockProjectAdminApis({
      projectModules: [{
        module_key: "product_feedback", name: "Product Feedback", effective_enabled: true,
        org_default_enabled: true, org_hard_enabled: true, has_project_override: false, project_override_enabled: null,
      }],
      projectModuleSubComponents: {
        product_feedback: [projectLevel("enhancement_request", "Enhancement requests"), projectLevel("external_references", "External references")],
      },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("link", { name: "Modules" }));
    await userEvent.click(await canvas.findByRole("button", { name: "2 components · all on" }));
    await expect(canvas.getByRole("switch", { name: "Enable Enhancement requests (Product Feedback) for this project" })).toBeChecked();
    await expect(canvas.queryByText("Organisation-level request inbox")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "dark" } };


/** Project-level link types live in Fields & actions: the organisation's types are listed read-only with a
 * Hide control, and this project's own types are added in the same row the organisation uses. */
export const FieldsAndActionsShowsLinkTypes: Story = {
  beforeEach: () =>
    mockProjectAdminApis({
      linkTypes: [
        buildProjectLinkType({ id: "lt-related", forward_name: "Related to", reverse_name: "Related to" }),
        buildProjectLinkType({
          id: "lt-own", forward_name: "Verifies", reverse_name: "Is verified by", scope: "project", owner_project_id: PROJECT_ID, editable: true,
        }),
      ],
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("link", { name: "Fields & actions" }));
    const available = within(await canvas.findByRole("region", { name: "Available to this project" }));
    await expect(available.getByRole("button", { name: "Hide Related to in this project" })).toBeInTheDocument();
    const own = within(canvas.getByRole("region", { name: "Link types of this project" }));
    await expect(own.getByDisplayValue("Verifies")).toBeInTheDocument();
    await expect(own.getByRole("button", { name: "New link type" })).toBeInTheDocument();
  },
};
