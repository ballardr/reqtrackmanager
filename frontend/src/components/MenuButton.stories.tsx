import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { MenuButton } from "./MenuButton";

const meta: Meta<typeof MenuButton> = {
  title: "Components/MenuButton",
  component: MenuButton,
  args: {
    label: "New",
    primary: true,
    items: [
      { label: "Persona", onSelect: fn() },
      { label: "Stakeholder", onSelect: fn() },
      { label: "Stakeholder Need", onSelect: fn() },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof MenuButton>;

/** The button shows its word, and clicking it reveals every choice as a `menuitem`. */
export const OpensMenuOfChoices: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "New" });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = within(document.body).getByRole("menu", { name: "New" });
    for (const name of ["Persona", "Stakeholder", "Stakeholder Need"]) {
      await expect(within(menu).getByRole("menuitem", { name })).toBeInTheDocument();
    }
  },
};

/** Choosing an item closes the menu, then calls that item's `onSelect`. */
export const SelectingAnItemClosesAndCalls: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "New" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Stakeholder" }));
    await expect(args.items[1].onSelect).toHaveBeenCalledTimes(1);
    await expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument();
  },
};

/** A disabled button cannot be opened. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "New" });
    await expect(trigger).toBeDisabled();
  },
};
