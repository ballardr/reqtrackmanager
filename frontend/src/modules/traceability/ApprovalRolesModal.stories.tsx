import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApprovalRolesModal } from "./ApprovalRolesModal";
import { ROLE_OPTIONS } from "./approvalFixtures";

const meta: Meta<typeof ApprovalRolesModal> = {
  title: "Modules/Governance/ApprovalRolesModal",
  component: ApprovalRolesModal,
  args: {
    typeLabel: "Decision",
    options: ROLE_OPTIONS,
    initial: [{ kind: "custom", key: "role-qa" }],
    onSave: fn(async () => undefined),
    onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ApprovalRolesModal>;

const dialog = () => within(document.body).findByRole("dialog", { name: "Approvers: Decision" });

/** Adding a role and saving sends the whole chosen set. */
export const SavesTheChosenRoles: Story = {
  play: async ({ args }) => {
    const modal = within(await dialog());
    await userEvent.click(modal.getByRole("button", { name: "Additional approvers" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Additional approvers: Project Manager" }));
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith([
      { kind: "custom", key: "role-qa" }, { kind: "project", key: "project_manager" },
    ]));
  },
};

/** A project that has its own roles can return to the inherited value, which saves `null`. */
export const UsesTheInheritedValue: Story = {
  args: { allowFollowParent: true, own: true, inheritedFrom: "Programme Alpha" },
  play: async ({ args }) => {
    const modal = within(await dialog());
    await userEvent.click(modal.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(null));
  },
};

/** A project with no row of its own names the tier it follows and offers no way back. */
export const NamesTheInheritedTier: Story = {
  args: { allowFollowParent: true, own: false, inheritedFrom: "Programme Alpha", initial: [] },
  play: async () => {
    const modal = within(await dialog());
    await expect(modal.getByText("Inherited from Programme Alpha")).toBeInTheDocument();
    await expect(modal.queryByRole("button", { name: "Use inherited value" })).toBeNull();
  },
};

/** A failed save stays in the dialog with the reason. */
export const ShowsAFailedSave: Story = {
  args: { onSave: fn(async () => { throw new Error("That role cannot approve."); }) },
  play: async () => {
    const modal = within(await dialog());
    await userEvent.click(modal.getByRole("button", { name: "Save" }));
    await expect(await modal.findByText("That role cannot approve.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...SavesTheChosenRoles, globals: { theme: "dark" } };
