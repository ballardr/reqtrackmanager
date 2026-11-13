import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildUser, withRouter, withStatefulAuth } from "../../testing/storybook-helpers";
import { buildConnection, buildViewBoundary, buildViewEdge, buildViewNode } from "./architectureFixtures";
import { boundaryFromView, boundaryNodeId, boxFromNode } from "./diagramEditorModel";
import { DiagramOutline } from "./DiagramOutline";
import { connectionRows, outlineSize, outlineTree } from "./diagramOutlineModel";
import { exportFileName, toggleStates } from "./diagramExport";

const GATEWAY = boxFromNode(buildViewNode());
const API = boxFromNode(buildViewNode({
  element_id: "el-5", unique_code: "ELM-005", name: "Orders API", parent_id: "el-2", display_note: "Public order entry point.",
}));
const ORDERS = boxFromNode(buildViewNode({ element_id: "el-2", unique_code: "ELM-002", name: "Orders" }));
const FIREWALL = boxFromNode(buildViewNode({ element_id: "el-3", unique_code: "ELM-003", name: "Firewall" }));
const LOCKED = boxFromNode(buildViewNode({ element_id: "el-9", unique_code: "ELM-009", name: "", locked: true }));
const PARENTS = { "el-1": null, "el-2": null, "el-3": null, "el-5": "el-2", "el-9": null };

const meta: Meta<typeof DiagramOutline> = {
  title: "Modules/Architecture/DiagramOutline",
  component: DiagramOutline,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter("/")],
  args: {
    boxes: [GATEWAY, ORDERS, API, FIREWALL], notes: [], boundaries: [], covered: new Set<string>(),
    edges: [buildViewEdge({ target_element_id: "el-5" })], parents: PARENTS,
    hidden: new Set<string>(), descriptions: new Map([["el-5", "Accepts orders over REST and queues them."]]),
    selection: null, onSelect: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof DiagramOutline>;

export const ListsTheElementsAsATreeAndTheLinesAsATable: Story = {
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await expect(outline.getByText(/4 elements, 1 line\./)).toBeInTheDocument();
    // The part inside Orders is nested under it.
    const orders = outline.getByRole("button", { name: /^ELM-002 Orders/ }).closest("li")!;
    await expect(within(orders).getByRole("button", { name: /^ELM-005 Orders API/ })).toBeInTheDocument();
    const row = outline.getByRole("button", { name: "Line from ELM-001 Gateway to ELM-005 Orders API" }).closest("tr")!;
    await expect(within(row).getByText("One-way")).toBeInTheDocument();
    await expect(within(row).getByText("Direct")).toBeInTheDocument();
  },
};

export const TheElementsCanBeReadAsATableAndSelectedFromIt: Story = {
  play: async ({ canvasElement, args }) => {
    const outline = within(canvasElement);
    await userEvent.click(outline.getByRole("button", { name: "List view" }));
    const table = await outline.findByRole("table", { name: "Elements" });
    const row = within(within(table).getByRole("button", { name: /^ELM-005 Orders API/ }).closest("tr")!);
    await expect(row.getByText("ELM-002 Orders")).toBeInTheDocument(); // its parent among the placed elements
    await expect(row.getByText("Public order entry point.")).toBeInTheDocument();
    await expect(row.getByText("Accepts orders over REST and queues them.")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: /^ELM-003 Firewall/ }));
    await expect(args.onSelect).toHaveBeenCalledWith({ kind: "node", id: "el-3" });
  },
};

export const TheTreeCollapsesAndExpandsAsAWhole: Story = {
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await expect(outline.getByRole("button", { name: /^ELM-005 Orders API/ })).toBeInTheDocument();
    await userEvent.click(outline.getByRole("button", { name: "Collapse all" }));
    await expect(outline.queryByRole("button", { name: /^ELM-005 Orders API/ })).not.toBeInTheDocument();
    await userEvent.click(outline.getByRole("button", { name: "Expand all" }));
    await expect(outline.getByRole("button", { name: /^ELM-005 Orders API/ })).toBeInTheDocument();
    await userEvent.click(outline.getByRole("button", { name: "Collapse ELM-002 Orders" }));
    await expect(outline.queryByRole("button", { name: /^ELM-005 Orders API/ })).not.toBeInTheDocument();
  },
};

