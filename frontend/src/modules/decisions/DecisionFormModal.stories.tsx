import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DecisionFormModal } from "./DecisionFormModal";
import type { Decision, DecisionTemplate, DecisionTypeDefinition } from "./types";

const DECISION_TYPES: DecisionTypeDefinition[] = [
  { id: "dt-1", project_id: "project-1", name: "Architecture", sort_order: 0 },
  { id: "dt-2", project_id: "project-1", name: "Strategy", sort_order: 1 },
];

const TEMPLATES: DecisionTemplate[] = [
  {
    id: "template-1", organization_id: "org-1", name: "Nygard (Classic ADR)", description: null,
    context_prompt: "What is the issue that we're seeing that is motivating this decision?",
    options_considered_prompt: null, chosen_option_prompt: null,
    rationale_prompt: "Why did we choose this option?", consequences_prompt: "What becomes easier or harder?",
    assumptions_prompt: null, constraints_prompt: null, sort_order: 0,
  },
];

const USER_OPTIONS = [{ id: "user-1", display_name: "Alex Morgan" }, { id: "user-2", display_name: "Jordan Lee" }];

/**
 * `DecisionFormModal` renders via `Modal`, which portals to `document.body`
 * (`createPortal`) — every assertion here queries `within(document.body)`,
 * not `canvasElement`, mirroring `modules/compliance/StandardFormModal
 * .stories.tsx`'s own identical convention for the same reason.
 */
const meta: Meta<typeof DecisionFormModal> = {
  title: "Modules/Decisions/DecisionFormModal",
  component: DecisionFormModal,
  args: { decisionTypes: DECISION_TYPES, userOptions: USER_OPTIONS, currentUserId: "user-1", onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof DecisionFormModal>;

export const CreateNew: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New decision" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Alex Morgan")).toBeInTheDocument();
  },
};

export const CreateFromTemplate: Story = {
  args: { templates: TEMPLATES },
  play: async () => {
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Start from a template (optional)"), "template-1");
    await waitFor(() => expect(body.getByDisplayValue(
      "What is the issue that we're seeing that is motivating this decision?"
    )).toBeInTheDocument());
  },
};

export const SubmitsNewDecision: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Decision title"), "Adopt PostgreSQL");
    await userEvent.type(body.getByLabelText("Decision statement"), "Use PostgreSQL as the backing store.");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Adopt PostgreSQL", decision_statement: "Use PostgreSQL as the backing store.", owner_id: "user-1" })
    ));
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      id: "decision-1", project_id: "project-1", unique_code: "DEC-001", title: "Adopt PostgreSQL",
      decision_statement: "Use PostgreSQL as the backing store.", decision_type_id: "dt-1", status: "draft",
      decision_date: null, decision_maker_id: null, owner_id: "user-1", context: "Legacy MySQL is EOL.",
      options_considered: null, chosen_option: null, rationale: null, consequences: null, assumptions: null,
      constraints: null, creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
      is_locked: false, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    } satisfies Decision,
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit DEC-001" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("Legacy MySQL is EOL.")).toBeInTheDocument();
    await expect(body.queryByLabelText("Start from a template (optional)")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
