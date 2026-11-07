import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { StageWorkflow } from "../api/types";
import { buildStageWorkflow, withToast } from "../testing/storybook-helpers";
import { StageWorkflowsPanel } from "./StageWorkflowsPanel";

const OUTSOURCED: StageWorkflow = buildStageWorkflow({
  id: "workflow-2", name: "Outsourced work", scope: "project", in_use: false,
  phases: [
    { id: "o1", name: "Scoping", kind: "open", sort_order: 0 },
    { id: "o2", name: "Awarded", kind: "locked", sort_order: 1 },
  ],
});

/** Stage workflow administration for one tier, shared by Organisation Admin and Project Admin. */
const meta: Meta<typeof StageWorkflowsPanel> = {
  title: "Components/StageWorkflowsPanel",
  component: StageWorkflowsPanel,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StageWorkflowsPanel>;

/** The organisation tier lists its workflows with each phase's kind and marks the starting phase. */
export const OrganisationTierListsPhasesWithKinds: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildStageWorkflow()]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Standard")).toBeInTheDocument();
    await expect(canvas.getByText("Approved · Locked")).toBeInTheDocument();
    await expect(canvas.getByText("Start")).toBeInTheDocument();
    await expect(canvas.getByText("In use")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit workflow Standard" })).toBeInTheDocument();
  },
};

/** In a project, an organisation workflow can be hidden but not edited; the project's own can be edited and deleted. */
export const ProjectTierHidesOrganisationWorkflowsAndRestoresThem: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    let hidden = false;
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/hidden")) return hidden ? [{ id: "workflow-1", name: "Standard" }] : [];
      return hidden ? [OUTSOURCED] : [buildStageWorkflow(), OUTSOURCED];
    });
    spyOn(api, "delete").mockImplementation(async () => {
      hidden = true;
    });
    spyOn(api, "post").mockImplementation(async () => {
      hidden = false;
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Standard")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit workflow Standard" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit workflow Outsourced work" })).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Hide workflow Standard" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Hide" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/project-1/stage-workflows/workflow-1"));
    await waitFor(() => expect(canvas.queryByText("Standard")).not.toBeInTheDocument());

    await userEvent.click(await canvas.findByRole("button", { name: /Add organisation defaults/ }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Add 1 default" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/projects/project-1/stage-workflows/restore", { workflow_ids: ["workflow-1"] }));
  },
};

/** A new workflow is posted with its phases in order. */
export const NewWorkflowSavesThroughTheApi: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildStageWorkflow()]);
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New workflow" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New workflow" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Workflow name/ }), "Fast track");
    await userEvent.type(dialog.getByRole("textbox", { name: "Phase name 1" }), "Go");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/stage-workflows", { name: "Fast track", phases: [{ name: "Go", kind: "open" }] }),
    );
  },
};
