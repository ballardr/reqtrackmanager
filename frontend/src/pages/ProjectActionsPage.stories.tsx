import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ActionTypeDefinition, OrgUser, RequirementAction } from "../api/types";
import { buildRecordColumns } from "../testing/recordTablesFixtures";
import { buildActionType, buildRequirementAction, buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ProjectActionsPage } from "./ProjectActionsPage";
import { openListMenu, chooseExport } from "../testing/listActionsMenu";

const PROJECT_ID = "project-1";

const actionTypes: ActionTypeDefinition[] = [
  buildActionType({ id: "at1", name: "Review" }),
  buildActionType({ id: "at2", name: "Test" }),
];
const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
};
const orgGroups = [
  { id: "group-2", name: "Test Group", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const actions: RequirementAction[] = [
  buildRequirementAction({ id: "act1", unique_code: "ACT-001", title: "Review password reset flow", action_type_id: "at1", outcome_status: "pending",
    assignee: { type: "org_group", id: "group-1", label: "QA Team", member_count: 3, exists: true },
  }),
  buildRequirementAction({ id: "act2", unique_code: "ACT-002", title: "Test 2FA enrolment", action_type_id: "at2", outcome_status: "completed", assignee: null }),
];

function mockProjectActionsApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/requirement_action/columns")) return buildRecordColumns({ label: "Actions" });
    if (path.includes("/action-types")) return actionTypes;
    if (path.includes("/actions")) return actions;
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
    if (path.endsWith("/orgs/org-1/groups")) return orgGroups as never;
    if (path.endsWith(`/projects/${PROJECT_ID}/groups`)) return [] as never;
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
    // A group assignee shows its name, kind and member count rather than a person's name.
    await expect(table.getByText("QA Team")).toBeInTheDocument();
    await expect(table.getByText("Org group · 3 members")).toBeInTheDocument();
  },
};

/** The shared list actions: Export downloads the list with the page's filters, Import opens a file picker. */
export const ExportAndImportAreOnTheTitleRow: Story = {
  beforeEach: () => {
    mockProjectActionsApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code,title\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/records/requirement_action/export"));
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

/** A slow, stale response must not overwrite a newer one: the initial
 * (active-only) load resolves *after* the "Include archived" reload, and
 * the archived row must still be shown. */
export const StaleResponseIsIgnored: Story = {
  beforeEach: () => {
    const archived = buildRequirementAction({ id: "act3", unique_code: "ACT-003", title: "Archived action", is_archived: true });
    let releaseFirst: () => void = () => {};
    const firstLoad = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let actionLoads = 0;
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/action-types")) return actionTypes;
      if (path.includes("/actions")) {
        actionLoads += 1;
        if (path.includes("include_archived=true")) {
          setTimeout(releaseFirst, 50); // the stale load lands afterwards
          return [...actions, archived];
        }
        if (actionLoads === 1) await firstLoad;
        return actions;
      }
      if (path.endsWith(`/projects/${PROJECT_ID}`)) return { organization_id: "org-1" };
      if (path.endsWith("/groups")) return [] as never;
      if (path.includes("/users")) return [orgUser];
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByLabelText("Include archived"));
    await waitFor(() => expect(canvas.getByText("Archived action")).toBeInTheDocument());
    // Give the stale response time to land; the newer result must survive it.
    await new Promise((resolve) => setTimeout(resolve, 200));
    await expect(canvas.getByText("Archived action")).toBeInTheDocument();
  },
};

/** A group can be the assignee of a new action; the form sends it as a typed principal. */
export const CreateAssignedToAGroup: Story = {
  beforeEach: () => {
    mockProjectActionsApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Review password reset flow")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /New action/ }));
    await userEvent.type(canvas.getByLabelText("Title"), "Verify audit log retention");
    await userEvent.type(canvas.getByRole("combobox", { name: "Assignee" }), "test");
    await userEvent.click(await canvas.findByText("Test Group"));
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/actions`,
        expect.objectContaining({ title: "Verify audit log retention", assignee: { type: "org_group", id: "group-2" } })
      )
    );
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
    await userEvent.type(canvas.getByLabelText("Title"), "Verify audit log retention");
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT_ID}/actions`,
        expect.objectContaining({ title: "Verify audit log retention", action_type_id: "at1" })
      )
    );
    // Principle 7 — every mutation ends with feedback. This page
    // got real interaction-model work
    // without picking up Toast, so create still just silently re-rendered.
    await expect(within(document.body).getByText("Action created")).toBeInTheDocument();
  },
};

/** Column-header sorting — this list has no
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
      if (path.endsWith("/groups")) return [] as never;
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
