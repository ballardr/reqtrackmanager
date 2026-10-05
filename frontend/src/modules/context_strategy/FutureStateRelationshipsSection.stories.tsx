import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { FutureStateRelationshipsSection } from "./FutureStateRelationshipsSection";
import type { ContextStrategyLink, FutureState } from "./types";

const PROJECT_ID = "project-1";

function futureState(overrides: Partial<FutureState> = {}): FutureState {
  return {
    id: "future-state-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
    current_state: "", desired_state: "We are the top provider in our region.", target_date: "2028-06-30",
    outcomes: "", success_measures: "", constraints: "", assumptions: "",
    status: "active", version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<ContextStrategyLink> = {}): ContextStrategyLink {
  return {
    id: "link-1", source_type: "future_state", source_id: "future-state-1", target_type: "requirement",
    target_id: "requirement-1", link_type_id: "linktype-1", direction: "outgoing", display_name: "Related to",
    other_type: "requirement", other_id: "requirement-1", other_display_code: "MKT-001",
    other_display_name: "Expand into two new territories", created_by: "user-1",
    created_at: "2026-02-02T09:00:00Z", ...overrides,
  };
}

const meta: Meta<typeof FutureStateRelationshipsSection> = {
  title: "Modules/ContextStrategy/FutureStateRelationshipsSection",
  component: FutureStateRelationshipsSection,
  args: { futureState: futureState(), projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof FutureStateRelationshipsSection>;

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
    await expect(canvas.getByText(/related to → Decision/)).toBeInTheDocument();
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) {
        return [
          link(),
          link({ id: "link-2", other_type: "pain_point", display_name: "Related to", other_display_code: "PP-001", other_display_name: "Paper re-keying" }),
        ];
      }
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByText("Related to").length).toBeGreaterThan(0));
    await expect(canvas.getByText(/MKT-001/)).toBeInTheDocument();
    await expect(canvas.getByText(/PP-001/)).toBeInTheDocument();
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
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/future-states/future-state-1/relationships`,
      { kind: "related_to_requirement", target_id: "requirement-1" }
    ));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

/** An org-scoped Future State has no single project to search a Requirement/
 * Pain Point/Guiding Principle within — only "Supersedes another Future
 * State" is offered (see this component's own module docstring). */
export const OrgScopedOffersFewerKinds: Story = {
  args: { futureState: futureState({ scope: "organization", organization_id: "org-1", project_id: null }), projectId: undefined, organizationId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/orgs/org-1/modules/context_strategy/future-states")) return [futureState({ id: "future-state-2", title: "Diversified supply base" })];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Relationship"));
    await expect(canvas.queryByText("Related to a Requirement")).not.toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Supersedes another Future State" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
