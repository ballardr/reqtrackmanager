import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { TagChip } from "./TagChip";

/** A tag on a record: the tag's own colour marks the left edge, the label keeps the theme's text colour. */
const meta: Meta<typeof TagChip> = {
  title: "Components/TagChip",
  component: TagChip,
};
export default meta;

type Story = StoryObj<typeof TagChip>;

export const WithColour: Story = { args: { tag: { name: "Safety", colour: "#c53030" } } };

export const WithoutColour: Story = { args: { tag: { name: "Release 2", colour: null } } };

/** A long name wraps inside the chip rather than stretching its row. */
export const LongName: Story = {
  args: { tag: { name: "Regulatory submission for the northern territories, second round", colour: "#2b6cb0" } },
  decorators: [(Story) => <div style={{ maxWidth: 220 }}><Story /></div>],
};

export const Removable: Story = {
  args: { tag: { name: "Safety", colour: "#c53030" }, removeLabel: "Remove tag Safety", onRemove: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Remove tag Safety" }));
    await expect(args.onRemove).toHaveBeenCalled();
  },
};

/** A stored value that is not plain hex never reaches the style attribute: the chip shows no colour. */
export const AnUnsafeColourIsIgnored: Story = {
  args: { tag: { name: "Odd", colour: "#2b6cb0;background:url(//evil.example/x)" } },
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector(".tag-chip") as HTMLElement;
    await expect(chip.getAttribute("style")).toBeNull();
  },
};
