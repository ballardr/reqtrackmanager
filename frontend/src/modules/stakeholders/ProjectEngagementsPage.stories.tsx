import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { withToast } from "../../testing/storybook-helpers";
import { buildEngagement, buildFinding, buildPersona, buildStakeholder } from "./fixtures";
import { ProjectEngagementsPage } from "./ProjectEngagementsPage";
import type { Engagement } from "./types";
import { chooseListAction, openListMenu } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const ENGAGEMENTS: Engagement[] = [
  buildEngagement(),
  buildEngagement({
    id: "engagement-2", unique_code: "ENG-002", title: "Evidence follow-up", channel: "email", engagement_date: "2026-04-02",
    participant_count: 1, retain_until: "2026-04-30", retention_due: true,
  }),
  buildEngagement({
    id: "engagement-3", unique_code: "ENG-003", title: "Technician focus group", channel: "focus_group", engagement_date: "2026-02-20",
    participant_count: 0, anonymous_participant_count: 5,
  }),
];

function mockPageApis(rows: Engagement[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (/\/records\/[a-z_]+\/columns$/.test(path)) return buildRecordColumns({ label: "Engagements" });
    if (path.startsWith(`${BASE}/engagements`)) return rows;
    if (path === `${BASE}/stakeholders`) return [buildStakeholder()];
    if (path === `${BASE}/personas`) return [buildPersona()];
    if (path === `${BASE}/findings/finding-1`) return buildFinding();
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/** Shows the current location, rendered by the catch-all route so a redirect away from the list can be asserted. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

const LIST_PATH = `/projects/${PROJECT_ID}/modules/stakeholders/engagements`;

const meta: Meta<typeof ProjectEngagementsPage> = {
  title: "Modules/Stakeholders/ProjectEngagementsPage",
  component: ProjectEngagementsPage,
  decorators: [
    (Story, context) => (
      <MemoryRouter initialEntries={[(context.parameters.initialPath as string | undefined) ?? LIST_PATH]}>
        <Routes>
          <Route path="/projects/:projectId/modules/stakeholders/engagements" element={<Story />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectEngagementsPage>;

export const ListsEngagementsWithLabelledChannels: Story = {
  beforeEach: () => mockPageApis(ENGAGEMENTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Quarterly review with the regulator")).toBeInTheDocument());
    const table = within(canvas.getByRole("table", { name: "Engagements" }));
    await expect(table.getByText("Focus group")).toBeInTheDocument();
    await expect(table.getByText("Email")).toBeInTheDocument();
    await expect(table.queryByText("focus_group")).not.toBeInTheDocument();
    // Channel is the type column; an engagement has no Scope or Status column.
    await expect(table.getByRole("columnheader", { name: "Channel" })).toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    // Participants combine named and anonymous ones.
    await expect(table.getByText("5")).toBeInTheDocument();
    await expect(table.getByText("Review due")).toBeInTheDocument();
    await expect(canvas.queryByText("Show archived")).not.toBeInTheDocument();
  },
};

export const ChannelBadgeFiltersTheList: Story = {
  beforeEach: () => mockPageApis(ENGAGEMENTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Evidence follow-up"));
    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await waitFor(() => expect(canvas.queryByText("Technician focus group")).not.toBeInTheDocument());
    await expect(canvas.getByText("Evidence follow-up")).toBeInTheDocument();
  },
};

/** The participant, persona, date range and retention filters are applied by the API. */
export const FiltersAreSentToTheApi: Story = {
  beforeEach: () => mockPageApis(ENGAGEMENTS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Participant" }));
    await waitFor(() => expect(canvas.getByRole("option", { name: "Pat Regulator" })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Participant" }), "stakeholder-1");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${BASE}/engagements?stakeholder_id=stakeholder-1`));
    await userEvent.click(canvas.getByLabelText("Retention review due"));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${BASE}/engagements?stakeholder_id=stakeholder-1&retention_due=true`));
  },
};

/** Export carries the server-side filters (a participant, a date range, retention) and the list's own channel filter. */
export const ExportCarriesTheFilters: Story = {
  beforeEach: () => {
    mockPageApis(ENGAGEMENTS);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Evidence follow-up"));
    await userEvent.click(canvas.getByLabelText("Retention review due"));
    await userEvent.click(canvas.getByRole("button", { name: "Email" }));
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseListAction(canvas, "Export as CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/engagement/export?retention_due=true&type=Email`));
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No engagements logged for this project yet.")).toBeInTheDocument());
  },
};

export const LogEngagementPostsAndToasts: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockResolvedValue(buildEngagement());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Log engagement" }));
    await userEvent.click(canvas.getByRole("button", { name: "Log engagement" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Log engagement" }));
    await userEvent.type(dialog.getByLabelText("Engagement title"), "Kick-off call");
    await userEvent.selectOptions(dialog.getByLabelText("Channel"), "call");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/engagements`, expect.objectContaining({ title: "Kick-off call", channel: "call" })),
    );
    await waitFor(() => expect(within(document.body).getByText("Engagement logged.")).toBeInTheDocument());
  },
};

export const CreateErrorKeepsTheModalOpen: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Only an Engagement Owner (or admin/manager) may do this."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Log engagement" }));
    await userEvent.click(canvas.getByRole("button", { name: "Log engagement" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Log engagement" }));
    await userEvent.type(dialog.getByLabelText("Engagement title"), "x");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(dialog.getByText(/Only an Engagement Owner/)).toBeInTheDocument());
  },
};

export const LoadFailureShowsAMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Not found"));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/Not found|aren't enabled/)).toBeInTheDocument());
  },
};

/** A link to a research finding (`?finding=`) redirects to the engagement the finding belongs to. */
export const FindingLinkRedirectsToItsEngagement: Story = {
  parameters: { initialPath: `${LIST_PATH}?finding=finding-1` },
  beforeEach: () => mockPageApis(ENGAGEMENTS),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${BASE}/findings/finding-1`));
    await waitFor(() => expect(within(canvasElement).getByTestId("location")).toHaveTextContent(`${LIST_PATH}/engagement-1`));
  },
};

export const DarkTheme: Story = { ...ListsEngagementsWithLabelledChannels, globals: { theme: "dark" } };
