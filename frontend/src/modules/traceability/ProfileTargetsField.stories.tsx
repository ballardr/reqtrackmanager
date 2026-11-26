import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";
import { useState } from "react";

import { api } from "../../api/client";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { ORG_ID, ORG_PROJECTS } from "./profileFixtures";
import { ProfileTargetsField } from "./ProfileTargetsField";
import type { ProfileTarget, ProfileTargetKind } from "./types";

/** Holds the field's value so a story can edit it, and reports every change to `onChange`. */
function Harness({ initialKind, initialTargets, onChange, projectName }: {
  initialKind: ProfileTargetKind; initialTargets: ProfileTarget[]; onChange: (kind: ProfileTargetKind, targets: ProfileTarget[]) => void; projectName?: string;
}) {
  const [kind, setKind] = useState(initialKind);
  const [targets, setTargets] = useState(initialTargets);
  return (
    <ProfileTargetsField
      orgId={ORG_ID} targetKind={kind} targets={targets} names={projectName ? { "proj-1": projectName } : {}}
      onChange={(k, t) => { setKind(k); setTargets(t); onChange(k, t); }}
    />
  );
}

const meta: Meta<typeof Harness> = {
  title: "Modules/Governance/ProfileTargetsField",
  component: Harness,
  args: { initialKind: "all_projects", initialTargets: [], onChange: fn() },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_PROJECTS);
  },
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** For every project no project picker is drawn. */
export const AllProjects: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Reaches" })).toHaveValue("all_projects");
    await expect(canvas.queryByRole("button", { name: "Projects" })).not.toBeInTheDocument();
  },
};

/** Choosing selected projects reveals the picker; choosing a project adds a row with its nested-projects choice. */
export const SelectingProjects: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Reaches" }), "selected_projects");
    await expect(args.onChange).toHaveBeenLastCalledWith("selected_projects", []);
    await userEvent.click(await canvas.findByRole("button", { name: "Projects" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Reach HBR Harbour crossing" }));
    await waitFor(() => expect(args.onChange).toHaveBeenLastCalledWith("selected_projects", [{ project_id: "proj-1", include_children: false }]));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Includes nested projects of HBR Harbour crossing" }));
    await waitFor(() => expect(args.onChange).toHaveBeenLastCalledWith("selected_projects", [{ project_id: "proj-1", include_children: true }]));
  },
};

/** A chosen project can be removed from the row. */
export const RemovingAProject: Story = {
  args: { initialKind: "selected_projects", initialTargets: [{ project_id: "proj-1", include_children: true }] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove HBR Harbour crossing" }));
    await waitFor(() => expect(args.onChange).toHaveBeenLastCalledWith("selected_projects", []));
  },
};

/** A long project name is cut inside its row; the checkbox and the remove control stay on the row. */
export const LongText: Story = {
  render: (args) => (
    <TextStress render={(long) => (
      <Harness {...args} initialKind="selected_projects" initialTargets={[{ project_id: "proj-1", include_children: true }]} projectName={stressText(long, "HBR Harbour crossing")} />
    )} />
  ),
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll("li[data-stress-row]").length).toBe(2));
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...SelectingProjects, play: undefined, globals: { theme: "dark" } };
