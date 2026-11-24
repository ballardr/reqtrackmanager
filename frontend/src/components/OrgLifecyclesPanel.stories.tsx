import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildLifecyclesApi, buildOrgLifecycle, buildProjectLifecycles } from "../testing/lifecycleFixtures";
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
    const canvas = within(canvasElement);
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
    const canvas = within(canvasElement);
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
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Exempt a project" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const select = await dialog.findByRole("combobox", { name: /Project/ });
    await waitFor(() => expect(within(select).getByRole("option", { name: "TEAM Team project" })).toBeInTheDocument());
    await expect(within(select).queryByRole("option", { name: "SOLO Solo project" })).not.toBeInTheDocument();
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
