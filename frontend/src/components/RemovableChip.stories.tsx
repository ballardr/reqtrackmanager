import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { orphanedControlViolations } from "../testing/orphanedControls";
import { RemovableChip } from "./RemovableChip";

/** A removable value (a pending upload): text wraps, the remove control stays beside it. Not a pill. */
const meta: Meta<typeof RemovableChip> = {
  title: "Components/RemovableChip",
  component: RemovableChip,
  args: { label: "design-review.pdf", removeLabel: "Remove design-review.pdf", onRemove: fn() },
};
export default meta;

type Story = StoryObj<typeof RemovableChip>;

export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Remove design-review.pdf" }));
    await expect(args.onRemove).toHaveBeenCalled();
  },
};

export const WithoutRemoveControl: Story = { args: { onRemove: undefined } };

/** A very long file name wraps inside the chip and the remove button does not move. */
export const LongNameKeepsTheButtonBeside: Story = {
  args: { label: "quarterly-safety-board-sign-off-evidence-pack-final-reviewed-v12-FINAL-really-final.pdf" },
  decorators: [(Story) => <div style={{ width: 240 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector<HTMLElement>(".chip")!;
    const button = within(canvasElement).getByRole("button").getBoundingClientRect();
    await expect(button.right).toBeLessThanOrEqual(chip.getBoundingClientRect().right + 1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};
