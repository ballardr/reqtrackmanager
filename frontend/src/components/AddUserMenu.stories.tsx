import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { AddUserMenu } from "./AddUserMenu";

const meta: Meta<typeof AddUserMenu> = {
  title: "Components/AddUserMenu",
  component: AddUserMenu,
  args: { onInvite: fn(), onNewUser: fn() },
};
export default meta;

type Story = StoryObj<typeof AddUserMenu>;

/** One button; the two ways to add a person are its menu items, each calling its own handler. */
export const OffersInviteAndNewUser: Story = {
  play: async ({ canvasElement, args }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Add user" });
    await userEvent.click(trigger);
    const menu = within(document.body).getByRole("menu", { name: "Add user" });
    await expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Invite user", "New user"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Invite user" }));
    await expect(args.onInvite).toHaveBeenCalledTimes(1);
    await userEvent.click(trigger);
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "New user" }));
    await expect(args.onNewUser).toHaveBeenCalledTimes(1);
  },
};
