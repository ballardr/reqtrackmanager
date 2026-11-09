import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { StageWorkflow } from "../api/types";
import { buildStageWorkflow, buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
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
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof StageWorkflowsPanel>;

/** The organisation tier lists each workflow as ordered steps with each phase's kind, and marks the starting phase. */
export const OrganisationTierListsPhasesWithKinds: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildStageWorkflow()]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Standard")).toBeInTheDocument();
    // One numbered step per phase, in order, with the kind and the starting phase beside the name.
    const steps = within(canvas.getByRole("list", { name: "Phases of Standard" })).getAllByRole("listitem");
    await expect(steps.length).toBeGreaterThan(1);
    await expect(within(steps[0]).getByText(/Starting phase/)).toBeInTheDocument();
    await expect(within(steps[2]).getByText("Approved")).toBeInTheDocument();
    await expect(within(steps[2]).getByText("Locked")).toBeInTheDocument();
    await expect(canvas.queryByText("In use")).not.toBeInTheDocument();
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

/** A project's list names the stages that follow a workflow; the organisation tier counts across its projects and names none. */
export const UsedByNamesStagesInAProjectAndCountsAtTheOrganisation: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/hidden")) return [];
      return [
        buildStageWorkflow({ used_by: { stage_names: ["Design", "Build"], stage_count: 2, track_count: 3, project_count: 1 } }),
        buildStageWorkflow({ id: "workflow-9", name: "Spare" }),
      ];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Two workflows start closed; the used-by line is part of the opened row.
    await userEvent.click(await canvas.findByRole("button", { name: /^Standard/ }));
    await userEvent.click(canvas.getByRole("button", { name: /^Spare/ }));
    await expect(await canvas.findByText("Used by Design, Build; 3 component tracks")).toBeInTheDocument();
    await expect(canvas.getByText("Not used yet")).toBeInTheDocument();
  },
};

export const OrganisationUsageIsCountsOnly: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildStageWorkflow({ used_by: { stage_names: [], stage_count: 4, track_count: 1, project_count: 2 } }),
    ]);
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Used by 4 stages and 1 component track in 2 projects")).toBeInTheDocument();
  },
};

/** Several workflows start closed (name, step count, source); opening one shows its steps and used-by line, and its actions stay beside the name. */
export const SeveralWorkflowsStartClosedAndOpenOnDemand: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : [buildStageWorkflow(), OUTSOURCED]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const standard = await canvas.findByRole("button", { name: /^Standard 5 steps/ });
    const outsourced = canvas.getByRole("button", { name: /^Outsourced work 2 steps/ });
    await expect(standard).toHaveAttribute("aria-expanded", "false");
    await expect(within(outsourced).getByText("This project")).toBeInTheDocument();
    await expect(within(standard).getByText("Organisation")).toBeInTheDocument();
    await expect(canvas.queryByRole("list", { name: "Phases of Standard" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Hide workflow Standard" })).toBeInTheDocument();

    await userEvent.click(standard);
    await expect(standard).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("list", { name: "Phases of Standard" })).toBeInTheDocument();
    await expect(canvas.getByText("Not used yet")).toBeInTheDocument();
    await expect(canvas.queryByRole("list", { name: "Phases of Outsourced work" })).not.toBeInTheDocument();

    await userEvent.click(standard);
    await expect(canvas.queryByRole("list", { name: "Phases of Standard" })).not.toBeInTheDocument();
  },
};

/** A single workflow is shown open, and a workflow with one phase reads "1 step". */
export const OneWorkflowStartsOpen: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildStageWorkflow({ name: "Single", phases: [{ id: "s1", name: "Only", kind: "open", sort_order: 0 }] }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("button", { name: /^Single 1 step/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("list", { name: "Phases of Single" })).toBeInTheDocument();
  },
};
