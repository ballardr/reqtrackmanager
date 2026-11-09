import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { DisclosureRow } from "./DisclosureRow";

/** One collapsible row of a stacked list: the toggle names and summarises the item, its actions sit beside it. */
const meta: Meta<typeof DisclosureRow> = {
  title: "Components/DisclosureRow",
  component: DisclosureRow,
};
export default meta;

type Story = StoryObj<typeof DisclosureRow>;

function Interactive({ startCollapsed }: { startCollapsed: boolean }) {
  const [collapsed, setCollapsed] = useState(startCollapsed);
  return (
    <DisclosureRow
      title="Outsourced work" summary="2 steps" collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)}
      actions={<button className="btn" aria-label="Edit workflow Outsourced work">Edit</button>}
    >
      <div>Scoping, then Awarded.</div>
    </DisclosureRow>
  );
}

/** Closed: only the name and summary show; the action is reachable and the detail is not rendered. */
export const ClosedShowsNameSummaryAndActions: Story = {
  render: () => <Interactive startCollapsed />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("button", { name: "Outsourced work 2 steps" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByText("Scoping, then Awarded.")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit workflow Outsourced work" })).toBeInTheDocument();
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByText("Scoping, then Awarded.")).toBeInTheDocument();
  },
};

/** Open, and a long name does not push the actions off the row. */
export const OpenWithALongName: Story = {
  render: () => (
    <DisclosureRow
      title="A workflow whose name is long enough to need to wrap or truncate inside a narrow column of the page"
      summary="12 steps" collapsed={false} onToggle={() => {}} actions={<button className="btn">Delete</button>}
    >
      <div>Detail</div>
    </DisclosureRow>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Delete" })).toBeVisible();
  },
};
