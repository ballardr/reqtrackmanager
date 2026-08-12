import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Category, Component, ProjectGroup, ProjectStage } from "../api/types";
import { buildProject, buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
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

function mockProjectAdminApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return buildProject({ id: PROJECT_ID, organization_id: "org-1", name: "Atlas Platform" });
    if (path.includes("/stages")) return stages;
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return categories;
    if (path.includes("/groups")) return groups;
    if (path.includes("/custom-fields")) return [];
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
  decorators: [withStatefulAuth(buildUser()), withRouter(`/projects/${PROJECT_ID}/admin`, "/projects/:projectId/admin")],
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

export const TerminologyTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Terminology" }));
    await waitFor(() => expect(canvas.getByPlaceholderText("requirement")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("requirement"), "story");
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
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
    await userEvent.click(canvas.getByRole("button", { name: "Project stages" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Start review" })).toBeInTheDocument());
    // Deleting the only stage is blocked — there's nothing else to reassign to.
    await expect(canvas.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
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
    await userEvent.click(canvas.getByRole("button", { name: "Categories" }));
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
    await userEvent.click(canvas.getByRole("button", { name: "Categories" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: /New category/ })).toBeInTheDocument());
    // Two "Name"/"Prefix"-placeholder inputs exist on this tab: the
    // per-component "add category" row (first, inside the component's own
    // block) and the "add component" row at the very bottom (last).
    const [nameInput] = canvas.getAllByPlaceholderText("Name");
    const [prefixInput] = canvas.getAllByPlaceholderText("Prefix");
    await userEvent.type(nameInput, "Sessions");
    await userEvent.type(prefixInput, "SES");
    await userEvent.click(canvas.getByRole("button", { name: /New category/ }));
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
    await userEvent.click(canvas.getByRole("button", { name: "Custom fields" }));
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

export const GroupsTabAddMember: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Project groups" }));
    await waitFor(() => expect(canvas.getByText("Stakeholders")).toBeInTheDocument());
    await expect(canvas.getByText("Stakeholder")).toBeInTheDocument();
  },
};

export const ReportSetupTab: Story = {
  beforeEach: () => {
    mockProjectAdminApis();
    spyOn(api, "put").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report Setup" }));
    await waitFor(() => expect(canvas.getByText("Project intro")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/report-config`, expect.any(Object)));
  },
};

export const LightTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OverviewTabSaveSettings, globals: { theme: "dark" } };
