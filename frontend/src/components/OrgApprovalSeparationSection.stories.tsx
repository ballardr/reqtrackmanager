import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildApprovalSeparationApi, buildOrgSeparation, buildProjectSeparations } from "../testing/approvalSeparationFixtures";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { OrgApprovalSeparationSection } from "./OrgApprovalSeparationSection";

/**
 * The Approval section of the organisation Lifecycles group: whether every project needs a separate approver for a
 * record type, and the projects exempt from the requirement.
 */
const projects = [
  { id: "p-solo", name: "Solo project", code: "SOLO" },
  { id: "p-team", name: "Team project", code: "TEAM" },
];

const meta: Meta<typeof OrgApprovalSeparationSection> = {
  title: "Components/OrgApprovalSeparationSection",
  component: OrgApprovalSeparationSection,
  args: {
    organizationId: "org-1",
    api: buildApprovalSeparationApi(buildProjectSeparations([]), [buildOrgSeparation()]),
    loadProjects: async () => projects,
  },
};
export default meta;

type Story = StoryObj<typeof OrgApprovalSeparationSection>;

export const RequiringASeparateApproverInEveryProject: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Change request approval" });
    await expect(select).toHaveValue("decides");
    await expect(canvas.queryByRole("button", { name: "Exempt a project" })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "required");
    await waitFor(() => expect(args.api!.setRequired).toHaveBeenCalledWith("org-1", "change_request", true));
    await expect(await canvas.findByRole("combobox", { name: "Change request approval" })).toHaveValue("required");
  },
};

export const ExemptingAProjectFromTheRequirement: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([]), [buildOrgSeparation({ required: true })]),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No project is exempt.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Exempt a project" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByRole("combobox", { name: /Project/ }), "p-solo");
    await userEvent.click(dialog.getByRole("button", { name: "Exempt a project" }));
    await waitFor(() => expect(args.api!.addExemption).toHaveBeenCalledWith("org-1", "change_request", "p-solo", false));
    await expect(await canvas.findByText("SOLO Solo project")).toBeInTheDocument();
  },
};

export const RemovingAnExemption: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([]), [buildOrgSeparation({
      required: true,
      exemptions: [{ project_id: "p-solo", project_name: "Solo project", project_code: "SOLO", include_children: false }],
    })]),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove the exemption of Solo project" }));
    await waitFor(() => expect(args.api!.removeExemption).toHaveBeenCalledWith("org-1", "change_request", "p-solo"));
  },
};

export const LongText: Story = {
  render: (args) => (
    <TextStress
      render={(long) => (
        <OrgApprovalSeparationSection
          {...args}
          api={buildApprovalSeparationApi(buildProjectSeparations([]), [buildOrgSeparation({
            required: true,
            exemptions: [1, 2, 3].map((n) => ({
              project_id: `p-${n}`, project_name: stressText(long, `Project ${n}`), project_code: stressText(long, `P${n}`, "code"),
              include_children: n === 2,
            })),
          })])}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findAllByText(/P1/);
    await expectStressStable(canvasElement);
  },
};
