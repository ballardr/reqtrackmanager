import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { CommentModeToggle } from "./CommentModeToggle";

function Harness() {
  const [on, setOn] = useState(false);
  return <CommentModeToggle on={on} onChange={setOn} />;
}

/** The toolbar switch for a canvas's comment mode; its help is the button's own tooltip. */
const meta: Meta<typeof Harness> = { title: "Components/CommentModeToggle", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const TogglesAndExplainsBothStatesOnTheButton: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Comment" });
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect(within(canvasElement).queryByRole("button", { name: /^Help:/ })).not.toBeInTheDocument();
    await userEvent.hover(button);
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("On:");
    await expect(tip).toHaveTextContent("Off:");
    await userEvent.click(button);
    await expect(button).toHaveAttribute("aria-pressed", "true");
  },
};
