import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, waitFor, within } from "storybook/test";

import { withRouter, withToast } from "../../testing/storybook-helpers";
import { HeldNeedsPanel } from "./HeldNeedsPanel";
import type { HeldNeed } from "./types";

const NEEDS: HeldNeed[] = [
  { link_id: "l1", id: "need-1", name: "Diagnose faults quickly", status: "active" },
  { link_id: "l2", id: "need-2", name: "Audit without a meeting", status: "draft" },
];

const meta: Meta<typeof HeldNeedsPanel> = {
  title: "Modules/Stakeholders/HeldNeedsPanel",
  component: HeldNeedsPanel,
  decorators: [withRouter("/", "/"), withToast()],
  args: { projectId: "project-1", load: fn(async () => NEEDS) },
};
export default meta;

type Story = StoryObj<typeof HeldNeedsPanel>;

export const ListsNeedsWithLabelledStatusAndLinksToThem: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Diagnose faults quickly (Active)" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Diagnose faults quickly (Active)" })).toHaveAttribute(
      "href", "/projects/project-1/modules/stakeholders/needs/need-1",
    );
    await expect(canvas.getByRole("link", { name: "Audit without a meeting (Draft)" })).toBeInTheDocument();
    // Read-only: links are owned from the Need's side.
    await expect(canvas.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { load: fn(async () => []) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Stakeholder Needs recorded for this yet.")).toBeInTheDocument());
  },
};

/** The org-level detail route has no project, so no needs apply. */
export const RendersNothingWithoutAProject: Story = {
  args: { projectId: undefined },
  play: async ({ canvasElement, args }) => {
    await expect(within(canvasElement).queryByText("Needs")).not.toBeInTheDocument();
    await expect(args.load).not.toHaveBeenCalled();
  },
};

export const HidesItselfWhenTheListCannotLoad: Story = {
  args: { load: fn(async () => { throw new Error("404"); }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.load).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Needs")).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ListsNeedsWithLabelledStatusAndLinksToThem, globals: { theme: "dark" } };
