import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { OrgStrategiesPanel } from "./OrgStrategiesPanel";
import type { Strategy } from "./types";

const ORG_ID = "org-1";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "strategy-1", scope: "organization", organization_id: ORG_ID, project_id: null, unique_code: "STR-001", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
    objective: "Become the top provider in our region.", current_state: "", desired_future_state: "",
    rationale: "", expected_outcomes: "", constraints: "", measures_of_success: "", priority: "high",
    time_horizon: "long_term", status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPanelApis(strategies: Strategy[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG_ID}/records/strategy/columns`) return buildRecordColumns({ label: "Strategies" });
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/modules/context_strategy/strategies`)) return strategies;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgStrategiesPanel> = {
  title: "Modules/ContextStrategy/OrgStrategiesPanel",
  component: OrgStrategiesPanel,
  args: { orgId: ORG_ID },
  decorators: [withStatefulAuth(buildUser({ id: "user-1" })), withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgStrategiesPanel>;

export const ListsOrgStrategies: Story = {
  beforeEach: () => mockPanelApis([strategy(), strategy({ id: "strategy-2", title: "Diversify revenue streams", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Lead the regional market")).toBeInTheDocument());
    await expect(canvas.getByText("Diversify revenue streams")).toBeInTheDocument();
  },
};

/** The panel offers the shared Export and Import of the organisation's own Strategies beside New Strategy. */
export const OffersExportAndImportOfTheOrganisationsStrategies: Story = {
  beforeEach: () => mockPanelApis([strategy()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "List actions" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "New Strategy" })).toBeInTheDocument();
  },
};

/** The search box matches the code or the title (it once matched a literal placeholder and found nothing). */
export const SearchMatchesTheTitle: Story = {
  beforeEach: () => mockPanelApis([strategy(), strategy({ id: "strategy-2", title: "Diversify revenue streams", unique_code: "STR-002" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByLabelText("Search organisation Strategy"), "diversify");
    await waitFor(() => expect(canvas.queryByText("Lead the regional market")).not.toBeInTheDocument());
    await expect(canvas.getByText("Diversify revenue streams")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No organisation-scoped Strategy recorded yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Strategy" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Strategy" }));
    await expect(within(document.body).getByRole("heading", { name: "New Strategy (organisation)" })).toBeInTheDocument();
  },
};

/** The Version column is off by default; the column chooser adds it, Priority can be hidden, and the reset restores the defaults. */
export const VersionColumnIsOptionalAndOffByDefault: Story = {
  beforeEach: () => mockPanelApis([strategy()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Organisation Strategy" });
    for (const name of ["Title", "Code", "Priority", "Status"]) {
      await expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    await expect(within(table).queryByRole("columnheader", { name: "Version" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Version" }));
    await expect(within(table).getByRole("columnheader", { name: "Version" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Priority" }));
    await expect(within(table).queryByRole("columnheader", { name: "Priority" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(within(table).queryByRole("columnheader", { name: "Version" })).not.toBeInTheDocument();
    await expect(within(table).getByRole("columnheader", { name: "Priority" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOrgStrategies };
export const DarkTheme: Story = { ...ListsOrgStrategies, globals: { theme: "dark" } };

/** The Title header orders the strategies, ascending then descending. */
export const TitleHeaderSortsTheStrategies: Story = {
  beforeEach: () => mockPanelApis([strategy(), strategy({ id: "strategy-2", title: "Diversify revenue streams", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table");
    await expectHeaderOrdersText(table, "Title");
  },
};