export const EachSectionCollapsesToItsTitle: Story = {
  args: { notes: [{ key: "n1", id: "n1", text: "Check with ops", x: 0, y: 0, width: 160, height: 60 }] },
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await userEvent.click(outline.getByRole("button", { name: "Lines section" }));
    await expect(outline.queryByRole("button", { name: /^Line from/ })).not.toBeInTheDocument();
    await userEvent.click(outline.getByRole("button", { name: "Notes section" }));
    await expect(outline.queryByRole("button", { name: "Check with ops" })).not.toBeInTheDocument();
    await expect(outline.getByRole("button", { name: /^ELM-003 Firewall/ })).toBeInTheDocument();
  },
};

export const ChoosingAnItemSelectsIt: Story = {
  play: async ({ canvasElement, args }) => {
    const outline = within(canvasElement);
    await userEvent.click(outline.getByRole("button", { name: /^ELM-003 Firewall/ }));
    await expect(args.onSelect).toHaveBeenCalledWith({ kind: "node", id: "el-3" });
    await userEvent.click(outline.getByRole("button", { name: /^Line from/ }));
    await expect(args.onSelect).toHaveBeenCalledWith({ kind: "edge", id: "edge-1" });
  },
};

export const TheSelectedItemIsMarkedCurrent: Story = {
  args: { selection: { kind: "node", id: "el-1" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: /^ELM-001 Gateway/ })).toHaveAttribute("aria-current", "true");
  },
};

export const HiddenElementsAreLeftOutAndCounted: Story = {
  args: { hidden: new Set(["el-3"]), edges: [] },
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await expect(outline.queryByRole("button", { name: /^ELM-003/ })).not.toBeInTheDocument();
    await expect(outline.getByText(/1 hidden by view switches\./)).toBeInTheDocument();
    await expect(outline.getByText("No lines are shown on this diagram.")).toBeInTheDocument();
  },
};

export const ABridgedLineNamesTheHiddenElementsItPassesThrough: Story = {
  args: {
    hidden: new Set(["el-3"]),
    edges: [buildViewEdge({
      bridged: true, indirect: true, count: 2, label: "×2",
      hops: [{ element_id: "el-3", unique_code: "ELM-003", name: "Firewall" }],
    })],
  },
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("button", { name: /^Line from/ }).closest("tr")!;
    await expect(within(row).getByText("Bridged")).toBeInTheDocument();
    await expect(within(row).getByText(/via ELM-003 Firewall/)).toBeInTheDocument();
    await expect(within(row).getByText("2")).toBeInTheDocument();
  },
};

export const AnUnreadableElementShowsItsCodeOnly: Story = {
  args: { boxes: [GATEWAY, LOCKED] },
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await expect(outline.getByRole("button", { name: "ELM-009" })).toBeInTheDocument();
    await expect(outline.queryByRole("button", { name: /ELM-009 / })).not.toBeInTheDocument();
  },
};

export const NotesAreListedAsPlainText: Story = {
  args: { notes: [{ key: "n1", id: "n1", text: "<b>Check with ops</b>", x: 0, y: 0, width: 160, height: 60 }] },
  play: async ({ canvasElement }) => {
    const note = within(canvasElement).getByRole("button", { name: "<b>Check with ops</b>" });
    await expect(note.querySelector("b")).toBeNull();
  },
};

export const AnEmptyDiagramSaysSo: Story = {
  args: { boxes: [], edges: [] },
  play: async ({ canvasElement }) => {
    const outline = within(canvasElement);
    await expect(outline.getByText("No elements are shown on this diagram.")).toBeInTheDocument();
    await expect(outline.getByText(/0 elements, 0 lines\./)).toBeInTheDocument();
  },
};

