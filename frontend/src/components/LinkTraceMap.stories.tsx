import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildTraceApi, LINKS_PROJECT_ID, type TraceLink, type TraceRecord } from "../testing/artefactLinksFixtures";
import { buildSupersessionApi, buildUniverseApi, FOCUS_ID, SUPERSESSION_FOCUS_ID } from "../testing/linkTraceUniverse";
import { withRouter } from "../testing/storybook-helpers";
import { LinkTraceMap } from "./LinkTraceMap";
import { wrapLabel } from "./linkTrace";

/**
 * The trace map (docs/plans/platform-enhancements-2026-10-plan.md Phase 7): a layered, read-only SVG
 * (upstream left, downstream right, related below) that scrolls and grows as records are opened.
 */
const meta: Meta<typeof LinkTraceMap> = {
  title: "Components/LinkTraceMap",
  component: LinkTraceMap,
  decorators: [withRouter("/")],
  // The trace views are part of the plan's a11y acceptance: violations fail here, not just show in the UI.
  parameters: { a11y: { test: "error" } },
  args: { projectId: LINKS_PROJECT_ID, artefactType: "requirement", artefactId: FOCUS_ID },
};
export default meta;

type Story = StoryObj<typeof LinkTraceMap>;

const left = (el: HTMLElement) => el.getBoundingClientRect().left;
const top = (el: HTMLElement) => el.getBoundingClientRect().top;

export const DrawsLayersAroundTheRecord: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const region = await canvas.findByRole("region", { name: "Map of the records linked to REQ-002 Store reports" });
    const map = within(region);
    const upstream = await map.findByRole("link", { name: /REQ-001 Keep reports/ });
    const focus = map.getByRole("link", { name: /REQ-002 Store reports/ });
    const downstream = map.getByRole("link", { name: /TST-001 Restore from backup/ });
    const related = map.getByRole("link", { name: /REQ-003 Export reports/ });
    // Direction is position: upstream left of the record, downstream right of it, related below.
    await expect(left(upstream)).toBeLessThan(left(focus));
    await expect(left(focus)).toBeLessThan(left(downstream));
    await expect(top(related)).toBeGreaterThan(top(focus));
    // Two hops are drawn from the start, in the same direction as the first.
    await expect(left(map.getByRole("link", { name: /REQ-000 Platform baseline/ }))).toBeLessThan(left(upstream));
    await expect(left(map.getByRole("link", { name: /TST-002 Restore under load/ }))).toBeGreaterThan(left(downstream));
    // The key is behind a button (a popover), so it takes no room until asked for; the hint says records open on click.
    await expect(canvas.queryByRole("list", { name: "Key" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/Click a record to open it/)).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Key" }));
    const key = within(await within(document.body).findByRole("dialog", { name: "Key" }));
    await expect(key.getByText("Arrow points downstream")).toBeInTheDocument();
    await expect(key.queryByText(/Show more/)).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Key" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog", { name: "Key" })).not.toBeInTheDocument());
    for (const lane of ["upstream", "focus", "downstream", "related"]) await expect(canvasElement.querySelector(`.link-trace__lane--${lane}`)).not.toBeNull();
    // Upstream links point downstream (their arrowhead is at the focus end); related links have none.
    await expect(canvasElement.querySelectorAll("path[marker-start], path[marker-end]").length).toBeGreaterThan(0);
    // The diagram names its text alternative.
    await expect(canvasElement.querySelector("svg desc")?.textContent).toMatch(/Tree tab/);
    await expect(map.getByRole("link", { name: /REQ-001 Keep reports/ })).toHaveAttribute("href", `/projects/${LINKS_PROJECT_ID}/requirements/req-1`);
  },
};

export const GrowsWhenARecordIsOpened: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /TST-002 Restore under load/ });
    await expect(args.api!.graph).toHaveBeenCalledWith(LINKS_PROJECT_ID, "requirement", FOCUS_ID, 2);
    // Past the two hops drawn at first: open the furthest records one at a time, without limit.
    await expect(canvas.queryByRole("link", { name: /TST-003/ })).not.toBeInTheDocument();
    // The control reads as a labelled pill, not a bare icon.
    const showMore = canvas.getByRole("button", { name: "Show more links of TST-002 Restore under load" });
    await expect(within(showMore).getByText("Show more")).toBeInTheDocument();
    await userEvent.click(showMore);
    await canvas.findByRole("link", { name: /TST-003 Restore across regions/ });
    await userEvent.click(await canvas.findByRole("button", { name: "Show more links of TST-003 Restore across regions" }));
    await canvas.findByRole("link", { name: /TST-004 Restore after failover/ });
    await expect(args.api!.graph).toHaveBeenLastCalledWith(LINKS_PROJECT_ID, "requirement", "test-3", 1);
    // An opened record has nothing left to open.
    await expect(canvas.queryByRole("button", { name: "Show more links of TST-002 Restore under load" })).not.toBeInTheDocument();
  },
};

