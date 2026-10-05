import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import type { GuidingPrinciple } from "./types";

/**
 * `GuidingPrincipleFormModal` renders via `Modal`, which portals to
 * `document.body` — every assertion here queries `within(document.body)`,
 * mirroring `StrategyFormModal.stories.tsx`'s own identical convention.
 */
const meta: Meta<typeof GuidingPrincipleFormModal> = {
  title: "Modules/ContextStrategy/GuidingPrincipleFormModal",
  component: GuidingPrincipleFormModal,
  args: { scopeLabel: "project", onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof GuidingPrincipleFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New Guiding Principle (project)" })).toBeInTheDocument();
  },
};

export const SubmitsNewGuidingPrinciple: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Guiding Principle name"), "Field data is captured once");
    await userEvent.type(body.getByLabelText("Principle statement"), "Every field observation is recorded exactly once, at the point of inspection.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Field data is captured once",
        principle_statement: "Every field observation is recorded exactly once, at the point of inspection.",
      })
    ));
  },
};

export const SaveDisabledUntilRequiredFieldsFilled: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Guiding Principle name"), "Field data is captured once");
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Principle statement"), "Every observation recorded once.");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "gp-1", scope: "project", organization_id: null, project_id: "project-1", creator_id: "user-1",
      is_archived: false, archived_at: null, archived_by: null, name: "Field data is captured once",
      principle_statement: "Every field observation is recorded exactly once, at the point of inspection.",
      rationale: "Re-keying paper forms introduces errors and delay.", priority: "high", status: "draft",
      owner_id: null, version_number: 1, is_locked: false,
      created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies GuidingPrinciple,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit Field data is captured once" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Re-keying paper forms introduces errors and delay.")).toBeInTheDocument();
    await expect(body.getByLabelText("Change note")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
