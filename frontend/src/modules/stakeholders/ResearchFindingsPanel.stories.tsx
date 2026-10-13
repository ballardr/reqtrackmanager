import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { withToast } from "../../testing/storybook-helpers";
import { buildFinding } from "./fixtures";
import { ResearchFindingsPanel } from "./ResearchFindingsPanel";
import type { ResearchFinding } from "./types";

const BASE = "/api/v1/projects/project-1/modules/stakeholders";

function mockFindings(rows: ResearchFinding[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `${BASE}/engagements/engagement-1/findings`) return rows;
    if (path.includes("/artefacts/research_finding/finding-1/link-graph")) {
      return buildGraph([[buildGraphNode({ type: "pain_point", id: "pp-1", type_label: "Pain Point", label: "Reports arrive late", status: null })]]);
    }
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ResearchFindingsPanel> = {
  title: "Modules/Stakeholders/ResearchFindingsPanel",
  component: ResearchFindingsPanel,
  decorators: [
    withToast(),
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: { projectId: "project-1", engagementId: "engagement-1" },
};
export default meta;

type Story = StoryObj<typeof ResearchFindingsPanel>;

/** A finding shows its FND code and its links through the shared Links panel (the same "Add link" dialog as every record). */
export const ListsFindingsWithTheirCodeAndLinks: Story = {
  beforeEach: () => mockFindings([buildFinding()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Technicians skip the checklist when offline")).toBeInTheDocument());
    await expect(canvas.getByText("Four of five said they note it down later.")).toBeInTheDocument();
    await expect(canvas.getByText("FND-001")).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByText("Reports arrive late")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: /Add link/ })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockFindings([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No findings recorded for this engagement.")).toBeInTheDocument());
  },
};

export const AddsAFinding: Story = {
  beforeEach: () => {
    mockFindings([]);
    spyOn(api, "post").mockResolvedValue(buildFinding());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add finding" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add finding" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "New finding" }));
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Finding title"), "Offline gaps");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/engagements/engagement-1/findings`, { title: "Offline gaps", description: "" }));
    await waitFor(() => expect(within(document.body).getByText("Finding added.")).toBeInTheDocument());
  },
};

export const EditsAFinding: Story = {
  beforeEach: () => {
    mockFindings([buildFinding()]);
    spyOn(api, "put").mockResolvedValue(buildFinding({ title: "Renamed" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Edit Technicians skip the checklist when offline" }));
    await userEvent.click(canvas.getByRole("button", { name: "Edit Technicians skip the checklist when offline" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Edit Technicians skip the checklist when offline" }));
    await userEvent.clear(dialog.getByLabelText("Finding title"));
    await userEvent.type(dialog.getByLabelText("Finding title"), "Renamed");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(`${BASE}/findings/finding-1`, { title: "Renamed", description: "Four of five said they note it down later." }),
    );
  },
};

export const DeletesBehindAConfirm: Story = {
  beforeEach: () => {
    mockFindings([buildFinding()]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Delete Technicians skip the checklist when offline" }));
    await userEvent.click(canvas.getByRole("button", { name: "Delete Technicians skip the checklist when offline" }));
    await userEvent.click(within(within(document.body).getByRole("dialog", { name: "Delete Technicians skip the checklist when offline?" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/findings/finding-1`));
  },
};

export const DarkTheme: Story = { ...ListsFindingsWithTheirCodeAndLinks, globals: { theme: "dark" } };
