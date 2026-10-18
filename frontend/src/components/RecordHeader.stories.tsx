import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import { Badge } from "./Badge";
import { RecordHeader } from "./RecordHeader";
import { orphanedControlViolations } from "../testing/orphanedControls";

const meta: Meta<typeof RecordHeader> = {
  title: "Components/RecordHeader",
  component: RecordHeader,
  decorators: [(Story) => <MemoryRouter><div style={{ maxWidth: 720 }}><Story /></div></MemoryRouter>],
  args: {
    recordLabel: "Persona",
    title: "Ada Lovelace",
    code: "PER-001",
    subtitle: "Analyst · v3",
    back: { to: "/personas", label: "← Personas" },
    badges: <><Badge>Project</Badge><Badge tone="accent">Active</Badge></>,
    onEdit: fn(),
    transitions: <button className="btn btn-danger">Retire</button>,
    actions: [{ label: "Archive", danger: true, onSelect: fn() }],
  },
};
export default meta;
type Story = StoryObj<typeof RecordHeader>;

/** Edit is a visible pencil; everything else sits behind the "{Record} actions" menu. */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    await expect(args.onEdit).toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Persona actions" }));
    await expect(within(document.body).getByRole("menuitem", { name: "Archive" })).toBeInTheDocument();
  },
};

/** A single object action still gets the menu, so its position never depends on permissions. */
export const SingleActionStillUsesTheMenu: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Persona actions" })).toBeInTheDocument();
  },
};

/** No permissions: no Edit, no menu, no empty kebab. */
export const NoPermissions: Story = {
  args: { onEdit: undefined, actions: [false, null], transitions: undefined },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Persona actions" })).not.toBeInTheDocument();
  },
};

/** A very long title wraps inside its own box; Edit and the menu stay on the title row. */
export const LongTitle: Story = {
  args: { title: "An exceptionally long record title ".repeat(8) },
  play: async ({ canvasElement }) => {
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

export const ManyBadges: Story = {
  args: {
    badges: (
      <>
        {["Project", "Active", "Review overdue", "Archived", "Retention review due"].map((b) => <Badge key={b}>{b}</Badge>)}
      </>
    ),
  },
};

export const DarkTheme: Story = { globals: { theme: "dark" } };
