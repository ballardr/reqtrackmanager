import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { buildGraph, buildLinksApi, LINKS_ARTEFACT_ID, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ArtefactLinksPanel } from "./ArtefactLinksPanel";
import { DetailLayout } from "./DetailLayout";

/**
 * Artefact detail page frame: content plus a collapsible aside (the Links panel). Collapse
 * is stored per user; below 1280px the aside stacks and has no toggle.
 */
const meta: Meta<typeof DetailLayout> = {
  title: "Components/DetailLayout",
  component: DetailLayout,
  decorators: [withStatefulAuth(buildUser()), withToast(), withRouter("/")],
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

const linksPanel = (
  <ArtefactLinksPanel
    projectId={LINKS_PROJECT_ID} artefactType="requirement" artefactId={LINKS_ARTEFACT_ID}
    api={buildLinksApi({ graph: async () => buildGraph([]) })}
  />
);

/** The aside is one card: the tab strip is its title, and the Links panel inside draws no card or heading of its own. */
export const OneCardWithTheTabStripAsItsTitle: Story = {
  args: { aside: linksPanel, activity: <p>Activity content</p> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const aside = canvas.getByRole("complementary", { name: "Links" });
    await expect(await within(aside).findByRole("button", { name: "Add link" })).toBeInTheDocument();
    // "Links" is the tab, once; the panel adds no heading of its own.
    await expect(within(aside).getAllByText("Links", { selector: "button, h2, h3" })).toHaveLength(1);
    await expect(within(aside).queryByRole("heading", { name: "Links" })).not.toBeInTheDocument();
    // One card holds the tab strip and the panel.
    const cards = aside.querySelectorAll(".card");
    await expect(cards).toHaveLength(1);
    await expect(cards[0]).toContainElement(within(aside).getByRole("tablist"));
  },
};

/** With no activity there is no tab strip, so the aside's single heading says "Links" once. */
export const SingleHeadingWithoutActivity: Story = {
  args: { aside: linksPanel },
  play: async ({ canvasElement }) => {
    const aside = within(canvasElement).getByRole("complementary", { name: "Links" });
    await expect(await within(aside).findByRole("button", { name: "Add link" })).toBeInTheDocument();
    await expect(within(aside).getAllByRole("heading", { name: "Links" })).toHaveLength(1);
    await expect(aside.querySelectorAll(".card")).toHaveLength(1);
  },
};

/** Collapsed to its toggle, the aside draws no card. */
export const CollapsedAsideHasNoCard: Story = {
  args: { aside: linksPanel },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const hide = canvas.queryByRole("button", { name: "Hide links panel" });
    if (!hide) return; // narrow viewport: the aside cannot collapse
    await userEvent.click(hide);
    await expect(canvasElement.querySelector(".detail-layout__aside .card")).toBeNull();
  },
};
