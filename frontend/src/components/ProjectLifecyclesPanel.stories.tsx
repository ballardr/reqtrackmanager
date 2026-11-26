import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildApprovalSeparationApi } from "../testing/approvalSeparationFixtures";
import {
  buildDecisionLifecycle, buildLifecyclesApi, buildPainPointLifecycle, buildProjectLifecycles, buildProjectSkip,
} from "../testing/lifecycleFixtures";
import { ProjectLifecyclesPanel } from "./ProjectLifecyclesPanel";

/**
 * Project Administration, Lifecycles: a checkbox per optional state of each record type, a required state shown locked,
 * the source of an inherited choice and a preview of the path that Promote follows.
 */
const meta: Meta<typeof ProjectLifecyclesPanel> = {
  title: "Components/ProjectLifecyclesPanel",
  component: ProjectLifecyclesPanel,
  args: { projectId: "project-1", api: buildLifecyclesApi(), separationApi: buildApprovalSeparationApi() },
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

/** A governance profile's requirement names the profile and stays locked even for a project the organisation exempts. */
export const AGovernanceProfilesRequirementIsNamedAndLocked: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([
      buildPainPointLifecycle({ required: ["triaged"], required_by_profiles: { triaged: ["Regulated delivery"] }, exempt: true }),
    ])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Use Triaged" })).toBeDisabled();
    await expect(canvas.getByText("Required by governance profile: Regulated delivery")).toBeInTheDocument();
  },
};

/** A governance profile's ban on skipping steps names the profile. */
export const AGovernanceProfilesBanOnSkippingIsNamed: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle()], {
      skip: buildProjectSkip({ forbidden: true, forbidden_by_profiles: ["Regulated delivery"] }),
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Allow skipping steps" })).toBeDisabled();
    await expect(canvas.getByText("Not allowed by governance profile: Regulated delivery")).toBeInTheDocument();
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

export const SkippingStepsIsOffByDefaultAndSavedWhenAllowed: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("checkbox", { name: "Allow skipping steps" });
    await expect(box).not.toBeChecked();
    await expect(canvas.queryByText("Custom")).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /inherited|Turn skipping/ })).not.toBeInTheDocument();
    await userEvent.click(box);
    await waitFor(() => expect(args.api!.setProjectSkip).toHaveBeenCalledWith("project-1", true));
    await expect(await canvas.findByRole("checkbox", { name: "Allow skipping steps" })).toBeChecked();
  },
};

export const TheOrganisationsBanLocksSkippingSteps: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle()], {
      skip: buildProjectSkip({ own: true, chosen: true, source: "project", forbidden: true }),
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Allow skipping steps" })).toBeDisabled();
    await expect(canvas.getByText("Not allowed by the organisation")).toBeInTheDocument();
  },
};

export const AnExemptProjectMaySkipSteps: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle()], {
      skip: buildProjectSkip({ own: true, chosen: true, source: "project", allowed: true, exempt: true }),
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("checkbox", { name: "Allow skipping steps" })).toBeEnabled();
    await expect(canvas.getByText("Exempt from the organisation's ban on skipping steps")).toBeInTheDocument();
  },
};

export const ANestedProjectNamesTheInheritedSkipChoice: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle()], {
      has_parent: true, skip: buildProjectSkip({ chosen: true, allowed: true, source: "parent_project" }),
    })),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const section = within(await canvas.findByRole("region", { name: "Skipping steps" }));
    await expect(section.getByText("Inherited from parent project")).toBeInTheDocument();
    await userEvent.click(section.getByRole("checkbox", { name: "Allow skipping steps" }));
    await waitFor(() => expect(args.api!.setProjectSkip).toHaveBeenCalledWith("project-1", false));
  },
};

export const WithoutPermissionSkippingStepsIsReadOnly: Story = {
  args: { api: buildLifecyclesApi(buildProjectLifecycles([buildPainPointLifecycle()], { can_manage: false })) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("checkbox", { name: "Allow skipping steps" })).toBeDisabled();
  },
};
