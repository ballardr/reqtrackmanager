import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildNeed } from "./fixtures";
import { ProjectNeedsPage } from "./ProjectNeedsPage";
import type { Need } from "./types";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

function mockPageApis(needs: Need[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/needs`)) return needs;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectNeedsPage> = {
  title: "Modules/Stakeholders/ProjectNeedsPage",
  component: ProjectNeedsPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/needs`, "/projects/:projectId/modules/stakeholders/needs"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectNeedsPage>;

export const ListsNeedsWithLabelledStatus: Story = {
  beforeEach: () => mockPageApis([buildNeed(), buildNeed({ id: "need-2", name: "Audit without a meeting", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Diagnose faults quickly")).toBeInTheDocument());
    const table = within(canvas.getByRole("table", { name: "Stakeholder Needs" }));
    // Status goes through its label map; a need has no Type or Scope column.
    await expect(table.getByText("Draft")).toBeInTheDocument();
    await expect(table.getByText("Active")).toBeInTheDocument();
    await expect(table.queryByText("draft")).not.toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
  },
};

export const StatusBadgeFiltersTheList: Story = {
  beforeEach: () => mockPageApis([buildNeed(), buildNeed({ id: "need-2", name: "Audit without a meeting", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Audit without a meeting"));
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(canvas.queryByText("Diagnose faults quickly")).not.toBeInTheDocument());
    await expect(canvas.getByText("Audit without a meeting")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Stakeholder Needs recorded for this project yet.")).toBeInTheDocument());
  },
};

export const CreatePostsAndToasts: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockResolvedValue(buildNeed());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Need" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Need" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "New Stakeholder Need" }));
    await userEvent.type(dialog.getByLabelText("Need name"), "Diagnose faults quickly");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/needs`, expect.objectContaining({ name: "Diagnose faults quickly" })),
    );
    await waitFor(() => expect(within(document.body).getByText("Stakeholder Need created.")).toBeInTheDocument());
  },
};

export const CreateErrorKeepsTheModalOpen: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Only a Stakeholder Need Owner (or admin/manager) may do this."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Need" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Need" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "New Stakeholder Need" }));
    await userEvent.type(dialog.getByLabelText("Need name"), "x");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(dialog.getByText(/Only a Stakeholder Need Owner/)).toBeInTheDocument());
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

export const DarkTheme: Story = { ...ListsNeedsWithLabelledStatus, globals: { theme: "dark" } };
