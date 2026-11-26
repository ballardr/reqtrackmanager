import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { ApproverRoleChips, ApproverRolesField } from "./ApproverRolesField";
import { ROLE_OPTIONS } from "./approvalFixtures";
import { GOVERNANCE_HELP } from "./help";
import type { ApproverRole } from "./types";

/** Holds the chosen roles so a story can tick and clear options. */
function Controlled({ initial, onChange }: { initial: ApproverRole[]; onChange: (next: ApproverRole[]) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <ApproverRolesField
      label="Additional approvers" help={GOVERNANCE_HELP.approvalRoles} options={ROLE_OPTIONS} value={value}
      onChange={(next) => { setValue(next); onChange(next); }}
    />
  );
}

const meta: Meta<typeof Controlled> = {
  title: "Modules/Governance/ApproverRolesField",
  component: Controlled,
  args: { initial: [], onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof Controlled>;

/** The roles are listed under their kind with where each is granted; ticking one reports the new set. */
export const ChoosesRoles: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Additional approvers" }));
    const body = within(document.body);
    await expect(await body.findByText("Project roles")).toBeInTheDocument();
    await expect(body.getByText("Custom roles")).toBeInTheDocument();
    await userEvent.click(body.getByRole("checkbox", { name: "Additional approvers: Quality Lead" }));
    await expect(args.onChange).toHaveBeenLastCalledWith([{ kind: "custom", key: "role-qa" }]);
  },
};

/** A chosen role that is no longer offered stays listed under its key and can be cleared. */
export const RoleNoLongerOffered: Story = {
  args: { initial: [{ kind: "custom", key: "role-gone" }] },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Additional approvers" }));
    const body = within(document.body);
    await expect(await body.findByText("No longer offered")).toBeInTheDocument();
    await userEvent.click(body.getByRole("checkbox", { name: "Additional approvers: role-gone" }));
    await expect(args.onChange).toHaveBeenLastCalledWith([]);
  },
};

export const DarkTheme: Story = { ...ChoosesRoles, globals: { theme: "dark" } };

/** The chips show each role, or "None" for an empty set. */
export const Chips: StoryObj<typeof ApproverRoleChips> = {
  render: () => (
    <div className="stack">
      <ApproverRoleChips roles={[{ kind: "project", key: "project_manager", label: "Project Manager" }]} />
      <ApproverRoleChips roles={[]} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Project Manager")).toBeInTheDocument();
    await expect(canvas.getByText("None")).toBeInTheDocument();
  },
};
