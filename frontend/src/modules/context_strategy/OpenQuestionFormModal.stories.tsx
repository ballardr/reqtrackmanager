import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { OpenQuestionFormModal } from "./OpenQuestionFormModal";
import type { OpenQuestion } from "./types";

/**
 * `OpenQuestionFormModal` renders via `Modal`, which portals to
 * `document.body` — every assertion here queries `within(document.body)`,
 * mirroring `PainPointFormModal.stories.tsx`'s own identical convention.
 */
const meta: Meta<typeof OpenQuestionFormModal> = {
  title: "Modules/ContextStrategy/OpenQuestionFormModal",
  component: OpenQuestionFormModal,
  args: { onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof OpenQuestionFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New Open Question" })).toBeInTheDocument();
  },
};

export const SubmitsNewOpenQuestion: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Question"), "Should we standardise on a single battery vendor?");
    await userEvent.type(body.getByLabelText("Context"), "Two vendors are currently qualified.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ question: "Should we standardise on a single battery vendor?" })
    ));
  },
};

export const SaveDisabledUntilQuestionFilled: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(body.getByLabelText("Question"), "Is the UI presentation question still open?");
    await expect(body.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "open-question-1", project_id: "project-1", creator_id: "user-1",
      is_archived: false, archived_at: null, archived_by: null,
      question: "Should we standardise on a single battery vendor?",
      context: "Two vendors are currently qualified.", evidence: "",
      priority: "high", status: "open", owner_id: null, due_date: "2026-03-01", is_locked: false,
      created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
    } satisfies OpenQuestion,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit Open Question" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Should we standardise on a single battery vendor?")).toBeInTheDocument();
    await expect(body.getByDisplayValue("2026-03-01")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
