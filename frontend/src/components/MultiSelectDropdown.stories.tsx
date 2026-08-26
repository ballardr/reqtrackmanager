import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { MultiSelectDropdown } from "./MultiSelectDropdown";

const meta: Meta<typeof MultiSelectDropdown> = {
  title: "Components/MultiSelectDropdown",
  component: MultiSelectDropdown,
  args: {
    triggerLabel: "Alex Morgan's roles",
    options: [
      { value: "member", label: "Member", checked: true, optionLabel: "Revoke Member from Alex Morgan", onToggle: fn() },
      {
        value: "project_creator",
        label: "Project creator",
        checked: false,
        optionLabel: "Grant Project creator to Alex Morgan",
        onToggle: fn(),
      },
      { value: "org_admin", label: "Org admin", checked: true, optionLabel: "Revoke Org admin from Alex Morgan", onToggle: fn() },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof MultiSelectDropdown>;

/** Closed by default, showing every currently-checked option's own label as
 * its summary text — visually a single dropdown, matching every other
 * `<select className="input">` in the app, even though more than one value
 * can be checked at once. */
export const ClosedShowsCheckedOptionsAsSummary: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Alex Morgan's roles" });
    await expect(trigger).toHaveTextContent("Member, Org admin");
    await expect(within(document.body).queryByRole("group")).not.toBeInTheDocument();
  },
};

/** Clicking the trigger reveals every option as its own checkbox, checked
 * or not, inside a `Popover` — this doesn't replace the summary with a
 * single choice, it opens the whole set. */
export const OpensToShowAllOptions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));

    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await expect(within(group).getByRole("checkbox", { name: "Revoke Member from Alex Morgan" })).toBeChecked();
    await expect(within(group).getByRole("checkbox", { name: "Grant Project creator to Alex Morgan" })).not.toBeChecked();
    await expect(within(group).getByRole("checkbox", { name: "Revoke Org admin from Alex Morgan" })).toBeChecked();
  },
};

/** Toggling one option calls that option's own `onToggle` immediately —
 * there's no separate "apply"/"save" step, matching every other immediate
 * toggle in the app (Principle 7, feedback on every mutation is the
 * caller's job, not this component's). */
export const TogglingAnOptionFiresItsOwnCallback: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });

    await userEvent.click(within(group).getByRole("checkbox", { name: "Grant Project creator to Alex Morgan" }));
    await expect(args.options[1].onToggle).toHaveBeenCalledOnce();
    await expect(args.options[0].onToggle).not.toHaveBeenCalled();
  },
};

/** Shared `Popover` outside-click-close behaviour — this component doesn't
 * reimplement it. */
export const OutsideClickClosesTheList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    await expect(within(document.body).getByRole("group")).toBeInTheDocument();

    await userEvent.click(document.body);
    await expect(within(document.body).queryByRole("group")).not.toBeInTheDocument();
  },
};

/** A `disabled` option (e.g. a user's own currently-held role, which this
 * app's org-role control never lets someone revoke from themselves) stays
 * visible and checked, just not toggleable. */
export const DisabledOption: Story = {
  args: {
    options: [
      {
        value: "org_admin",
        label: "Org admin",
        checked: true,
        disabled: true,
        title: "You cannot change your own organisation role here.",
        optionLabel: "Revoke Org admin from Alex Morgan",
        onToggle: fn(),
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    await expect(within(group).getByRole("checkbox", { name: "Revoke Org admin from Alex Morgan" })).toBeDisabled();
  },
};

/** No option checked shows `emptyLabel` instead of an empty trigger. */
export const EmptySelectionShowsEmptyLabel: Story = {
  args: {
    emptyLabel: "No roles",
    options: [
      { value: "member", label: "Member", checked: false, optionLabel: "Grant Member to Alex Morgan", onToggle: fn() },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toHaveTextContent("No roles");
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
