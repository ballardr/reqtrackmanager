import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildStageWorkflow } from "../testing/storybook-helpers";
import { StageWorkflowEditor } from "./StageWorkflowEditor";

/** The dialog that creates or edits a stage workflow: a name and an ordered list of phases, each with a kind. */
const meta: Meta<typeof StageWorkflowEditor> = {
  title: "Components/StageWorkflowEditor",
  component: StageWorkflowEditor,
  args: { workflow: null, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StageWorkflowEditor>;

const dialog = async () => within(await within(document.body).findByRole("dialog", { name: /workflow/i }));

/** A new workflow starts with one open phase; Save stays disabled until the name and every phase are filled. */
export const CreatesAWorkflowWithOrderedPhases: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByRole("textbox", { name: /Workflow name/ }), "Outsourced work");
    await userEvent.type(d.getByRole("textbox", { name: "Phase name 1" }), "Scoping");
    await userEvent.click(d.getByRole("button", { name: "Add phase" }));
    await userEvent.type(d.getByRole("textbox", { name: "Phase name 2" }), "Awarded");
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Kind 2" }), "Locked");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalled());
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Outsourced work",
      phases: [{ name: "Scoping", kind: "open" }, { name: "Awarded", kind: "locked" }],
    });
  },
};

/** Editing keeps each existing phase's id (so stages in it stay attached), and reordering changes the start. */
export const EditingKeepsPhaseIdsAndOrder: Story = {
  args: { workflow: buildStageWorkflow() },
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Move phase Review up" }));
    await userEvent.click(d.getByRole("button", { name: "Remove phase Archived" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalled());
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Standard",
      phases: [
        { id: "phase-review", name: "Review", kind: "review" },
        { id: "phase-scoping", name: "Scoping", kind: "open" },
        { id: "phase-approved", name: "Approved", kind: "locked" },
        { id: "phase-completed", name: "Completed", kind: "closed" },
      ],
    });
  },
};

/** The last phase cannot be removed: a workflow needs at least one. */
export const KeepsAtLeastOnePhase: Story = {
  play: async () => {
    const d = await dialog();
    await expect(d.getByRole("button", { name: /Remove phase/ })).toBeDisabled();
  },
};

/** A save error from the server (a phase in use cannot be removed) is shown in the dialog header. */
export const ShowsAServerError: Story = {
  args: { workflow: buildStageWorkflow(), error: "The phase 'Approved' is in use by a stage and cannot be removed." },
  play: async () => {
    const d = await dialog();
    await expect(d.getByText(/is in use by a stage/)).toBeInTheDocument();
  },
};
