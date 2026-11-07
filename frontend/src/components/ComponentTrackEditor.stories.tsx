import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildComponentTrack, buildStageWorkflow } from "../testing/storybook-helpers";
import { ComponentTrackEditor } from "./ComponentTrackEditor";

/** The dialog for one component's track within a stage: workflow, applicability and owner. */
const meta: Meta<typeof ComponentTrackEditor> = {
  title: "Components/ComponentTrackEditor",
  component: ComponentTrackEditor,
  args: {
    track: buildComponentTrack(), componentName: "Software", stageName: "Release 1",
    workflows: [buildStageWorkflow(), buildStageWorkflow({ id: "workflow-2", name: "Outsourced work" })],
    orgUsers: [], organizationId: "org-1", projectId: "project-1", onCancel: fn(), onSave: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ComponentTrackEditor>;

/** Saving without a change sends nothing. */
export const SavingUnchangedSendsNoChanges: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Software: Release 1" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({});
  },
};

/** A changed workflow is sent alone. */
export const ChangedWorkflowIsSent: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: /Workflow/ }), "workflow-2");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({ workflow_id: "workflow-2" });
  },
};

/** The server's refusal is shown in the dialog. */
export const ShowsTheServerError: Story = {
  args: { error: "A track can change workflow or applicability only while it is in an open phase and has no baseline." },
  play: async () => {
    await expect(await within(document.body).findByText(/only while it is in an open phase/)).toBeInTheDocument();
  },
};
