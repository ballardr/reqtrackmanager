import type { Meta, StoryObj } from "@storybook/react-vite";
import { Layers } from "lucide-react";
import { expect, fn, userEvent, within } from "storybook/test";

import { expectTextRows } from "../testing/menuRows";
import { GraphNodeBadges } from "./GraphNodeBadges";

const meta: Meta<typeof GraphNodeBadges> = {
  title: "Components/GraphNodeBadges",
  component: GraphNodeBadges,
  args: {
    badges: [
      {
        id: "diagrams",
        label: "Open a state machine diagram",
        icon: <Layers />,
        count: 2,
        items: [
          { id: "a", label: "Order lifecycle", onSelect: fn() },
          { id: "b", label: "Payment lifecycle", onSelect: fn() },
        ],
      },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof GraphNodeBadges>;

/** A badge with several targets opens a list of plain text rows, never a stack of standard buttons; a chosen row closes the list. */
export const SeveralTargetsOpenATextRowList: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Open a state machine diagram" }));
    const list = within(document.body).getByRole("list", { name: "Open a state machine diagram" });
    await expectTextRows(list, 2);

    await userEvent.click(within(list).getByRole("button", { name: "Payment lifecycle" }));
    await expect(args.badges[0].items?.[1].onSelect).toHaveBeenCalledOnce();
    await expect(within(document.body).queryByRole("list", { name: "Open a state machine diagram" })).not.toBeInTheDocument();
  },
};

/** A badge with one target opens it at once, with no list. */
export const OneTargetOpensAtOnce: Story = {
  args: {
    badges: [{ id: "one", label: "Open the diagram", icon: <Layers />, items: [{ id: "a", label: "Order lifecycle", onSelect: fn() }] }],
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Open the diagram" }));
    await expect(args.badges[0].items?.[0].onSelect).toHaveBeenCalledOnce();
    await expect(within(document.body).queryByRole("list")).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { globals: { theme: "dark" } };
