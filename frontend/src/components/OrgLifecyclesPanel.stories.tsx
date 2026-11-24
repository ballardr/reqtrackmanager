import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildApprovalSeparationApi } from "../testing/approvalSeparationFixtures";
import { buildLifecyclesApi, buildOrgLifecycle, buildOrgSkip, buildProjectLifecycles } from "../testing/lifecycleFixtures";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { OrgLifecyclesPanel } from "./OrgLifecyclesPanel";

/**
 * Organisation Administration, Lifecycles: a checkbox per optional state that makes it required in every project, and
 * the projects that are exempt from the requirement.
 */
const projects = [
  { id: "p-solo", name: "Solo project", code: "SOLO" },
  { id: "p-team", name: "Team project", code: "TEAM" },
];

const meta: Meta<typeof OrgLifecyclesPanel> = {
  title: "Components/OrgLifecyclesPanel",
  component: OrgLifecyclesPanel,
  args: {
    organizationId: "org-1",
    api: buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle()]),
    loadProjects: async () => projects,
    separationApi: buildApprovalSeparationApi(),
  },
};
export default meta;

type Story = StoryObj<typeof OrgLifecyclesPanel>;

export const RequiringAState: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Require Triaged" }));
    await waitFor(() => expect(args.api!.setRequired).toHaveBeenCalledWith("org-1", "pain_point", ["triaged"]));
    await expect(await canvas.findByRole("checkbox", { name: "Require Triaged" })).toBeChecked();
  },
};

export const ExemptingAProjectAndItsNestedProjects: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(await within(canvasElement).findByRole("region", { name: "Pain Point" }));
    await expect(await canvas.findByText("No project is exempt.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Exempt a project" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByRole("combobox", { name: /Project/ }), "p-solo");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Include nested projects" }));
    await userEvent.click(dialog.getByRole("button", { name: "Exempt a project" }));
    await waitFor(() => expect(args.api!.addExemption).toHaveBeenCalledWith("org-1", "pain_point", "p-solo", true));
    await expect(await canvas.findByText("SOLO Solo project")).toBeInTheDocument();
    await expect(canvas.getByText("Includes nested projects")).toBeInTheDocument();
  },
};

export const RemovingAnExemption: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle({
      required: ["triaged"],
      exemptions: [{ project_id: "p-solo", project_name: "Solo project", project_code: "SOLO", include_children: false }],
    })]),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(await within(canvasElement).findByRole("region", { name: "Pain Point" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Remove the exemption of Solo project" }));
    await waitFor(() => expect(args.api!.removeExemption).toHaveBeenCalledWith("org-1", "pain_point", "p-solo"));
    await expect(await canvas.findByText("No project is exempt.")).toBeInTheDocument();
  },
};

export const AProjectAlreadyExemptIsNotOffered: Story = {
  args: {
    api: buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle({
      exemptions: [{ project_id: "p-solo", project_name: "Solo project", project_code: "SOLO", include_children: false }],
    })]),
  },
  play: async ({ canvasElement }) => {
    const section = within(await within(canvasElement).findByRole("region", { name: "Pain Point" }));
    await userEvent.click(await section.findByRole("button", { name: "Exempt a project" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const select = await dialog.findByRole("combobox", { name: /Project/ });
    await waitFor(() => expect(within(select).getByRole("option", { name: "TEAM Team project" })).toBeInTheDocument());
    await expect(within(select).queryByRole("option", { name: "SOLO Solo project" })).not.toBeInTheDocument();
  },
};

const SOLO_EXEMPTION = { project_id: "p-solo", project_name: "Solo project", project_code: "SOLO", include_children: false };

export const ForbiddingSkippedSteps: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Do not allow skipping steps" }));
    await waitFor(() => expect(args.api!.setSkipForbidden).toHaveBeenCalledWith("org-1", true));
    await expect(await canvas.findByRole("checkbox", { name: "Do not allow skipping steps" })).toBeChecked();
  },
};

export const ExemptingAProjectFromTheBanOnSkippedSteps: Story = {
  args: { api: buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle()], buildOrgSkip({ forbidden: true })) },
  play: async ({ canvasElement, args }) => {
    const section = within(await within(canvasElement).findByRole("region", { name: "Skipping steps" }));
    await userEvent.click(await section.findByRole("button", { name: "Exempt a project" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Exempt a project from the ban on skipping steps" }));
    await userEvent.selectOptions(await dialog.findByRole("combobox", { name: /Project/ }), "p-team");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Include nested projects" }));
    await userEvent.click(dialog.getByRole("button", { name: "Exempt a project" }));
    await waitFor(() => expect(args.api!.addSkipExemption).toHaveBeenCalledWith("org-1", "p-team", true));
    await expect(await section.findByText("SOLO Solo project")).toBeInTheDocument();
  },
};

export const RemovingAnExemptionFromTheBanOnSkippedSteps: Story = {
  args: { api: buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle()], buildOrgSkip({ forbidden: true, exemptions: [SOLO_EXEMPTION] })) },
  play: async ({ canvasElement, args }) => {
    const section = within(await within(canvasElement).findByRole("region", { name: "Skipping steps" }));
    await userEvent.click(await section.findByRole("button", { name: "Remove the exemption of Solo project" }));
    await waitFor(() => expect(args.api!.removeSkipExemption).toHaveBeenCalledWith("org-1", "p-solo"));
    await expect(await section.findByText("No project is exempt.")).toBeInTheDocument();
  },
};

export const LongText: Story = {
  render: (args) => (
    <TextStress
      render={(long) => (
        <OrgLifecyclesPanel
          {...args}
          api={buildLifecyclesApi(buildProjectLifecycles([]), [buildOrgLifecycle({
            exemptions: [1, 2, 3].map((n) => ({
              project_id: `p-${n}`, project_name: stressText(long, `Project ${n}`), project_code: stressText(long, `P${n}`, "code"),
              include_children: n === 2,
            })),
          })], buildOrgSkip({
            forbidden: true,
            exemptions: [4, 5].map((n) => ({
              project_id: `p-${n}`, project_name: stressText(long, `Project ${n}`), project_code: stressText(long, `P${n}`, "code"),
              include_children: n === 5,
            })),
          }))}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findAllByText(/P1/);
    await expectStressStable(canvasElement);
  },
};
