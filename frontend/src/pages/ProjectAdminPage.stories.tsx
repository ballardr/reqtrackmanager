import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, Category, Component, CustomFieldDefinition, OrgGroup, ProjectGroup, ProjectStage, ProjectStatusDefinition } from "../api/types";
import { buildActionType, buildProject, buildProjectStatus, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ProjectAdminPage } from "./ProjectAdminPage";

const PROJECT_ID = "project-1";

const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Scoping", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];
const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const groups: ProjectGroup[] = [
  { id: "g1", name: "Stakeholders", role: "stakeholder", is_default: true, member_user_ids: [], member_org_group_ids: [] },
];
const orgGroups: OrgGroup[] = [
  { id: "og1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null },
];
const projectStatuses: ProjectStatusDefinition[] = [
  buildProjectStatus({ id: "st1", name: "Proposed", sort_order: 0 }),
  buildProjectStatus({ id: "st2", name: "Active", sort_order: 1 }),
];

function mockProjectAdminApis(overrides: { actionTypes?: ActionTypeDefinition[]; customFields?: CustomFieldDefinition[] } = {}) {
  const actionTypes = overrides.actionTypes ?? [buildActionType({ id: "at1", name: "Review", sort_order: 0 }), buildActionType({ id: "at2", name: "Test", sort_order: 1 })];
  const customFields = overrides.customFields ?? [];
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform", status_id: "st1" });
    if (path.includes("/stages")) return stages;
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return categories;
    if (path.includes("/action-types")) return actionTypes;
    if (path.includes("/project-statuses")) return projectStatuses;
    // Checked before the plain "/groups" check below — /orgs/{id}/groups
    // also contains that substring, and returns a differently-shaped
    // OrgGroup[] (project groups vs. org groups).
    if (path.includes("/orgs/") && path.includes("/groups")) return orgGroups;
    if (path.includes("/groups")) return groups;
    if (path.includes("/custom-fields")) return customFields;
    if (path.includes("/report-config")) return {
      intro: "", chapters: [], appendices: [],
      intro_is_organisation_default: false, chapters_is_organisation_default: false, appendices_is_organisation_default: false,
      default_report_template_id: null,
    };
    if (path.includes("/report-templates")) return [];
    if (path.includes("/users")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ProjectAdminPage> = {
  title: "Pages/ProjectAdminPage",
  component: ProjectAdminPage,
  decorators: [
    withStatefulAuth(buildUser()),
    withRouter(`/projects/${PROJECT_ID}/admin`, "/projects/:projectId/admin"),
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
    await userEvent.click(canvas.getByRole("tab", { name: "Structure" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Structure" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Structure" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Fields & actions" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Fields & actions" }));
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

/** Style guide "Pattern: create panels, popovers, and one door for bulk":
 * "+ New group" opens a small popover instead of the Groups tab having no
 * create form at all (2026-08 UX audit finding) — mirrors OrgAdminPage's
 * own "New group" popover, just against the project-scoped endpoint, which
 * also requires a role up front (`ProjectGroupCreate.role`) since a
 * project group's role can't be changed after creation. */
export const GroupsTabCreateGroupViaPopover: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Project groups" }));
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

export const GroupsTabAddMember: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByText("Stakeholders")).toBeInTheDocument());
    await expect(canvas.getByText("Stakeholder")).toBeInTheDocument();
  },
};

export const GroupsTabAddOrgGroup: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByText("Stakeholders")).toBeInTheDocument());
    // `getAllByRole` + a tag filter: `UserAutocomplete`'s own text input in
    // the same tab is also `role="combobox"` (WAI-ARIA combobox pattern),
    // so a bare `getByRole("combobox")` is ambiguous here.
    const select = canvas.getAllByRole("combobox").find((el) => el.tagName === "SELECT")!;
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

export const ReportSetupTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Report Setup" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Fields & actions" }));
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
    await userEvent.click(canvas.getByRole("tab", { name: "Fields & actions" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
  },
};

export const LightTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "dark" } };
