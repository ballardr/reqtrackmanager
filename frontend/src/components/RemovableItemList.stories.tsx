import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { orphanedControlViolations } from "../testing/orphanedControls";
import { RemovableItemList, type RemovableItem } from "./RemovableItemList";

const items = (n: number): RemovableItem[] =>
  Array.from({ length: n }, (_, i) => ({ id: `p${i + 1}`, content: <span>Person {i + 1}</span>, removeLabel: `Remove Person ${i + 1}` }));

const meta: Meta<typeof RemovableItemList> = {
  title: "Components/RemovableItemList",
  component: RemovableItemList,
  args: { items: items(3), onRemove: fn(), noun: "participants", modalTitle: "Participants" },
};
export default meta;

type Story = StoryObj<typeof RemovableItemList>;

/** Each chip has a named "x" that only asks: `onRemove` receives the item's id (the caller confirms). */
export const RemoveAsksTheCaller: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove Person 2" }));
    await expect(args.onRemove).toHaveBeenCalledWith("p2");
  },
};

/** Without `onRemove` the list is read-only: no "x" buttons. */
export const ReadOnly: Story = {
  args: { onRemove: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

/** A long list is capped; the full list, with working "x" buttons, is in the "Show all" modal. */
export const LongListIsCapped: Story = {
  args: { items: items(13) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(10);
    await userEvent.click(canvas.getByRole("button", { name: "Show all 13 participants" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Participants" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove Person 13" }));
    await expect(args.onRemove).toHaveBeenCalledWith("p13");
  },
};

export const LightTheme: Story = { ...RemoveAsksTheCaller, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RemoveAsksTheCaller, globals: { theme: "dark" } };

/** A very long name keeps its "x" on the same chip. */
export const LongNameKeepsTheRemoveButtonBeside: Story = {
  args: {
    items: [{ id: "long", content: <span>{"Dr Alexandra Featherstonehaugh-Montgomery of the Northern Safety Board ".repeat(2)}</span>, removeLabel: "Remove long" }],
  },
  decorators: [(Story) => <div style={{ width: 300 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector<HTMLElement>(".removable-item")!;
    const button = within(canvasElement).getByRole("button", { name: "Remove long" }).getBoundingClientRect();
    await expect(button.right).toBeLessThanOrEqual(chip.getBoundingClientRect().right + 1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};
