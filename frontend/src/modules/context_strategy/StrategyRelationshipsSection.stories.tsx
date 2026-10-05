import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { StrategyRelationshipsSection } from "./StrategyRelationshipsSection";
import type { ContextStrategyLink, Strategy } from "./types";

const PROJECT_ID = "project-1";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "strategy-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
    objective: "Become the top provider in our region.", current_state: "", desired_future_state: "",
    rationale: "", expected_outcomes: "", constraints: "", measures_of_success: "", priority: "high",
    time_horizon: "long_term", status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<ContextStrategyLink> = {}): ContextStrategyLink {
  return {
    id: "link-1", source_type: "strategy", source_id: "strategy-1", target_type: "requirement",
    target_id: "requirement-1", link_type_id: "linktype-1", direction: "outgoing", display_name: "Drives",
    other_type: "requirement", other_id: "requirement-1", other_display_code: "MKT-001",
    other_display_name: "Expand into two new territories", created_by: "user-1",
    created_at: "2026-02-02T09:00:00Z", ...overrides,
  };
}

const meta: Meta<typeof StrategyRelationshipsSection> = {
  title: "Modules/ContextStrategy/StrategyRelationshipsSection",
  component: StrategyRelationshipsSection,
  args: { strategy: strategy(), projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StrategyRelationshipsSection>;

export const NoRelationshipsYet: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No relationships yet.")).toBeInTheDocument());
    await expect(canvas.getByText(/informs → Decision/)).toBeInTheDocument();
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) {
        return [
          link(),
          link({ id: "link-2", other_type: "future_state", display_name: "Defines", other_display_code: "FS-001", other_display_name: "Regional #1 by 2028" }),
        ];
      }
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Drives")).toBeInTheDocument());
    await expect(canvas.getByText(/MKT-001/)).toBeInTheDocument();
    await expect(canvas.getByText("Defines")).toBeInTheDocument();
  },
};

export const AddRequirementLink: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/requirements")) {
        return [{ id: "requirement-1", unique_code: "MKT-001", name: "Expand into two new territories" }];
      }
      return [];
    });
    spyOn(api, "post").mockImplementation(async () => link());
  },
  args: { onChanged: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Requirement"));
    await userEvent.selectOptions(canvas.getByLabelText("Requirement"), "requirement-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/strategies/strategy-1/relationships`,
      { kind: "drives_requirement", target_id: "requirement-1" }
    ));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** An org-scoped Strategy has no single project to search a Requirement/
 * Future State/Open Question within — only "Contributes to another
 * Strategy" and "Supersedes another Strategy" are offered (see this
 * component's own module docstring for the reasoning). */
export const OrgScopedOffersFewerKinds: Story = {
  args: { strategy: strategy({ scope: "organization", organization_id: "org-1", project_id: null }), projectId: undefined, organizationId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/orgs/org-1/modules/context_strategy/strategies")) return [strategy({ id: "strategy-2", title: "Diversify revenue" })];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Relationship"));
    await expect(canvas.queryByText("Drives a Requirement")).not.toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Contributes to another Strategy" })).toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Supersedes another Strategy" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
