import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { buildStageWorkflow } from "../testing/storybook-helpers";
import { StageCreateModal } from "./StageCreateModal";

/** The dialog behind Project Administration's "New stage" button: a required name and the governing workflow. */
const meta: Meta<typeof StageCreateModal> = {
  title: "Components/StageCreateModal",
  component: StageCreateModal,
  args: {
    workflows: [buildStageWorkflow({ id: "wf-1", name: "Standard" }), buildStageWorkflow({ id: "wf-2", name: "Tendered" })],
    workflowId: "",
    onWorkflowChange: fn(),
    onNewWorkflow: fn(),
    onCreate: fn(async () => true),
    onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof StageCreateModal>;

const body = () => within(document.body);

/** Only the name is required; the workflow defaults to the first one and Add waits for a name. */
export const OpenWithTheNameRequired: Story = {
  play: async () => {
    const dialog = within(await body().findByRole("dialog", { name: "New stage" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await expect(dialog.getByRole("combobox", { name: "Workflow" })).toHaveValue("wf-1");
    await expect(dialog.getByRole("button", { name: "Add" })).toBeDisabled();
  },
};

export const CreatesAndCloses: Story = {
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "New stage" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Design");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.onCreate).toHaveBeenCalledWith("Design", "wf-1"));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** A refused create (already reported by the caller) leaves the dialog open with what was typed. */
export const ARefusedCreateKeepsTheDialogOpen: Story = {
  args: { onCreate: fn(async () => false) },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "New stage" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Design");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.onCreate).toHaveBeenCalled());
    await expect(args.onClose).not.toHaveBeenCalled();
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Design");
  },
};

export const NewWorkflowOpensTheEditor: Story = {
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "New stage" }));
    await userEvent.click(dialog.getByRole("button", { name: "New workflow" }));
    await expect(args.onNewWorkflow).toHaveBeenCalled();
  },
};

/** The workflow choice belongs to the caller, so a workflow created elsewhere can be selected here. */
export const WorkflowChoiceIsControlled: Story = {
  render: (args) => {
    function Harness() {
      const [workflowId, setWorkflowId] = useState("");
      return <StageCreateModal {...args} workflowId={workflowId} onWorkflowChange={setWorkflowId} />;
    }
    return <Harness />;
  },
  play: async () => {
    const dialog = within(await body().findByRole("dialog", { name: "New stage" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Workflow" }), "wf-2");
    await expect(dialog.getByRole("combobox", { name: "Workflow" })).toHaveValue("wf-2");
  },
};
