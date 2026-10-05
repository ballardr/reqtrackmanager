import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { FutureStateFormModal } from "./FutureStateFormModal";
import type { FutureState } from "./types";

/**
 * `FutureStateFormModal` renders via `Modal`, which portals to
 * `document.body` — every assertion here queries `within(document.body)`,
 * mirroring `StrategyFormModal.stories.tsx`'s own identical convention.
 */
const meta: Meta<typeof FutureStateFormModal> = {
  title: "Modules/ContextStrategy/FutureStateFormModal",
  component: FutureStateFormModal,
  args: { scopeLabel: "project", onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof FutureStateFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New Future State (project)" })).toBeInTheDocument();
  },
};

export const SubmitsNewFutureState: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Future State title"), "Regional #1 by 2028");
    await userEvent.type(body.getByLabelText("Desired state"), "We are the top provider in our region.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Regional #1 by 2028", desired_state: "We are the top provider in our region.", target_date: null })
    ));
  },
};

export const SaveDisabledUntilRequiredFieldsFilled: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Future State title"), "Regional #1 by 2028");
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Desired state"), "We are the top provider.");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const SubmitsWithTargetDate: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Future State title"), "Regional #1 by 2028");
    await userEvent.type(body.getByLabelText("Desired state"), "We are the top provider in our region.");
    await userEvent.type(body.getByLabelText("Target date"), "2028-06-30");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ target_date: "2028-06-30" })
    ));
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "future-state-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
      is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
      current_state: "We are #3 in the region.", desired_state: "We are #1 in the region.", target_date: "2028-06-30",
      outcomes: "Revenue up 20%.", success_measures: "Market share.", constraints: "Limited hiring budget.",
      assumptions: "Market conditions stay favourable.", status: "draft", version_number: 1, is_locked: false,
      created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies FutureState,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit Regional #1 by 2028" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("We are #3 in the region.")).toBeInTheDocument();
    await expect(body.getByLabelText("Target date")).toHaveValue("2028-06-30");
    await expect(body.getByLabelText("Change note")).toBeInTheDocument();
  },
};

export const ClearingTargetDateSendsNull: Story = {
  args: {
    initial: {
      id: "future-state-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
      is_archived: false, archived_at: null, archived_by: null, title: "Regional #1 by 2028",
      current_state: "", desired_state: "We are #1 in the region.", target_date: "2028-06-30",
      outcomes: "", success_measures: "", constraints: "", assumptions: "",
      status: "draft", version_number: 1, is_locked: false,
      created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies FutureState,
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.clear(body.getByLabelText("Target date"));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ target_date: null })));
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
