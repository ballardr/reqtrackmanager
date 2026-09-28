import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { StrategyFormModal } from "./StrategyFormModal";
import type { Strategy } from "./types";

/**
 * `StrategyFormModal` renders via `Modal`, which portals to `document.body`
 * — every assertion here queries `within(document.body)`, mirroring
 * `modules/decisions/DecisionFormModal.stories.tsx`'s own identical
 * convention.
 */
const meta: Meta<typeof StrategyFormModal> = {
  title: "Modules/ContextStrategy/StrategyFormModal",
  component: StrategyFormModal,
  args: { scopeLabel: "project", onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StrategyFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New Strategy (project)" })).toBeInTheDocument();
  },
};

export const SubmitsNewStrategy: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Strategy title"), "Lead the regional market");
    await userEvent.type(body.getByLabelText("Objective / strategic theme"), "Become the top provider in our region.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Lead the regional market", objective: "Become the top provider in our region." })
    ));
  },
};

export const SaveDisabledUntilRequiredFieldsFilled: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Strategy title"), "Lead the regional market");
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Objective / strategic theme"), "Become the top provider.");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "strategy-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
      is_archived: false, archived_at: null, archived_by: null, title: "Lead the regional market",
      objective: "Become the top provider in our region.", current_state: "We are #3 in the region.",
      desired_future_state: "We are #1 in the region.", rationale: "Market analysis shows a clear opening.",
      expected_outcomes: "Revenue up 20%.", constraints: "Limited hiring budget.", measures_of_success: "Market share.",
      priority: "high", time_horizon: "long_term", status: "draft", version_number: 1, is_locked: false,
      created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies Strategy,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit Lead the regional market" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("We are #3 in the region.")).toBeInTheDocument();
    await expect(body.getByLabelText("Change note")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
