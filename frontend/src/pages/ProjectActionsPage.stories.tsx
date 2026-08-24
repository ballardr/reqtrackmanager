import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, OrgUser, RequirementAction } from "../api/types";
import { buildActionType, buildRequirementAction, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ProjectActionsPage } from "./ProjectActionsPage";

const PROJECT_ID = "project-1";

const actionTypes: ActionTypeDefinition[] = [
  buildActionType({ id: "at1", name: "Review" }),
  buildActionType({ id: "at2", name: "Test" }),
];
const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
};
const actions: RequirementAction[] = [
  buildRequirementAction({ id: "act1", unique_code: "ACT-001", title: "Review password reset flow", action_type_id: "at1", outcome_status: "pending" }),
  buildRequirementAction({ id: "act2", unique_code: "ACT-002", title: "Test 2FA enrolment", action_type_id: "at2", outcome_status: "completed", assignee_id: null }),
];

function mockProjectActionsApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/action-types")) return actionTypes;
    if (path.includes("/actions")) return actions;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.includes("/users")) return [orgUser];
    throw new Error(`unmocked path: ${path}`);
  });
}

const meta: Meta<typeof ProjectActionsPage> = {
  title: "Pages/ProjectActionsPage",
  component: ProjectActionsPage,
  decorators: [withStatefulAuth(buildUser()), withRouter(`/projects/${PROJECT_ID}/actions`, "/projects/:projectId/actions"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectActionsPage>;

export const ListWithFilters: Story = {
  beforeEach: () => mockProjectActionsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    await expect(canvas.getByText("Test 2FA enrolment")).toBeInTheDocument();
    // "Pending"/"Completed" also appear as <option>s in the Outcome filter
    // select, so these assertions are scoped to the results table.
    const table = within(canvas.getByRole("table"));
    await expect(table.getByText("Pending")).toBeInTheDocument();
    await expect(table.getByText("Completed")).toBeInTheDocument();
  },
};

/** The outcome badge in the results table doubles as a filter shortcut —
 * `FilterBadge`, the same component `RequirementsPage`'s status badge uses
 * (style guide "Every badge that names a filterable value is a `FilterBadge`,
 * not a plain `.badge`"). Clicking it sets the Outcome filter in the side
 * panel to match. */
export const FilterByOutcomeBadge: Story = {
  beforeEach: () => mockProjectActionsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    const table = within(canvas.getByRole("table"));
    await userEvent.click(table.getByText("Pending"));
    const outcomeSelect = canvas.getByLabelText("Outcome");
    await expect(outcomeSelect).toHaveValue("pending");
  },
};

export const CreateNewAction: Story = {
  beforeEach: () => {
    mockProjectActionsApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New action/ }));
    await userEvent.type(canvas.getByPlaceholderText("Title"), "Verify audit log retention");
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/actions`,
        expect.objectContaining({ title: "Verify audit log retention", action_type_id: "at1" })
      )
    );
    // Principle 7 — every mutation ends with feedback. The 2026-08 UX audit
    // named this page specifically: it got real interaction-model work
    // without picking up Toast, so create still just silently re-rendered.
    await expect(within(document.body).getByText("Action created")).toBeInTheDocument();
  },
};

/** Column-header sorting (2026-08 UX audit roadmap) — this list has no
 * backend pagination, so sorting is a client-side `useMemo` over the
 * already-loaded rows. Clicking "Title" once sorts ascending. */
export const SortedByTitleAscending: Story = {
  beforeEach: () => mockProjectActionsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Title" }));
    const rows = within(canvas.getByRole("table")).getAllByRole("row").slice(1);
    // "Review password reset flow" < "Test 2FA enrolment" alphabetically.
    await expect(within(rows[0]).getByText("Review password reset flow")).toBeInTheDocument();
    await expect(within(rows[1]).getByText("Test 2FA enrolment")).toBeInTheDocument();
    const th = canvas.getByRole("button", { name: "Title" }).closest("th");
    await expect(th).toHaveAttribute("aria-sort", "ascending");
  },
};

export const EmptyState: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/action-types")) return actionTypes;
      if (path.includes("/actions")) return [];
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
      if (path.includes("/users")) return [];
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No actions to show.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListWithFilters, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListWithFilters, globals: { theme: "dark" } };