export const TheModelNestsUnderTheNearestPlacedAncestor: Story = {
  play: async () => {
    // Orders API's parent chain is Orders (placed): it nests there. With Orders not placed it becomes a root.
    expect(outlineTree([GATEWAY, ORDERS, API], PARENTS, new Set()).map((n) => [n.box.unique_code, n.children.length])).toEqual([
      ["ELM-001", 0], ["ELM-002", 1],
    ]);
    expect(outlineTree([GATEWAY, API], PARENTS, new Set()).map((n) => n.box.unique_code)).toEqual(["ELM-001", "ELM-005"]);
    // A hidden parent is not an anchor: its child is shown at the next visible ancestor, or as a root.
    expect(outlineTree([ORDERS, API], PARENTS, new Set(["el-2"])).map((n) => n.box.unique_code)).toEqual(["ELM-005"]);
    // Siblings are in code order, numerically within a prefix.
    const ten = boxFromNode(buildViewNode({ element_id: "el-10", unique_code: "ELM-010", name: "Ten" }));
    expect(outlineTree([ten, ORDERS], { "el-10": null, "el-2": null }, new Set()).map((n) => n.box.unique_code)).toEqual(["ELM-002", "ELM-010"]);
    // A cycle in the parents does not loop.
    expect(outlineSize(outlineTree([ORDERS, API], { "el-2": "el-5", "el-5": "el-2" }, new Set()))).toBe(2);
  },
};

export const TheRowsNameEveryRouteKind: Story = {
  play: async () => {
    const rows = connectionRows(
      [
        buildViewEdge({ id: "a" }),
        buildViewEdge({ id: "b", rolled_up: true, two_way: true, count: 3, label: "REST API ×3" }),
        buildViewEdge({ id: "c", bridged: true, hops: [{ element_id: "el-3", unique_code: "ELM-003", name: "Firewall" }] }),
        buildViewEdge({ id: "d", source_element_id: "gone", connections: [buildConnection()] }),
      ],
      [GATEWAY, ORDERS],
    );
    expect(rows.map((r) => [r.id, r.route, r.twoWay, r.detail, r.count, r.via])).toEqual([
      ["a", "direct", false, "", 1, []],
      ["b", "rolled_up", true, "REST API ×3", 3, []],
      ["c", "bridged", false, "", 1, ["ELM-003 Firewall"]],
    ]);
  },
};

export const ExportNamesAndSwitchStates: Story = {
  play: async () => {
    expect(exportFileName("DGM-001", "Platform overview", "svg")).toBe("DGM-001-platform-overview.svg");
    expect(exportFileName("DGM-002", "  Ünïcode / Crème <b>! ", "png")).toBe("DGM-002-unicode-creme-b.png");
    expect(exportFileName("DGM-003", "???", "mmd")).toBe("DGM-003.mmd");
    expect(exportFileName("DGM-004", "x".repeat(200), "svg").length).toBeLessThan(80);
    expect(toggleStates([{ id: "a", on: true }, { id: "b", on: false }])).toEqual({ on: ["a"], off: ["b"] });
  },
};

export const OuterConnectionsAreATableWithDirectionAndCoverageAndNameTheBoxOnALine: Story = {
  args: {
    boundaries: [boundaryFromView(buildViewBoundary()), boundaryFromView(buildViewBoundary({
      id: "bx-2", connection_id: "con-12", connection_code: "CON-012", shape: "input", locked: true, outside_element_code: "ELM-020",
      outside_element_name: "",
    }))],
    covered: new Set(["con-9"]),
    edges: [buildViewEdge({ source_element_id: "el-1", target_element_id: boundaryNodeId("con-9") })],
  },
  play: async ({ canvasElement, args }) => {
    const outline = within(canvasElement);
    await expect(outline.getByText(/2 outer connections/)).toBeInTheDocument();
    const table = outline.getByRole("table", { name: "Outer connections" });
    const first = within(within(table).getByRole("button", { name: "CON-009" }).closest("tr")!);
    await expect(first.getByText("ELM-008 Cloud")).toBeInTheDocument();
    await expect(first.getByText("Output")).toBeInTheDocument();
    await expect(first.getByText("Covered")).toBeInTheDocument();
    // An outside element the viewer cannot read is named by its code alone.
    const second = within(within(table).getByRole("button", { name: "CON-012" }).closest("tr")!);
    await expect(second.getByText("ELM-020")).toBeInTheDocument();
    await expect(second.getByText("Not covered")).toBeInTheDocument();
    // The line to the box names the box by its connection and the element outside.
    await expect(outline.getByRole("button", { name: "Line from ELM-001 Gateway to CON-009 (ELM-008 Cloud)" })).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "CON-009" }));
    await expect(args.onSelect).toHaveBeenCalledWith({ kind: "node", id: boundaryNodeId("con-9") });
  },
};
