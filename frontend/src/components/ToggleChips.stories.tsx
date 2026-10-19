import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ToggleChips } from "./ToggleChips";

type Kind = "persona" | "stakeholder" | "need";
const OPTIONS = [
  { key: "persona" as const, label: "Personas", count: 3 },
  { key: "stakeholder" as const, label: "Stakeholders", count: 12 },
  { key: "need" as const, label: "Needs" },
];

function Harness({ initial }: { initial: Kind[] }) {
  const [selected, setSelected] = useState<Kind[]>(initial);
  return (
    <ToggleChips
      ariaLabel="Kinds of record"
      options={OPTIONS}
      selected={selected}
      onToggle={(key) => setSelected((s) => (s.includes(key) ? s.filter((k) => k !== key) : [...s, key]))}
    />
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/ToggleChips",
  component: Harness,
  args: { initial: ["persona", "stakeholder", "need"] },
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** Every chip is a toggle button whose pressed state follows the selection. */
export const ClickingAChipTogglesIt: Story = {
  play: async ({ canvasElement }) => {
    const group = within(within(canvasElement).getByRole("group", { name: "Kinds of record" }));
    const stakeholders = group.getByRole("button", { name: /Stakeholders/ });
    await expect(stakeholders).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(stakeholders);
    await expect(stakeholders).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(stakeholders);
    await expect(stakeholders).toHaveAttribute("aria-pressed", "true");
  },
};

/** The count is shown muted after the label; a chip without one shows the label only. */
export const ShowsCounts: Story = {
  args: { initial: ["persona"] },
  play: async ({ canvasElement }) => {
    const group = within(within(canvasElement).getByRole("group", { name: "Kinds of record" }));
    await expect(group.getByRole("button", { name: "Personas 3" })).toHaveAttribute("aria-pressed", "true");
    await expect(group.getByRole("button", { name: "Stakeholders 12" })).toHaveAttribute("aria-pressed", "false");
    await expect(group.getByRole("button", { name: "Needs" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsCounts, globals: { theme: "dark" } };
