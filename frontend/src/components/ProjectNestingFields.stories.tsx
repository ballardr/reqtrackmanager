import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { useState } from "react";

import type { ProjectRole, ProjectRoleInheritanceMode } from "../api/types";
import { ProjectNestingFields } from "./ProjectNestingFields";

const OPTIONS = [{ id: "p1", name: "Programme" }, { id: "p2", name: "Portfolio" }];

function Harness({ initialParent = "", initialMode = "none", onModeChange }: {
  initialParent?: string; initialMode?: ProjectRoleInheritanceMode; onModeChange?: (m: ProjectRoleInheritanceMode) => void;
}) {
  const [parent, setParent] = useState(initialParent);
  const [mode, setMode] = useState<ProjectRoleInheritanceMode>(initialMode);
  const [role, setRole] = useState<ProjectRole>("project_manager");
  return (
    <ProjectNestingFields
      parentProjectId={parent} parentOptions={OPTIONS} onParentChange={setParent}
      mode={mode} onModeChange={(m) => { onModeChange?.(m); setMode(m); }}
      filterRole={role} onFilterRoleChange={setRole}
    />
  );
}

const meta: Meta<typeof Harness> = { title: "Components/ProjectNestingFields", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

/** With no parent only the parent picker shows. */
export const TopLevel: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Parent project")).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Inherit access from parent")).not.toBeInTheDocument();
  },
};

/** A parent brings the inheritance choice; the mirrored role shows only for the role-mirroring mode. */
export const WithParent: Story = {
  args: { initialParent: "p1" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Inherit access from parent")).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Role to mirror")).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Inherit access from parent"), "mirror_role");
    await expect(canvas.getByLabelText("Role to mirror")).toBeInTheDocument();
  },
};

/** Changing the parent resets an elevated mode so it is confirmed again for the new parent. */
export const ChangingParentResetsAnElevatedMode: Story = {
  args: { initialParent: "p1", initialMode: "mirror_all", onModeChange: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Parent project"), "p2");
    await expect(args.onModeChange).toHaveBeenCalledWith("none");
  },
};
