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
    subtitle: "Analyst",
    version: 3,
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

/** The version is a labelled, muted item on the badge line, never a line of its own. */
export const VersionAfterTheBadges: Story = {
  play: async ({ canvasElement }) => {
    const version = within(canvasElement).getByText("Version 3");
    await expect(version).toHaveAttribute("title", "Version 3 of this record");
    await expect(version.parentElement).toContainElement(within(canvasElement).getByText("Active"));
  },
};

/** A version with no badges still sits on its own badge line; a record with no version shows none. */
export const VersionOnly: Story = {
  args: { badges: undefined, subtitle: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Version 3")).toBeInTheDocument();
  },
};

export const NoVersionNoSubtitle: Story = {
  args: { version: undefined, subtitle: undefined, badges: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText(/Version/)).not.toBeInTheDocument();
  },
};

/** A long title keeps the version on the badge line under it. */
export const LongTitleWithVersion: Story = {
  args: { title: "A very long persona name that would otherwise push everything around when it wraps across several lines" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Version 3")).toBeInTheDocument();
  },
};

/** A record the organisation owns is qualified with the organisation's code. */
export const CodeOwnedByTheOrganisation: Story = {
  args: { codeOwner: "ACME" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("ACME-PER-001")).toBeInTheDocument();
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
