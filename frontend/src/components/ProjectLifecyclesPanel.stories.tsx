import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import {
  buildDecisionLifecycle, buildLifecyclesApi, buildPainPointLifecycle, buildProjectLifecycles,
} from "../testing/lifecycleFixtures";
import { ProjectLifecyclesPanel } from "./ProjectLifecyclesPanel";

/**
 * Project Administration, Lifecycles: a checkbox per optional state of each record type, a required state shown locked,
 * the source of an inherited choice and a preview of the path that Promote follows.
 */
const meta: Meta<typeof ProjectLifecyclesPanel> = {
  title: "Components/ProjectLifecyclesPanel",
  component: ProjectLifecyclesPanel,
  args: { projectId: "project-1", api: buildLifecyclesApi() },
};
export default meta;

type Story = StoryObj<typeof ProjectLifecyclesPanel>;

export const EveryOptionalStateIsOffered: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Use Triaged" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Use Proposed" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Use Under review" })).toBeChecked();
    // An approval state is never offered.
    await expect(canvas.queryByRole("checkbox", { name: "Use Approved" })).not.toBeInTheDocument();
  },
};

export const TurningAStateOffSavesTheChoice: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Use Triaged" }));
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "pain_point", ["triaged"]));
    await expect(await canvas.findByRole("checkbox", { name: "Use Triaged" })).not.toBeChecked();
  },
};

export const TheOrganisationsRequiredStateIsLocked: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle({ required: ["triaged"] })])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Use Triaged" })).toBeDisabled();
    await expect(canvas.getByText("Required by the organisation")).toBeInTheDocument();
  },
};

export const AnExemptProjectMayTurnARequiredStateOff: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle({ required: ["triaged"], exempt: true })])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Use Triaged" })).toBeEnabled();
    await expect(canvas.getByText("Exempt from the organisation's requirement")).toBeInTheDocument();
  },
};

export const ANestedProjectNamesTheInheritedChoice: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([
      buildPainPointLifecycle({ disabled: ["triaged"], own_disabled: null, source: "parent_project" }),
    ], { has_parent: true })),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Inherited from parent project")).toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Use Triaged" })).not.toBeChecked();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Use Triaged" }));
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "pain_point", []));
  },
};

export const GoingBackToTheInheritedChoice: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle({ disabled: ["triaged"] })], { has_parent: true })),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Use inherited setting" }));
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "pain_point", null));
  },
};

export const WithoutPermissionTheChoiceIsReadOnly: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildDecisionLifecycle({ disabled: ["proposed"] })], { can_manage: false })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Use Proposed" })).toBeDisabled();
    await expect(canvas.getByRole("checkbox", { name: "Use Under review" })).toBeDisabled();
  },
};

export const ATypeWithNoOptionalStateIsLeftOut: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([
      buildDecisionLifecycle({ path: buildDecisionLifecycle().path.map((s) => ({ ...s, optional: false })) }),
    ])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/No record type of an enabled module has states/)).toBeInTheDocument();
  },
};

export const ALoadFailureIsStated: Story = {
  args: { api: { ...buildLifecyclesApi(), project: async () => { throw new Error("down"); } } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("could not be loaded");
  },
};
