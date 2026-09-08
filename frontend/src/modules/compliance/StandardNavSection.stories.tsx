import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { withRouter } from "../../testing/storybook-helpers";
import { StandardNavSection } from "./StandardNavSection";

/**
 * The "Standard" left-nav section (docs/compliance-module-plan.md Phase 18)
 * — Overview/Details, Versions, History — registered via `module.ts`'s
 * `standaloneWorkspaces`, rendered by `Layout.tsx` as a sibling structural
 * pattern to its own "Project" section, never imported by `Layout.tsx`
 * directly.
 */
const meta: Meta<typeof StandardNavSection> = {
  title: "Modules/Compliance/StandardNavSection",
  component: StandardNavSection,
  args: { entityId: "std-1", railCollapsed: false },
  decorators: [withRouter("/standards/std-1")],
};
export default meta;

type Story = StoryObj<typeof StandardNavSection>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Standard")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/standards/std-1");
    await expect(canvas.getByRole("link", { name: "Versions" })).toHaveAttribute("href", "/standards/std-1/versions");
    await expect(canvas.getByRole("link", { name: "History" })).toHaveAttribute("href", "/standards/std-1/history");
  },
};

export const Collapsed: Story = {
  args: { railCollapsed: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Collapsed rows keep their accessible name but hide the visible text
    // label (`.nav-label`, hidden via CSS in icon-only mode) — same
    // convention every other `NavRailLink` follows.
    await expect(canvas.getByRole("link", { name: "Overview" })).toBeInTheDocument();
  },
};
