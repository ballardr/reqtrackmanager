import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { OrgFutureStatesPanel } from "./OrgFutureStatesPanel";
import type { FutureState } from "./types";

const ORG_ID = "org-1";

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: "future-state-1", scope: "organization", organization_id: ORG_ID, project_id: null, unique_code: "FUT-001", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
    current_state: "", desired_state: "We are the top provider in our region.", target_date: "2028-06-30",
    outcomes: "", success_measures: "", constraints: "", assumptions: "",
    status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function mockPanelApis(futureStates: FutureState[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`/api/v1/orgs/${ORG_ID}/modules/context_strategy/future-states`)) return futureStates;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof OrgFutureStatesPanel> = {
  title: "Modules/ContextStrategy/OrgFutureStatesPanel",
  component: OrgFutureStatesPanel,
  args: { orgId: ORG_ID },
  decorators: [withStatefulAuth(buildUser({ id: "user-1" })), withRouter("/org-overview"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgFutureStatesPanel>;

export const ListsOrgFutureStates: Story = {
  beforeEach: () => mockPanelApis([futureState(), futureState({ id: "future-state-2", title: "Diversified supply base", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Regional #1 by 2028")).toBeInTheDocument());
    await expect(canvas.getByText("Diversified supply base")).toBeInTheDocument();
  },
};

/** The Version column is off by default; the column chooser adds it, Target date can be hidden, and the reset restores the defaults. */
export const VersionColumnIsOptionalAndOffByDefault: Story = {
  beforeEach: () => mockPanelApis([futureState()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Organisation Future State" });
    for (const name of ["Title", "Code", "Status", "Target date"]) {
      await expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    await expect(within(table).queryByRole("columnheader", { name: "Version" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Version" }));
    await expect(within(table).getByRole("columnheader", { name: "Version" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Target date" }));
    await expect(within(table).queryByRole("columnheader", { name: "Target date" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(within(table).queryByRole("columnheader", { name: "Version" })).not.toBeInTheDocument();
    await expect(within(table).getByRole("columnheader", { name: "Target date" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No organisation-scoped Future State recorded yet.")).toBeInTheDocument());
  },
};

export const OpenCreateModal: Story = {
  beforeEach: () => mockPanelApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Future State" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Future State" }));
    await expect(within(document.body).getByRole("heading", { name: "New Future State (organisation)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsOrgFutureStates };
export const DarkTheme: Story = { ...ListsOrgFutureStates, globals: { theme: "dark" } };

/** The Title header orders the future states, ascending then descending. */
export const TitleHeaderSortsTheFutureStates: Story = {
  beforeEach: () => mockPanelApis([futureState(), futureState({ id: "future-state-2", title: "Diversified supply base", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table");
    await expectHeaderOrdersText(table, "Title");
  },
};