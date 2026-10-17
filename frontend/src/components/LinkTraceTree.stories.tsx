import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildTraceApi, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { buildSupersessionApi, buildUniverseApi, FOCUS_ID, SUPERSESSION_FOCUS_ID } from "../testing/linkTraceUniverse";
import { withRouter } from "../testing/storybook-helpers";
import { LinkTraceTree } from "./LinkTraceTree";

/**
 * The trace tree: a record's links as
 * Upstream / Downstream / Related, each branch opened on demand without a depth limit.
 */
const meta: Meta<typeof LinkTraceTree> = {
  title: "Components/LinkTraceTree",
  component: LinkTraceTree,
  decorators: [withRouter("/")],
  // The trace views are part of the a11y acceptance: violations fail here, not just show in the UI.
  parameters: { a11y: { test: "error" } },
  args: { projectId: LINKS_PROJECT_ID, artefactType: "requirement", artefactId: FOCUS_ID },
};
export default meta;

type Story = StoryObj<typeof LinkTraceTree>;

export const GroupsLinksByDirection: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const upstream = await canvas.findByRole("region", { name: /Upstream/ });
    await expect(within(upstream).getByRole("link", { name: "REQ-001 Keep reports" })).toBeInTheDocument();
    await expect(within(upstream).getByText("Depends on")).toBeInTheDocument();
    const downstream = canvas.getByRole("region", { name: /Downstream/ });
    await expect(within(downstream).getByRole("link", { name: "DEC-001 Use Postgres" })).toBeInTheDocument();
    await expect(within(downstream).getByRole("link", { name: "TST-001 Restore from backup" })).toBeInTheDocument();
    const related = canvas.getByRole("region", { name: /Related/ });
    await expect(within(related).getByRole("link", { name: "REQ-003 Export reports" })).toBeInTheDocument();
    // Label-mapped status, never the raw value.
    await expect(within(downstream).getByText("Draft")).toBeInTheDocument();
  },
};

export const EmptyGroupsSayNone: Story = {
  args: {
    api: buildTraceApi(
      [{ id: FOCUS_ID, label: "REQ-002 Store reports" }, { id: "req-1", label: "REQ-001 Keep reports" }],
      [{ source: FOCUS_ID, target: "req-1", forward: "Depends on", reverse: "Is a dependency of", flow: "forward_is_upstream" }],
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const downstream = await canvas.findByRole("region", { name: /Downstream/ });
    await expect(within(downstream).getByText("None")).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: /Related/ })).getByText("None")).toBeInTheDocument();
  },
};

export const OpensBranchesAsDeepAsTheUserLikes: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    // Four levels down the verification chain: each open is one lazy read, none is prefetched.
    const names = ["TST-001 Restore from backup", "TST-002 Restore under load", "TST-003 Restore across regions"];
    await canvas.findByRole("link", { name: names[0] });
    await expect(args.api!.graph).toHaveBeenCalledTimes(1);
    for (const name of names) {
      await userEvent.click(await canvas.findByRole("button", { name: `Show what is linked beyond ${name}` }));
    }
    await expect(await canvas.findByRole("link", { name: "TST-004 Restore after failover" })).toBeInTheDocument();
    await expect(args.api!.graph).toHaveBeenCalledTimes(4);
    // Closing a branch hides it without another read.
    await userEvent.click(canvas.getByRole("button", { name: `Hide what is linked beyond ${names[0]}` }));
    await expect(canvas.queryByRole("link", { name: "TST-002 Restore under load" })).not.toBeInTheDocument();
  },
};

export const KeepsItsDirectionOfTravel: Story = {
  args: { api: buildUniverseApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The decision is downstream of the requirement; the pain point it addresses is upstream of the
    // decision, so a downstream branch must not follow it.
    await userEvent.click(await canvas.findByRole("button", { name: "Show what is linked beyond DEC-001 Use Postgres" }));
    await expect(await canvas.findByText("Nothing further in this direction.")).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Reports arrive late" })).not.toBeInTheDocument();
  },
};

