import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { DecisionRelationshipsSection } from "./DecisionRelationshipsSection";
import type { Decision, DecisionLink } from "./types";

const PROJECT_ID = "project-1";

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "decision-1", project_id: PROJECT_ID, unique_code: "DEC-001", title: "Adopt PostgreSQL for the new service",
    decision_statement: "Use PostgreSQL as the backing store.", decision_type_id: "dt-1", status: "approved",
    decision_date: "2026-02-01", decision_maker_id: "user-1", owner_id: "user-1",
    context: null, options_considered: null, chosen_option: null, rationale: null, consequences: null,
    assumptions: null, constraints: null, creator_id: "user-1", is_archived: false, archived_at: null,
    archived_by: null, is_locked: true, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<DecisionLink> = {}): DecisionLink {
  return {
    id: "link-1", source_type: "decision", source_id: "decision-1", target_type: "requirement",
    target_id: "requirement-1", link_type_id: "linktype-1", direction: "outgoing", display_name: "Implements",
    other_type: "requirement", other_id: "requirement-1", other_display_code: "AUTH-LOG-001",
    other_display_name: "Users can reset a forgotten password", created_by: "user-1",
    created_at: "2026-02-02T09:00:00Z", ...overrides,
  };
}

const meta: Meta<typeof DecisionRelationshipsSection> = {
  title: "Modules/Decisions/DecisionRelationshipsSection",
  component: DecisionRelationshipsSection,
  args: { projectId: PROJECT_ID, decision: decision() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof DecisionRelationshipsSection>;

export const NoRelationshipsYet: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/requirements")) return [];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No relationships yet.")).toBeInTheDocument());
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) {
        return [
          link(),
          link({ id: "link-2", other_type: "decision", display_name: "Depends on", other_display_code: "DEC-002", other_display_name: "Use Terraform for infra" }),
        ];
      }
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Implements")).toBeInTheDocument());
    await expect(canvas.getByText(/AUTH-LOG-001/)).toBeInTheDocument();
    await expect(canvas.getByText("Depends on")).toBeInTheDocument();
  },
};

export const AddRequirementLink: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/requirements")) {
        return [{ id: "requirement-1", unique_code: "AUTH-LOG-001", name: "Users can reset a forgotten password" }];
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
      `/api/v1/projects/${PROJECT_ID}/modules/decisions/decision-1/requirement-links`,
      { requirement_id: "requirement-1", kind: "implements" }
    ));
    // A supersession has a side effect on a *different* Decision
    // (flipping it to Superseded) that this section's own list can't
    // reflect on its own — `onChanged` is how the caller learns to
    // refresh anything wider than this one Decision's relationships list.
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
