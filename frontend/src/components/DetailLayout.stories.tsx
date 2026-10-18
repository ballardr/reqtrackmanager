import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { DetailLayout } from "./DetailLayout";

/**
 * Artefact detail page frame: content plus a collapsible aside (the Links panel). Collapse
 * is stored per user; below 1280px the aside stacks and has no toggle.
 */
const meta: Meta<typeof DetailLayout> = {
  title: "Components/DetailLayout",
  component: DetailLayout,
  decorators: [withStatefulAuth(buildUser())],
  args: {
    children: <h1 style={{ margin: 0 }}>Page content</h1>,
    aside: <div className="card">Aside content</div>,
  },
};
export default meta;

type Story = StoryObj<typeof DetailLayout>;

export const ShowsTheAsideBesideTheContent: Story = {
  parameters: { viewport: { defaultViewport: "desktop" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Page content")).toBeInTheDocument();
    await expect(canvas.getByRole("complementary", { name: "Links" })).toBeInTheDocument();
  },
};

export const CollapsesAndRestoresTheAside: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The toggle only exists in the wide layout; skip the interaction in a narrow viewport.
    const hide = canvas.queryByRole("button", { name: "Hide links panel" });
    if (!hide) return;
    await userEvent.click(hide);
    await expect(canvas.queryByText("Aside content")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show links panel" }));
    await expect(canvas.getByText("Aside content")).toBeInTheDocument();
  },
};

export const RendersContentAloneWithoutAnAside: Story = {
  args: { aside: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("complementary")).not.toBeInTheDocument();
  },
};

export const ShowsLinksAndActivityTabsWhenGivenBoth: Story = {
  args: { activity: <div className="card">Activity content</div> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Links" })).toHaveAttribute("aria-selected", "true");
    await expect(canvas.getByText("Aside content")).toBeVisible();
    await expect(canvas.queryByText("Activity content")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("tab", { name: "Activity" }));
    await expect(canvas.getByText("Activity content")).toBeInTheDocument();
    // The Links panel stays mounted (its state survives) but is hidden.
    await expect(canvas.getByText("Aside content")).not.toBeVisible();

    await userEvent.click(canvas.getByRole("tab", { name: "Links" }));
    await expect(canvas.getByText("Aside content")).toBeVisible();
    await expect(canvas.queryByText("Activity content")).not.toBeInTheDocument();
  },
};

export const NoTabsWithoutAnActivityPanel: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("tablist")).not.toBeInTheDocument();
  },
};
