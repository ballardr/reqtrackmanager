import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { ChoiceButtons } from "./ChoiceButtons";

const OPTIONS = [{ value: "left", label: "Left" }, { value: "center", label: "Centre" }, { value: "right", label: "Right" }];

function Harness({ initial, onPick, disabled }: { initial: string; onPick?: (v: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <ChoiceButtons
      label="Alignment" value={value} options={OPTIONS} disabled={disabled} help="Where text sits across a cell."
      onChange={(next) => { setValue(next); onPick?.(next); }}
    />
  );
}

/** An exclusive choice of a few short values as a radio group of buttons. */
const meta: Meta<typeof Harness> = { title: "Components/ChoiceButtons", component: Harness, args: { initial: "left" } };
export default meta;

type Story = StoryObj<typeof Harness>;

export const TheChosenButtonIsChecked: Story = {
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    await expect(within(group).getByRole("radio", { name: "Left" })).toHaveAttribute("aria-checked", "true");
    await expect(within(group).getByRole("radio", { name: "Right" })).toHaveAttribute("aria-checked", "false");
  },
};

export const APressChoosesAndReports: Story = {
  args: { onPick: fn() },
  play: async ({ canvasElement, args }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    await userEvent.click(within(group).getByRole("radio", { name: "Centre" }));
    await expect(args.onPick).toHaveBeenCalledWith("center");
    await expect(within(group).getByRole("radio", { name: "Centre" })).toHaveAttribute("aria-checked", "true");
  },
};

export const ArrowKeysMoveTheChoiceAndWrap: Story = {
  args: { initial: "right" },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    within(group).getByRole("radio", { name: "Right" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(within(group).getByRole("radio", { name: "Left" })).toHaveAttribute("aria-checked", "true");
    await expect(within(group).getByRole("radio", { name: "Left" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(within(group).getByRole("radio", { name: "Right" })).toHaveAttribute("aria-checked", "true");
  },
};

/** A value that is not an option leaves none checked, and the first button is still the one tab stop. */
export const AnUnknownValueChecksNothingButStaysReachable: Story = {
  args: { initial: "justify" },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    for (const radio of within(group).getAllByRole("radio")) await expect(radio).toHaveAttribute("aria-checked", "false");
    await expect(within(group).getByRole("radio", { name: "Left" })).toHaveAttribute("tabindex", "0");
  },
};

export const DisabledButtonsDoNotChoose: Story = {
  args: { disabled: true, onPick: fn() },
  play: async ({ canvasElement, args }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    await userEvent.click(within(group).getByRole("radio", { name: "Right" }));
    await expect(args.onPick).not.toHaveBeenCalled();
  },
};
