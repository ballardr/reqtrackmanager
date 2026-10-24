import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { Principal } from "../../api/types";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildProject, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectDecisionsPage } from "./ProjectDecisionsPage";
import type { Decision, DecisionTypeDefinition } from "./types";
import { chooseListAction, openListMenu } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: PROJECT_ID, name: "Architecture", sort_order: 0 },
  { id: "dt-2", project_id: PROJECT_ID, name: "Strategy", sort_order: 1 },
];

const USER_ALEX: Principal = { type: "user", id: "user-1", label: "Alex Morgan", member_count: null, exists: true };
const GROUP_PLATFORM: Principal = {
  type: "org_group", id: "group-1", label: "Platform Architecture", member_count: 3, exists: true,
};

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1", project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store.", decision_type_id: "dt-1", status: "approved",
    decision_date: "2026-02-01", decision_maker: USER_ALEX, owner: GROUP_PLATFORM, context: null,
    options_considered: null, chosen_option: null, rationale: null, consequences: null, assumptions: null,
    constraints: null, creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    is_locked: true, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPageApis(decisions: Decision[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/decision/columns")) return buildRecordColumns({ label: "Decisions" });
    if (path === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (path.includes("/orgs/org-1/users")) return [];
    if (path.includes("/templates")) return [];
    if (path.includes("/decision-types")) return DECISION_TYPES;
    if (path.startsWith(`/api/v1/projects/${PROJECT_ID}/modules/decisions?`) || path.endsWith("/modules/decisions")) return decisions;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectDecisionsPage> = {
  title: "Modules/Decisions/ProjectDecisionsPage",
  component: ProjectDecisionsPage,
  decorators: [
    // `parameters.query` opens the page the way a link with a status or `open=0` does.
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/decisions${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/decisions",
      )(Story, context),
    withToast(),
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectDecisionsPage>;

const MIXED = [
  decision(),
  decision({ id: "decision-2", unique_code: "DEC-002", title: "Use Terraform for infra", status: "draft", is_locked: false }),
];

export const ListsDecisions: Story = {
  parameters: { query: "?open=0" },
  beforeEach: () => mockPageApis(MIXED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(canvas.getByText("Use Terraform for infra")).toBeInTheDocument();
    await expect(canvas.getByText("DEC-001")).toBeInTheDocument();
    // The Owner column shows a group owner by name with its kind.
    await expect(canvas.getAllByText("Platform Architecture")).toHaveLength(2);
  },
};

/** The list opens on Decisions still to be made; unticking the filter shows the ones already made. */
export const OpensOnOpenDecisionsByDefault: Story = {
  beforeEach: () => mockPageApis(MIXED),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Use Terraform for infra")).toBeInTheDocument());
    await expect(canvas.queryByText("Adopt PostgreSQL for the new service")).not.toBeInTheDocument();
    const openOnly = canvas.getByRole("checkbox", { name: "Open only" });
    await expect(openOnly).toBeChecked();
    await userEvent.click(openOnly);
    await expect(await canvas.findByText("Adopt PostgreSQL for the new service")).toBeInTheDocument();
  },
};

/** Draft, proposed and under review are open; approved, rejected and superseded are not. */
export const OpenStatusesAreTheOnesNotYetDecided: Story = {
  beforeEach: () => mockPageApis(
    (["draft", "proposed", "under_review", "approved", "rejected", "superseded"] as const)
      .map((status, i) => decision({ id: `d-${i}`, unique_code: `DEC-00${i + 1}`, title: `Decision ${status}`, status })),
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Decision draft")).toBeInTheDocument());
    await expect(canvas.getByText("Decision proposed")).toBeInTheDocument();
    await expect(canvas.getByText("Decision under_review")).toBeInTheDocument();
    for (const done of ["approved", "rejected", "superseded"]) {
      await expect(canvas.queryByText(`Decision ${done}`)).not.toBeInTheDocument();
    }
  },
};

/** A link that names a status shows that slice, so the default never produces an empty list. */
export const AStatusLinkStartsWithOpenOnlyOff: Story = {
  parameters: { query: "?status=approved" },
  beforeEach: () => mockPageApis([MIXED[0]]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Adopt PostgreSQL for the new service")).toBeInTheDocument());
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
    await expect(canvas.getByLabelText("Status")).toHaveValue("approved");
  },
};

/** When only the default hides everything, the empty state says why. */
export const EmptyBecauseOfOpenOnlySaysSo: Story = {
  beforeEach: () => mockPageApis([MIXED[0]]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/^No open Decisions\. Untick Open only/)).toBeInTheDocument());
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No Decisions recorded for this project yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New decision" }));
    await userEvent.click(canvas.getByRole("button", { name: "New decision" }));
    // `DecisionFormModal` portals to `document.body` — see that file's own
    // stories for why this query isn't `within(canvasElement)`.
    await expect(within(document.body).getByRole("heading", { name: "New decision" })).toBeInTheDocument();
  },
};

/** Export and Import are on the title row; Export carries the list's filters (the server applies the same rules). */
export const ExportCarriesThePageFilters: Story = {
  parameters: { query: "?mine=1&q=postgres" },
  beforeEach: () => {
    mockPageApis(MIXED);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Use Terraform for infra")).toBeInTheDocument());
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseListAction(canvas, "Export as CSV");
    await waitFor(() =>
      expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/decision/export?search=postgres&mine=true&open_only=true`),
    );
  },
};

export const LightTheme: Story = { ...ListsDecisions };
export const DarkTheme: Story = { ...ListsDecisions, globals: { theme: "dark" } };