export const SaysWhenAnOpenedRecordHasNothingFurther: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // REQ-000 sits two hops upstream and has no links of its own; its control goes once it has been read.
    await userEvent.click(await canvas.findByRole("button", { name: "Show more links of REQ-000 Platform baseline" }));
    await waitFor(() => expect(canvas.getAllByText("Nothing further from REQ-000 Platform baseline in this direction.").length).toBeGreaterThan(0));
    await expect(canvas.queryByRole("button", { name: "Show more links of REQ-000 Platform baseline" })).not.toBeInTheDocument();
    // The record itself says so, not only a note off to the side.
    await expect(canvas.getByText("No more links")).toBeInTheDocument();
  },
};

/** An API whose records past the first reads wait until `release` is called. */
function slowUniverse() {
  const api = buildUniverseApi();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const graph = api.graph;
  return {
    release: () => release(),
    api: { ...api, graph: fn(async (...args: Parameters<typeof graph>) => (args[3] === 1 ? gate.then(() => graph(...args)) : graph(...args))) },
  };
}

let releaseSlow: () => void = () => {};

/** Builds its own gated API per mount, so replaying the story starts from a pending read again. */
function SlowMap(props: React.ComponentProps<typeof LinkTraceMap>) {
  const [slow] = useState(slowUniverse);
  useEffect(() => {
    releaseSlow = slow.release;
  }, [slow]);
  return <LinkTraceMap {...props} api={slow.api} />;
}

export const ShowsAPendingStateWhileARecordIsRead: Story = {
  render: (args) => <SlowMap {...args} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const showMore = await canvas.findByRole("button", { name: "Show more links of TST-002 Restore under load" });
    await userEvent.click(showMore);
    await expect(showMore).toHaveAttribute("aria-disabled", "true");
    await expect(within(showMore).getByText("Loading…")).toBeInTheDocument();
    releaseSlow();
    await canvas.findByRole("link", { name: /TST-003 Restore across regions/ });
    await expect(canvas.queryByRole("button", { name: "Show more links of TST-002 Restore under load" })).not.toBeInTheDocument();
  },
};

export const HighlightsTheEdgesOfTheRecordUnderThePointer: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: /REQ-001 Keep reports/ });
    await expect(canvasElement.querySelector(".link-trace__edge-group--active")).toBeNull();
    await userEvent.hover(link);
    // Keep reports has two edges: one to the focus record and one to REQ-000.
    await waitFor(() => expect(canvasElement.querySelectorAll(".link-trace__edge-group--active")).toHaveLength(2));
    await userEvent.unhover(link);
    await waitFor(() => expect(canvasElement.querySelector(".link-trace__edge-group--active")).toBeNull());
  },
};

export const ShowsALoadingState: Story = {
  args: { api: { ...buildUniverseApi(), graph: () => new Promise(() => {}) } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("status")).toHaveTextContent("Loading…");
  },
};

export const KeepsADirectionAndSkipsLinksThatWouldDoubleBack: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The decision is downstream; the pain point it addresses is upstream of the decision, so it is not drawn.
    await canvas.findByRole("link", { name: /DEC-001 Use Postgres/ });
    await expect(canvas.queryByRole("link", { name: /Reports arrive late/ })).not.toBeInTheDocument();
  },
};

const MANY: TraceRecord[] = [
  { id: FOCUS_ID, label: "REQ-002 Store reports" },
  ...Array.from({ length: 70 }, (_, i) => ({ id: `rel-${i}`, label: `REL-${String(i).padStart(3, "0")} Related record` })),
];
const MANY_LINKS: TraceLink[] = MANY.slice(1).map((r) => ({
  source: FOCUS_ID, target: r.id, forward: "Related to", reverse: "Related to", flow: "none" as const,
}));

export const CapsAVeryLargeGraph: Story = {
  args: { api: buildTraceApi(MANY, MANY_LINKS) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/Showing 60 of 71 records/)).toBeInTheDocument();
    await expect(canvas.getAllByRole("link")).toHaveLength(60);
  },
};

