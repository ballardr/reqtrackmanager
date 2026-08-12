import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Category, Component, ProjectStage } from "../api/types";
import { buildChangeRequest, buildRequirement, buildUser, withRouter, withStatefulAuth, withTerminology } from "../testing/storybook-helpers";
import { ChangeRequestsPage } from "./ChangeRequestsPage";

const PROJECT_ID = "project-1";

const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Build", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];
const requirement = buildRequirement({
  id: "req-1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1",
  target_stage_id: "s1", reasoning: "Locked-out users need a self-service recovery path.",
});

function mockChangeRequestsListApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/requirements")) return [requirement];
    if (path.includes("/components")) return components;
    if (path.includes("/categories")) return categories;
    if (path.includes("custom-fields")) return [];
    if (path.includes("/stages")) return stages;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [];
    if (path.includes("/resources")) return [];
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockResolvedValue({
    items: [
      buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" }),
      buildChangeRequest({ id: "cr2", requirement_id: "req-1", kind: "new_requirement", status: "draft", proposed_name: "Add SSO login" }),
    ],
    total: 2,
  });
}

const meta: Meta<typeof ChangeRequestsPage> = {
  title: "Pages/ChangeRequestsPage",
  component: ChangeRequestsPage,
  decorators: [
    withStatefulAuth(buildUser({ id: "user-1" })),
    withTerminology(),
    withRouter(`/projects/${PROJECT_ID}/change-requests`, "/projects/:projectId/change-requests"),
  ],
};
export default meta;

type Story = StoryObj<typeof ChangeRequestsPage>;

export const ListOfChangeRequests: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Add SSO login" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No change requests to show.")).toBeInTheDocument());
  },
};

/**
 * The core documented behaviour (help/03-change-requests.md): ticking a
 * field's checkbox pre-fills its editor from the selected requirement's
 * CURRENT value — nothing is shown, let alone submitted, for an untouched
 * field.
 */
export const ModifyRequirementFieldTogglePrefills: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByText("Fields to change")).toBeInTheDocument());
    // Untoggled: no editor for Reasoning is rendered at all.
    await expect(canvas.queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Reasoning" }));
    await expect(canvas.getByDisplayValue(requirement.reasoning)).toBeInTheDocument();
    // Untick again: the editor (and its value) disappears.
    await userEvent.click(canvas.getByRole("checkbox", { name: "Reasoning" }));
    await expect(canvas.queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
  },
};

export const ModifyRequirementCreateDisabledUntilFieldSelected: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByText("Fields to change")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("Reason for change"), "Extend the recovery window");
    await expect(canvas.getByRole("button", { name: "Create" })).toBeDisabled();
    await expect(canvas.getByText("Select at least one field to change.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Reasoning" }));
    await expect(canvas.getByRole("button", { name: "Create" })).toBeEnabled();
  },
};

/** Switching to "New requirement" replaces the field-toggle form with a
 * plain create form — no existing requirement to diff against. */
export const NewRequirementKindShowsPlainCreateForm: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByText("Modify requirement")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("radio", { name: "New requirement" }));
    await expect(canvas.getByPlaceholderText("Proposed name")).toBeInTheDocument();
    await expect(canvas.queryByText("Fields to change")).not.toBeInTheDocument();
  },
};

export const SubmitCreatesChangeRequest: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    await waitFor(() => expect(canvas.getByText("Fields to change")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("checkbox", { name: "Reasoning" }));
    await userEvent.type(canvas.getByPlaceholderText("Reason for change"), "Extend the recovery window");
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({ kind: "modify_requirement", changed_fields: ["reasoning"] })
      )
    );
  },
};

export const LightTheme: Story = { ...ListOfChangeRequests, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListOfChangeRequests, globals: { theme: "dark" } };