export const EndsACycleInsteadOfRepeatingARecord: Story = {
  args: {
    api: buildTraceApi(
      [{ id: FOCUS_ID, label: "A" }, { id: "b", label: "B" }, { id: "c", label: "C" }],
      [
        { source: FOCUS_ID, target: "b", forward: "Related to", reverse: "Related to", flow: "none" },
        { source: "b", target: "c", forward: "Related to", reverse: "Related to", flow: "none" },
        { source: "c", target: FOCUS_ID, forward: "Related to", reverse: "Related to", flow: "none" },
      ],
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Show what is linked beyond B" }));
    // B's other neighbour is C; A (the record on the path) is not offered again beneath it.
    await waitFor(() => expect(canvas.getAllByRole("link", { name: "C" })).toHaveLength(2));
    await expect(canvas.queryByRole("link", { name: "A" })).not.toBeInTheDocument();
  },
};

export const ExplainsWhenMostLinksHaveNoDirection: Story = {
  args: {
    api: buildTraceApi(
      [{ id: FOCUS_ID, label: "A" }, { id: "b", label: "B" }, { id: "c", label: "C" }],
      [
        { source: FOCUS_ID, target: "b", forward: "Related to", reverse: "Related to", flow: "none" },
        { source: FOCUS_ID, target: "c", forward: "Related to", reverse: "Related to", flow: "none" },
      ],
    ),
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Most of these links have no direction/)).toBeInTheDocument();
  },
};

export const ReportsABranchThatCannotBeRead: Story = {
  args: {
    api: (() => {
      const api = buildUniverseApi();
      const read = api.graph;
      let calls = 0;
      api.graph = async (...args: Parameters<typeof read>) => {
        calls += 1;
        if (calls > 1) throw new Error("boom");
        return read(...args);
      };
      return api;
    })(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Show what is linked beyond TST-001 Restore from backup" }));
    await expect(await canvas.findByText("Could not load this branch.")).toBeInTheDocument();
  },
};

export const ShowsInactiveRecordsUntilTheyAreHidden: Story = {
  args: { api: buildSupersessionApi(), artefactId: SUPERSESSION_FOCUS_ID, artefactType: "decision" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const upstream = await canvas.findByRole("region", { name: /Upstream/ });
    await expect(within(upstream).getByRole("link", { name: "DEC-001 Single controller with hot-swap" })).toBeInTheDocument();
    await expect(within(upstream).queryByRole("link", { name: "AV-PERF-001 Acquire GPS lock" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "REQ-900 Withdrawn idea" })).toBeInTheDocument();
  },
};

export const HidingInactiveRecordsJoinsWhatTheyLinkToTheRecordInFront: Story = {
  args: { api: buildSupersessionApi(), artefactId: SUPERSESSION_FOCUS_ID, artefactType: "decision", hideInactive: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const upstream = await canvas.findByRole("region", { name: /Upstream/ });
    // DEC-001 is skipped, so its own sources sit directly under the record, marked with where they came through.
    await waitFor(() => expect(within(upstream).getByRole("link", { name: "AV-PERF-001 Acquire GPS lock" })).toBeInTheDocument());
    await expect(within(upstream).getByRole("link", { name: "Reports arrive late" })).toBeInTheDocument();
    await expect(within(upstream).queryByRole("link", { name: /DEC-001/ })).not.toBeInTheDocument();
    await expect(within(upstream).getAllByText("via DEC-001 Single controller with hot-swap").length).toBe(2);
    // A chain of skipped records is followed to the end, naming each.
    await expect(within(upstream).getByRole("link", { name: "REQ-000 Platform baseline" })).toBeInTheDocument();
    await expect(within(upstream).getByText("via DEC-001 Single controller with hot-swap, DEC-000 Single controller")).toBeInTheDocument();
    // An archived record is hidden too, and the record being traced never is.
    await expect(canvas.queryByRole("link", { name: "REQ-900 Withdrawn idea" })).not.toBeInTheDocument();
  },
};

export const NeverHidesTheRecordBeingTraced: Story = {
  args: { api: buildSupersessionApi(), artefactId: "dec-1", artefactType: "decision", hideInactive: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // DEC-001 is superseded itself, but is the subject: its sources show, and its superseder (downstream) is live.
    await expect(await canvas.findByRole("link", { name: "AV-PERF-001 Acquire GPS lock" })).toBeInTheDocument();
    await expect(within(canvas.getByRole("region", { name: /Downstream/ })).getByRole("link", { name: /DEC-002/ })).toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: /DEC-000/ })).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "REQ-000 Platform baseline" })).toBeInTheDocument();
  },
};
