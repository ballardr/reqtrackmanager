import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Category, Component, ProjectStage } from "../api/types";
import { buildChangeRequest, buildRequirement, buildUser, withRouter, withStatefulAuth, withTerminology, withToast } from "../testing/storybook-helpers";
import { ChangeRequestsPage } from "./ChangeRequestsPage";

const PROJECT_ID = "project-1";

const components: Component[] = [{ id: "c1", project_id: PROJECT_ID, name: "Authentication", prefix: "AUTH", sort_order: 0 }];
const categories: Category[] = [{ id: "cat1", project_id: PROJECT_ID, component_id: "c1", name: "Login", prefix: "LOG", sort_order: 0 }];
const stages: ProjectStage[] = [
  { id: "s1", project_id: PROJECT_ID, name: "Build", status: "scoping", sort_order: 0, is_current: true, approved_at: null, completed_at: null, completed_by: null, review_deadline: null },
];
// "approved" (locked): a modify change request can only target an
// already-locked requirement (2026-08 UX audit roadmap, "No requirement
// approval action; change requests can target draft requirements") — a
// still-draft one wouldn't appear in the "Select a requirement" dropdown at
// all, which would break every story below that exercises the
// modify-requirement form.
const requirement = buildRequirement({
  id: "req-1", unique_code: "AUTH-LOG-001", name: "Reset password", component_id: "c1", category_id: "cat1",
  target_stage_id: "s1", reasoning: "Locked-out users need a self-service recovery path.", status: "approved",
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
    withToast(),
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
/** The create form is a `Modal` (style guide "Pattern: modal dialog for
 * entity create/rename") — a layer portalled to `document.body`, not an
 * inline block inside `canvasElement`, so its fields are queried via
 * `within(document.body)` rather than `canvas`. */
export const ModifyRequirementFieldTogglePrefills: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    // Untoggled: no editor for Reasoning is rendered at all.
    await expect(within(dialog).queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).getByDisplayValue(requirement.reasoning)).toBeInTheDocument();
    // Untick again: the editor (and its value) disappears.
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).queryByDisplayValue(requirement.reasoning)).not.toBeInTheDocument();
  },
};

export const ModifyRequirementCreateDisabledUntilFieldSelected: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    await userEvent.type(within(dialog).getByPlaceholderText("Reason for change"), "Extend the recovery window");
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
    await expect(within(dialog).getByText("Select at least one field to change.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await expect(within(dialog).getByRole("button", { name: "Create" })).toBeEnabled();
  },
};

/** Switching to "New requirement" replaces the field-toggle form with a
 * plain create form — no existing requirement to diff against. */
export const NewRequirementKindShowsPlainCreateForm: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Modify requirement")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("radio", { name: "New requirement" }));
    await expect(within(dialog).getByPlaceholderText("Proposed name")).toBeInTheDocument();
    await expect(within(dialog).queryByText("Fields to change")).not.toBeInTheDocument();
  },
};

/** Column-header sorting (2026-08 UX audit roadmap) — this list is backend-
 * paginated (`PAGE_SIZE`/`LoadMoreButton`), so a header click has to refetch
 * with `sort`/`order` query params rather than reordering just the loaded
 * page. Switch to list view first — sorting only applies there. */
export const SortByCreatedRefetchesWithSortParams: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await userEvent.click(canvas.getByRole("button", { name: "Created" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=created_at&order=asc"))
    );
    const th = canvas.getByRole("button", { name: "Created" }).closest("th");
    await expect(th).toHaveAttribute("aria-sort", "ascending");

    await userEvent.click(canvas.getByRole("button", { name: "Created" }));
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("sort=created_at&order=desc"))
    );
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
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() => expect(within(dialog).getByText("Fields to change")).toBeInTheDocument());
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Reasoning" }));
    await userEvent.type(within(dialog).getByPlaceholderText("Reason for change"), "Extend the recovery window");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/change-requests`,
        expect.objectContaining({ kind: "modify_requirement", changed_fields: ["reasoning"] })
      )
    );
    // Principle 7 — every mutation ends with feedback (sixth-pass audit:
    // this page previously just silently re-rendered the list).
    await expect(within(document.body).getByText("Change request created")).toBeInTheDocument();
    // The Modal closes itself on a successful create (`setShowForm(false)`).
    await expect(dialog).not.toBeInTheDocument();
  },
};

/** Tri-state status filter (2026-08 UX audit roadmap, "Default Change
 * Requests to an active-only status filter"): the page loads with "Active"
 * selected and sends `active_only=true` (no `cr_status`), hiding a
 * terminal-status change request; switching to "All statuses" sends
 * neither param and reveals it. */
export const StatusFilterDefaultsToActiveAndWidensToAll: Story = {
  beforeEach: () => {
    mockChangeRequestsListApis();
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      if (path.includes("active_only=true")) {
        return {
          items: [buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" })],
          total: 1,
        };
      }
      return {
        items: [
          buildChangeRequest({ id: "cr1", requirement_id: "req-1", status: "submitted", proposed_target_stage_id: "s1" }),
          buildChangeRequest({ id: "cr3", requirement_id: "req-1", kind: "new_requirement", status: "approved", proposed_name: "Approved CR" }),
        ],
        total: 2,
      };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.getPage).toHaveBeenCalledWith(expect.stringContaining("active_only=true")));
    const statusSelect = canvas.getByLabelText("Status");
    await expect(statusSelect).toHaveValue("active");
    await expect(canvas.queryByText("Approved CR")).not.toBeInTheDocument();

    await userEvent.selectOptions(statusSelect, "");
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.not.stringContaining("active_only"))
    );
    await waitFor(() => expect(canvas.getByText("Approved CR")).toBeInTheDocument());
  },
};

/** Filter select options render the existing `CHANGE_REQUEST_STATUS_LABEL`
 * map (2026-08 UX audit roadmap, "Fix raw-enum filter/table text"), not the
 * raw backend enum string — "In review", not "in_review". */
export const StatusFilterOptionsUseLabelMap: Story = {
  beforeEach: () => mockChangeRequestsListApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Reset password" })).toBeInTheDocument());
    const statusSelect = canvas.getByLabelText("Status") as HTMLSelectElement;
    const optionLabels = Array.from(statusSelect.options).map((o) => o.textContent);
    await expect(optionLabels).toContain("In review");
    await expect(optionLabels).not.toContain("in_review");
  },
};

/**
 * A modify change request can only target an already-locked (approved/
 * completed) requirement (2026-08 UX audit roadmap, "No requirement
 * approval action; change requests can target draft requirements") — a
 * still-draft one doesn't appear in the "Select a requirement" dropdown at
 * all, and a hint explains why rather than showing a silently empty select.
 */
export const NoLockableRequirementsShowsHint: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/requirements")) return [buildRequirement({ id: "req-draft", status: "draft" })];
      if (path.includes("/components")) return components;
      if (path.includes("/categories")) return categories;
      if (path.includes("custom-fields")) return [];
      if (path.includes("/stages")) return stages;
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
      if (path.includes("/users")) return [];
      if (path.includes("/resources")) return [];
      throw new Error(`unmocked path: ${path}`);
    });
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New change request" });
    await waitFor(() =>
      expect(within(dialog).getByText("No requirements are approved yet — approve one first, or edit a draft requirement directly.")).toBeInTheDocument()
    );
    const requirementSelect = within(dialog).getByLabelText("Select a requirement") as HTMLSelectElement;
    await expect(requirementSelect.options).toHaveLength(0);
  },
};

export const LightTheme: Story = { ...ListOfChangeRequests, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListOfChangeRequests, globals: { theme: "dark" } };
