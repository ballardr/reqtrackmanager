import type { Meta, StoryObj } from "@storybook/react-vite";
import { Bold } from "lucide-react";
import { expect, fn, userEvent, within } from "storybook/test";

import { ToolbarButton } from "./ToolbarButton";

const meta: Meta<typeof ToolbarButton> = { title: "Components/ToolbarButton", component: ToolbarButton };
export default meta;

type Story = StoryObj<typeof ToolbarButton>;

export const IsNamedAndReportsPresses: Story = {
  args: { icon: Bold, label: "Bold", onClick: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Bold" }));
    await expect(args.onClick).toHaveBeenCalledTimes(1);
  },
};

export const ActiveIsPressedAndDisabledIsUnavailable: Story = {
  render: () => (
    <div className="row">
      <ToolbarButton icon={Bold} label="On" active onClick={fn()} />
      <ToolbarButton icon={Bold} label="Unavailable" disabled onClick={fn()} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "On" })).toHaveAttribute("aria-pressed", "true");
    await expect(canvas.getByRole("button", { name: "Unavailable" })).toBeDisabled();
  },
};