export const ExplainsWhenMostLinksHaveNoDirection: Story = {
  args: { api: buildTraceApi(MANY.slice(0, 3), MANY_LINKS.slice(0, 2)) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Most of these links have no direction/)).toBeInTheDocument();
  },
};

export const OnlyTheRecordItself: Story = {
  args: { api: buildTraceApi(MANY.slice(0, 1), []) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("link", { name: /REQ-002 Store reports/ })).toBeInTheDocument();
    await expect(within(canvasElement).getByText(/no links to draw yet/)).toBeInTheDocument();
  },
};

export const WrapsLongLabelsAndMarksArchivedAndOtherProjectRecords: Story = {
  args: {
    api: buildTraceApi(
      [
        { id: FOCUS_ID, label: "REQ-002 Store reports" },
        { id: "long", label: "REQ-010 A very long requirement name that cannot possibly fit on two short lines of a map node", isArchived: true },
        { id: "far", label: "REQ-011 In the parent", projectId: "project-parent", projectName: "Programme" },
      ],
      [
        { source: FOCUS_ID, target: "long", forward: "Depends on", reverse: "Is a dependency of", flow: "forward_is_upstream" },
        { source: FOCUS_ID, target: "far", forward: "Depends on", reverse: "Is a dependency of", flow: "forward_is_upstream" },
      ],
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The node's accessible name keeps the whole label even though the drawing cuts it.
    await expect(await canvas.findByRole("link", { name: /A very long requirement name that cannot possibly fit/ })).toBeInTheDocument();
    await expect(wrapLabel("REQ-010 A very long requirement name that cannot possibly fit on two short lines")).toHaveLength(2);
    await expect(canvas.getByRole("link", { name: /Programme/ })).toHaveAttribute("href", "/projects/project-parent/requirements/far");
    await expect(canvasElement.querySelector(".link-trace__node--archived")).not.toBeNull();
    await expect(canvasElement.querySelector(".link-trace__node--elsewhere")).not.toBeNull();
  },
};

export const ReportsAMapThatCannotBeRead: Story = {
  args: {
    api: {
      ...buildUniverseApi(),
      graph: async () => {
        throw new Error("boom");
      },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Could not load links.")).toBeInTheDocument();
  },
};

export const HidingInactiveRecordsJoinsTheirLinksToTheRecordInFront: Story = {
  args: { api: buildSupersessionApi(), artefactId: SUPERSESSION_FOCUS_ID, artefactType: "decision", hideInactive: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /AV-PERF-001 Acquire GPS lock/ });
    await expect(canvas.getByRole("link", { name: /Reports arrive late/ })).toBeInTheDocument();
    // DEC-001 sat between them and the record, and DEC-000 beyond it was read on the way: both are skipped, REQ-000 is reached.
    await waitFor(() => expect(canvas.getByRole("link", { name: /REQ-000 Platform baseline/ })).toBeInTheDocument());
    await expect(canvas.queryByRole("link", { name: /DEC-001/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /DEC-000/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /REQ-900/ })).not.toBeInTheDocument();
    // They join the record directly, in the same lane, with dashed edges.
    await expect(left(canvas.getByRole("link", { name: /AV-PERF-001/ }))).toBeLessThan(left(canvas.getByRole("link", { name: /DEC-002/ })));
    await expect(canvasElement.querySelectorAll(".link-trace__edge--joined").length).toBe(3);
  },
};

export const ShowsInactiveRecordsByDefault: Story = {
  args: { api: buildSupersessionApi(), artefactId: SUPERSESSION_FOCUS_ID, artefactType: "decision" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: /DEC-001/ })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /REQ-900/ })).toBeInTheDocument();
    await expect(canvasElement.querySelectorAll(".link-trace__edge--joined").length).toBe(0);
  },
};

export const RelatedRecordsOpenOneHopAtATime: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Upstream and downstream start two hops deep; related records can be numerous, so they start one hop deep.
    await canvas.findByRole("link", { name: /TST-002 Restore under load/ });
    await expect(canvas.getByRole("link", { name: /REQ-003 Export reports/ })).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /REQ-004 Email reports/ })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show more links of REQ-003 Export reports" }));
    await expect(await canvas.findByRole("link", { name: /REQ-004 Email reports/ })).toBeInTheDocument();
    // It had links to show, so it is not reported as exhausted.
    await expect(canvas.queryByText("No more links")).not.toBeInTheDocument();
  },
};
