import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../../testing/storybook-helpers";
import { projectPainPointApi, projectStrategyApi } from "./api";
import { PainPointRelationshipsSection } from "./PainPointRelationshipsSection";
import type { ContextStrategyLink, PainPoint } from "./types";

const PROJECT_ID = "project-1";

function painPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    id: "pain-point-1", project_id: PROJECT_ID, pain_point_type_id: "type-operator", pain_point_type_name: "Operator",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Report delays under poor connectivity", description: "", source: "", impact: "", evidence: "",
    priority: "high", status: "triaged", owner_id: null, date_identified: "2026-01-05", is_intentional: false, is_locked: false,
    created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<ContextStrategyLink> = {}): ContextStrategyLink {
  return {
    id: "link-1", source_type: "pain_point", source_id: "pain-point-1", target_type: "strategy",
    target_id: "strategy-1", link_type_id: "link-type-1", direction: "outgoing", display_name: "Drives",
    other_type: "strategy", other_id: "strategy-1", other_display_code: null, other_display_name: "Lead the regional market",
    created_by: "user-1", created_at: "2026-01-06T09:00:00Z",
    ...overrides,
  };
}

const meta: Meta<typeof PainPointRelationshipsSection> = {
  title: "Modules/ContextStrategy/PainPointRelationshipsSection",
  component: PainPointRelationshipsSection,
  args: { projectId: PROJECT_ID, painPoint: painPoint() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof PainPointRelationshipsSection>;

export const NoRelationshipsYet: Story = {
  beforeEach: () => {
    spyOn(projectPainPointApi, "listRelationships").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No relationships yet.")).toBeInTheDocument());
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(projectPainPointApi, "listRelationships").mockResolvedValue([link()]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Lead the regional market")).toBeInTheDocument());
    await expect(canvas.getByText("Drives")).toBeInTheDocument();
  },
};

export const AddDrivesStrategyRelationship: Story = {
  beforeEach: () => {
    spyOn(projectPainPointApi, "listRelationships").mockResolvedValue([]);
    spyOn(projectStrategyApi, "list").mockResolvedValue([
      {
        id: "strategy-2", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
        is_archived: false, archived_at: null, archived_by: null, title: "Modernise the delivery pipeline",
        objective: "", current_state: "", desired_future_state: "", rationale: "", expected_outcomes: "",
        constraints: "", measures_of_success: "", priority: "medium", time_horizon: "medium_term", status: "active",
        version_number: 1, is_locked: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    spyOn(projectPainPointApi, "createRelationship").mockResolvedValue(link({ id: "link-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Strategy"));
    await userEvent.selectOptions(canvas.getByLabelText("Strategy"), "strategy-2");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(projectPainPointApi.createRelationship).toHaveBeenCalledWith(
      PROJECT_ID, "pain-point-1", "drives_strategy", "strategy-2"
    ));
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
