import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { CanvasModeToggle } from "./CanvasModeToggle";

function Harness({ disabled }: { disabled?: boolean }) {
  const [on, setOn] = useState(false);
  return <CanvasModeToggle label="Draw" help={"On: a click draws.\nOff: a click selects."} on={on} onChange={setOn} disabled={disabled} />;
}

/** The toolbar switch every canvas mode shares (Comment, Note); its help is the button's own tooltip, one line per state. */
const meta: Meta<typeof Harness> = { title: "Components/CanvasModeToggle", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const TogglesAndExplainsBothStatesOnTheButton: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Draw" });
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect(within(canvasElement).queryByRole("button", { name: /^Help:/ })).not.toBeInTheDocument();
    await userEvent.hover(button);
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Off: a click selects.");
    await userEvent.click(button);
    await expect(button).toHaveAttribute("aria-pressed", "true");
  },
};

export const DisabledCannotBeTurnedOn: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Draw" })).toBeDisabled();
  },
};
