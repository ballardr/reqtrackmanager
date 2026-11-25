import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { TreeToggle, TreeToggleGap } from "./TreeToggle";

function Harness({ initial }: { initial: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="row" style={{ gap: "var(--space-1)" }}>
      <TreeToggle expanded={open} name="Acme" onToggle={() => setOpen((o) => !o)} />
      <span>Acme</span>
      <TreeToggleGap />
      <span>Leaf</span>
    </div>
  );
}

const meta: Meta<typeof Harness> = { title: "Components/TreeToggle", component: Harness, args: { initial: true } };
export default meta;

type Story = StoryObj<typeof Harness>;

/** Plain disclosure control: named from the node, announces its state, flips on press and on Enter. */
export const TogglesAndAnnouncesState: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const open = canvas.getByRole("button", { name: "Collapse Acme" });
    await expect(open).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(open);
    const closed = canvas.getByRole("button", { name: "Expand Acme" });
    await expect(closed).toHaveAttribute("aria-expanded", "false");
    closed.focus();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("button", { name: "Collapse Acme" })).toBeInTheDocument();
  },
};

/** No border or background of a button, and a hit area large enough to touch. */
export const IsPlainWithATouchSizedTarget: Story = {
  play: async ({ canvasElement }) => {
    const toggle = within(canvasElement).getByRole("button", { name: "Collapse Acme" });
    await expect(toggle).not.toHaveClass("btn");
    await expect(getComputedStyle(toggle).borderTopStyle).toBe("none");
    await expect(toggle.getBoundingClientRect().width).toBeGreaterThanOrEqual(24);
    await expect(toggle.getBoundingClientRect().height).toBeGreaterThanOrEqual(24);
  },
};

export const Collapsed: Story = { args: { initial: false } };
export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };

/** In a persistent tree the chevron names itself in the shared tooltip, never in a native `title`; a picker turns it off. */
export const NamesItselfInTheSharedTooltip: Story = {
  play: async ({ canvasElement }) => {
    const toggle = within(canvasElement).getByRole("button", { name: "Collapse Acme" });
    await expect(toggle).not.toHaveAttribute("title");
    await userEvent.hover(toggle);
    await expect(await within(document.body).findByRole("tooltip", { hidden: true })).toHaveTextContent("Collapse Acme");
  },
};

export const WithoutTooltipInAPicker: Story = {
  render: () => <TreeToggle expanded name="Acme" onToggle={() => undefined} tooltip={false} />,
  play: async ({ canvasElement }) => {
    const toggle = within(canvasElement).getByRole("button", { name: "Collapse Acme" });
    await userEvent.hover(toggle);
    await expect(within(document.body).queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
    await expect(toggle).not.toHaveAttribute("title");
  },
};
