import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { GRAPH_DROP_MIME, GraphCanvas, type GraphCanvasEdge, type GraphCanvasNode, type GraphCanvasProps, type GraphCanvasSelection } from "./GraphCanvas";

const SYMBOL =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3" fill="#3b5bdb"/></svg>';

const NODES: GraphCanvasNode[] = [
  { id: "sensor", label: "Sensor", x: 0, y: 0, accent: "#0f766e" },
  { id: "gateway", label: "Gateway", x: 280, y: 0, symbolSvg: SYMBOL },
  { id: "cloud", label: "Cloud service", x: 560, y: 0, accent: "#7c3aed" },
  { id: "hidden", label: "Restricted element", x: 280, y: 140, dashed: true },
];

const EDGES: GraphCanvasEdge[] = [
  { id: "e1", source: "sensor", target: "gateway", label: "SPI" },
  { id: "e2", source: "gateway", target: "cloud", label: "MQTT", direction: "both" },
  { id: "e3", source: "sensor", target: "cloud", label: "Bridged", dashed: true, color: "#b7791f" },
];

/** Hosts the canvas with real state, as a consumer would, and prints what was selected and moved. */
function Host(props: Partial<GraphCanvasProps>) {
  const [nodes, setNodes] = useState(NODES);
  const [selection, setSelection] = useState<GraphCanvasSelection | null>(null);
  return (
    <div className="stack">
      <GraphCanvas
        nodes={nodes}
        edges={EDGES}
        ariaLabel="Telemetry system"
        selected={selection}
        onSelect={setSelection}
        onNodesMove={(moves) =>
          setNodes((current) => current.map((n) => ({ ...n, ...moves.find((m) => m.id === n.id) })))
        }
        {...props}
      />
      <span data-testid="selection">{selection ? `${selection.kind}:${selection.id}` : "none"}</span>
    </div>
  );
}

/**
 * The shared node-and-connection canvas: React Flow loaded on first use behind plain props, with a list view as the
 * text alternative and the fallback when the canvas cannot load.
 */
const meta: Meta<typeof GraphCanvas> = {
  title: "Components/GraphCanvas",
  component: GraphCanvas,
  parameters: { layout: "padded" },
  // The drawing is a lazily loaded chunk; fetching it before the story runs keeps a cold first load from racing the
  // interaction test's wait for the first node.
  loaders: [async () => { await import("./GraphCanvasView"); return {}; }],
};
export default meta;

type Story = StoryObj<typeof GraphCanvas>;

/** Nodes, typed lines and a bridged (dashed) line; the node and the connection are named for a screen reader. */
export const Default: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect(await canvas.findByLabelText("Sensor, node")).toBeInTheDocument();
    expect(await canvas.findByLabelText("Bridged, connection from Sensor to Cloud service")).toBeInTheDocument();
    expect(canvas.getByRole("group", { name: "Telemetry system" })).toBeInTheDocument();
  },
};

/** Tab reaches a node, Enter selects it, and the consumer hears about it. */
export const KeyboardSelect: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Gateway, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("node:gateway"));
  },
};

/** An arrow key moves the selected node and reports the new position once. */
export const KeyboardMove: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("node:sensor"));
    const before = node.closest(".react-flow__node")?.getAttribute("style") ?? "";
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    await waitFor(() => expect(node.closest(".react-flow__node")?.getAttribute("style") ?? "").not.toBe(before));
  },
};

/** Moves are reported to the consumer when a drag or key move ends. */
export const ReportsMoves: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Cloud service, node");
    node.focus();
    await userEvent.keyboard("{Enter}{ArrowDown}");
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalled());
    const first = (args.onNodesMove as ReturnType<typeof fn>).mock.calls[0]?.[0] as { id: string }[];
    expect(first[0]?.id).toBe("cloud");
  },
};

/** Dragging a node with the pointer reports the final position once, when the drag ends. */
export const PointerDrag: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Cloud service, node");
    const box = node.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: node, coords: { clientX: x, clientY: y } },
      { target: node, coords: { clientX: x + 20, clientY: y + 30 } },
      { target: node, coords: { clientX: x + 40, clientY: y + 60 } },
      { keys: "[/MouseLeft]", target: node, coords: { clientX: x + 40, clientY: y + 60 } },
    ]);
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalled());
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { id: string; y: number }[][][];
    const last = calls[calls.length - 1]?.[0]?.[0];
    expect(last?.id).toBe("cloud");
    expect(last?.y).toBeGreaterThan(0);
  },
};

/** Read-only: nodes stay put and no connection handles are offered, but selection still works. */
export const ReadOnly: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host readOnly onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}{ArrowRight}");
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("node:sensor"));
    expect(args.onNodesMove).not.toHaveBeenCalled();
  },
};

/** A supplied SVG drawing is shown on the node as an image (a sanitised data URI), alongside the text label. */
export const WithSymbol: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (await canvas.findByLabelText("Gateway, node")).closest(".react-flow__node") as HTMLElement;
    const image = node.querySelector("img.graph-node-symbol");
    expect(image).not.toBeNull();
    expect(image?.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(within(node).getByText("Gateway")).toBeInTheDocument();
  },
};

const HOSTILE: GraphCanvasNode[] = [
  {
    id: "x",
    label: '<img src=x onerror="window.__graphXss=1"> <b>bold</b>',
    x: 0,
    y: 0,
    symbolSvg:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="window.__graphXss=1"><script>window.__graphXss=1</script><rect width="10" height="10"/></svg>',
  },
];

/** Hostile labels stay text and hostile symbol markup loses its script; nothing executes. */
export const HostileContent: Story = {
  render: () => <GraphCanvas nodes={HOSTILE} edges={[]} ariaLabel="Hostile" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect(await canvas.findByText('<img src=x onerror="window.__graphXss=1"> <b>bold</b>')).toBeInTheDocument();
    const image = canvasElement.querySelector("img.graph-node-symbol");
    const src = decodeURIComponent(image?.getAttribute("src") ?? "");
    expect(src).not.toMatch(/<script|onload/i);
    expect((window as unknown as { __graphXss?: number }).__graphXss).toBeUndefined();
    expect(canvasElement.querySelectorAll(".graph-node-label b")).toHaveLength(0);
  },
};

const BODY_TEXT = "Buffers readings from the field sensors.\nForwards them to the cloud every hour.\nRetries for a day when offline.";

const BODY_NODES: GraphCanvasNode[] = [
  { id: "tall", label: "Gateway", caption: "ELM-001 · Service", body: BODY_TEXT, x: 0, y: 0, width: 200, height: 160 },
  { id: "short", label: "Cloud", body: BODY_TEXT, x: 300, y: 0, width: 160, height: 40 },
  { id: "plain", label: "Sensor", x: 560, y: 0 },
  { id: "hostile", label: "Board", body: '<img src=x onerror="window.__graphXss=1"><b>bold</b>', x: 0, y: 220, width: 200, height: 120 },
];

/** Body text sits under the caption, keeps its line breaks, is clipped with an ellipsis to the lines the box has room for
 * (none in a box that is too short), and is text only. */
export const BodyText: Story = {
  render: () => <GraphCanvas nodes={BODY_NODES} edges={[]} ariaLabel="Notes" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tall = await canvas.findByLabelText("Gateway, node");
    await waitFor(() => expect(tall.querySelector(".graph-node-body > span")).not.toBeNull());
    const shown = tall.querySelector(".graph-node-body > span") as HTMLElement;
    expect(shown.textContent).toBe(BODY_TEXT);
    expect(shown.style.getPropertyValue("-webkit-line-clamp") || shown.style.webkitLineClamp).not.toBe("");
    const short = await canvas.findByLabelText("Cloud, node");
    expect(short.querySelector(".graph-node-body > span")).toBeNull();
    const plain = await canvas.findByLabelText("Sensor, node");
    expect(plain.querySelector(".graph-node-body")).toBeNull();
    const hostile = await canvas.findByLabelText("Board, node");
    await waitFor(() => expect(hostile.querySelector(".graph-node-body > span")).not.toBeNull());
    expect(hostile.querySelectorAll("b, img.graph-node-body")).toHaveLength(0);
    expect(hostile.querySelector(".graph-node-body")?.textContent).toContain("<b>bold</b>");
    expect((window as unknown as { __graphXss?: number }).__graphXss).toBeUndefined();
  },
};

/** The list view: the same nodes and connections as two tables, for anyone who cannot use a canvas. */
export const ListView: Story = {
  render: () => <Host initialView="list" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect(canvas.getByRole("table", { name: "Connections" })).toBeInTheDocument();
    const row = canvas.getByRole("cell", { name: "Bridged" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("Sensor")).toBeInTheDocument();
    expect(within(row).getByText("Cloud service")).toBeInTheDocument();
  },
};

/** The toggle switches between the canvas and the list, in both directions. */
export const ToggleView: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Sensor, node");
    await userEvent.click(canvas.getByRole("button", { name: "Show as list" }));
    expect(canvas.getByRole("table", { name: "Nodes" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show as diagram" }));
    expect(await canvas.findByLabelText("Sensor, node")).toBeInTheDocument();
  },
};

/** Nothing to draw. */
export const Empty: Story = {
  render: () => <GraphCanvas nodes={[]} edges={[]} ariaLabel="Empty" initialView="list" />,
  play: async ({ canvasElement }) => {
    expect(within(canvasElement).getByText("Nothing to show.")).toBeInTheDocument();
  },
};

/** A palette item dropped on the canvas reaches `onDropItem` with its text and a canvas position. */
export const DropsAPaletteItem: Story = {
  args: { onDropItem: fn() },
  render: (args) => <Host onDropItem={args.onDropItem} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const group = await canvas.findByRole("group", { name: "Telemetry system" });
    await canvas.findByLabelText("Sensor, node");
    // React Flow reports its instance (needed to convert the drop point) a moment after the first render.
    await new Promise((resolve) => setTimeout(resolve, 100));
    const data = new DataTransfer();
    data.setData(GRAPH_DROP_MIME, "type:service");
    const box = group.getBoundingClientRect();
    group.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: data, clientX: box.left + 100, clientY: box.top + 100 }));
    await waitFor(() => expect(args.onDropItem).toHaveBeenCalledTimes(1));
    const [payload, at] = (args.onDropItem as ReturnType<typeof fn>).mock.calls[0] as [string, { x: number; y: number }];
    expect(payload).toBe("type:service");
    expect(Number.isFinite(at.x) && Number.isFinite(at.y)).toBe(true);
  },
};

/** Read-only ignores a drop. */
export const ReadOnlyIgnoresDrops: Story = {
  args: { onDropItem: fn() },
  render: (args) => <Host readOnly onDropItem={args.onDropItem} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const group = await canvas.findByRole("group", { name: "Telemetry system" });
    await canvas.findByLabelText("Sensor, node");
    const data = new DataTransfer();
    data.setData(GRAPH_DROP_MIME, "type:service");
    group.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: data }));
    expect(args.onDropItem).not.toHaveBeenCalled();
  },
};

/** The selected node shows resize handles when `resizable`; dragging one reports the final size once. */
export const ResizesTheSelectedNode: Story = {
  args: { onNodesResize: fn() },
  render: (args) => <Host resizable onNodesResize={args.onNodesResize} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    const handle = await waitFor(() => {
      const found = canvasElement.querySelector(".react-flow__resize-control.handle.bottom.right");
      if (!found) throw new Error("no handle");
      return found as HTMLElement;
    });
    // The view fits itself to the nodes after they are measured; drag only once the handle has stopped moving.
    let box = handle.getBoundingClientRect();
    await waitFor(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
      const next = handle.getBoundingClientRect();
      const still = next.left === box.left && next.top === box.top;
      box = next;
      if (!still) throw new Error("handle still moving");
    });
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: handle, coords: { clientX: x, clientY: y } },
      { target: handle, coords: { clientX: x + 30, clientY: y + 20 } },
      { target: handle, coords: { clientX: x + 60, clientY: y + 40 } },
      { keys: "[/MouseLeft]", target: handle, coords: { clientX: x + 60, clientY: y + 40 } },
    ]);
    await waitFor(() => expect(args.onNodesResize).toHaveBeenCalled());
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { id: string; width: number }[][][];
    expect(calls).toHaveLength(1);
    expect(calls[0][0][0].id).toBe("sensor");
    expect(calls[0][0][0].width).toBeGreaterThan(160);
  },
};

/** Alt with an arrow key resizes the selected node by one step and reports the final size once, as a pointer resize does. */
export const ResizesTheSelectedNodeFromTheKeyboard: Story = {
  args: { onNodesResize: fn() },
  render: (args) => <Host resizable onNodesResize={args.onNodesResize} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Alt>}{ArrowRight}{ArrowDown}{/Alt}");
    await waitFor(() => expect(args.onNodesResize).toHaveBeenCalledTimes(2));
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { id: string; width: number; height: number }[][][];
    expect(calls[0][0][0]).toMatchObject({ id: "sensor", width: 170, height: 64 });
    expect(calls[1][0][0]).toMatchObject({ id: "sensor", width: 170, height: 74 });
    // Alt+arrow resizes only; the node did not move.
    expect(calls[1][0][0]).toMatchObject({ x: 0, y: 0 });
  },
};

/** A node never shrinks below its minimum size from the keyboard. */
export const KeyboardResizeStopsAtTheMinimumSize: Story = {
  args: { onNodesResize: fn() },
  render: (args) => <Host resizable onNodesResize={args.onNodesResize} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    for (let i = 0; i < 12; i += 1) await userEvent.keyboard("{Alt>}{ArrowLeft}{/Alt}");
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { width: number }[][][];
    expect(calls[calls.length - 1][0][0].width).toBe(80);
  },
};

/** Delete and Backspace ask the consumer to delete the selection; the canvas deletes nothing itself. */
export const ReportsADeleteKeyOnTheSelection: Story = {
  args: { onDelete: fn() },
  render: (args) => <Host onDelete={args.onDelete} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Delete}");
    await expect(args.onDelete).not.toHaveBeenCalled(); // nothing is selected yet
    await userEvent.keyboard("{Enter}{Delete}");
    await expect(args.onDelete).toHaveBeenCalledWith({ kind: "node", id: "sensor" });
    await expect(canvas.getByLabelText("Sensor, node")).toBeInTheDocument();
  },
};

/** A double-click asks the consumer to open the node; Enter stays selection only, and the canvas opens nothing itself. */
export const OpensANodeOnDoubleClick: Story = {
  args: { onNodeOpen: fn() },
  render: (args) => <Host onNodeOpen={args.onNodeOpen} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}{Enter}");
    await expect(args.onNodeOpen).not.toHaveBeenCalled();
    await userEvent.dblClick(node);
    await expect(args.onNodeOpen).toHaveBeenCalledWith("sensor");
  },
};

/** A read-only canvas does not report a delete, and does not advertise one. */
export const ReadOnlyIgnoresTheDeleteKey: Story = {
  args: { onDelete: fn() },
  render: (args) => <Host readOnly onDelete={args.onDelete} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}{Delete}");
    await expect(args.onDelete).not.toHaveBeenCalled();
    await expect(canvasElement.querySelector("[aria-describedby]")).not.toHaveTextContent(/Delete or Backspace/);
  },
};

/** The y of the start of a drawn line's path (its source end), from the path's "M x,y". */
function lineStartY(root: HTMLElement, edgeId: string): number {
  const path = root.querySelector(`.react-flow__edge[data-id="${edgeId}"] path.react-flow__edge-path`);
  const match = /^M\s*([-\d.e]+)[ ,]\s*([-\d.e]+)/.exec(path?.getAttribute("d") ?? "");
  return match ? Number(match[2]) : Number.NaN;
}

/** Every box offers eight attach handles: the middle of each side and the four corners. */
export const DrawsEightAttachHandlesOnEachNode: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    const ids = [...node.querySelectorAll(".react-flow__handle")].map((h) => h.getAttribute("data-handleid")).sort();
    expect(ids).toEqual(["bottom", "bottom_left", "bottom_right", "left", "right", "top", "top_left", "top_right"]);
  },
};

/** A line meets the nearest points unless the consumer fixes an end; a fixed end moves where the line starts. */
export const AFixedAttachPointMovesWhereTheLineStarts: Story = {
  render: () => (
    <div className="stack">
      <div data-testid="automatic">
        <GraphCanvas
          nodes={NODES.slice(0, 2)} edges={[{ id: "e1", source: "sensor", target: "gateway" }]} ariaLabel="Automatic" showViewToggle={false}
        />
      </div>
      <div data-testid="fixed">
        <GraphCanvas
          nodes={NODES.slice(0, 2)} edges={[{ id: "e1", source: "sensor", target: "gateway", sourcePoint: "bottom" }]}
          ariaLabel="Fixed" showViewToggle={false}
        />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findAllByLabelText("Sensor, node");
    const automatic = canvas.getByTestId("automatic");
    const fixed = canvas.getByTestId("fixed");
    await waitFor(() => expect(lineStartY(automatic, "e1")).not.toBeNaN());
    await waitFor(() => expect(lineStartY(fixed, "e1")).not.toBeNaN());
    // Both boxes are 64 high at the same height, so the automatic line starts at mid-height and the fixed one at the bottom.
    expect(lineStartY(fixed, "e1")).toBeGreaterThan(lineStartY(automatic, "e1"));
  },
};

/** The numbers of a straight line's path ("M sx,sy L ex,ey"): `[sx, sy, ex, ey]`. */
function lineEnds(root: HTMLElement, edgeId: string): number[] {
  const d = root.querySelector(`.react-flow__edge[data-id="${edgeId}"] path.react-flow__edge-path`)?.getAttribute("d") ?? "";
  return (d.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g) ?? []).map(Number);
}

/** Boxes side by side are joined by a level line from side to side, and boxes stacked by a vertical line from bottom to top. */
export const TheLineJoinsTheNearestPointsOfTwoBoxes: Story = {
  render: () => (
    <div className="stack">
      <div data-testid="beside">
        <GraphCanvas
          nodes={[{ id: "a", label: "A", x: 0, y: 0 }, { id: "b", label: "B", x: 300, y: 0 }]}
          edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Beside" showViewToggle={false}
        />
      </div>
      <div data-testid="below">
        <GraphCanvas
          nodes={[{ id: "a", label: "A", x: 0, y: 0 }, { id: "b", label: "B", x: 0, y: 300 }]}
          edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Below" showViewToggle={false}
        />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => {
      expect(lineEnds(canvas.getByTestId("beside"), "e1").length).toBeGreaterThanOrEqual(4);
      expect(lineEnds(canvas.getByTestId("below"), "e1").length).toBeGreaterThanOrEqual(4);
    });
    const [sx, sy, ex, ey] = lineEnds(canvas.getByTestId("beside"), "e1");
    expect(ex).toBeGreaterThan(sx);
    expect(ey).toBeCloseTo(sy, 0);
    const [vx, vy, wx, wy] = lineEnds(canvas.getByTestId("below"), "e1");
    expect(wy).toBeGreaterThan(vy);
    expect(wx).toBeCloseTo(vx, 0);
  },
};

/** A read-only canvas offers no way to change where a line meets its box. */
export const ReadOnlyOffersNoAnchorChange: Story = {
  args: { onEdgeAnchorChange: fn() },
  render: (args) => <Host readOnly onEdgeAnchorChange={args.onEdgeAnchorChange} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Sensor, node");
    expect(canvasElement.querySelectorAll(".react-flow__edgeupdater").length).toBe(0);
    expect(args.onEdgeAnchorChange).not.toHaveBeenCalled();
  },
};

/** Dragging the end of a line to another attach point of the same box reports the new point once, naming only that end. */
export const DraggingALineEndReportsTheNewAttachPoint: Story = {
  args: { onEdgeAnchorChange: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={[{ id: "a", label: "A", x: 0, y: 0 }, { id: "b", label: "B", x: 300, y: 0 }]}
      edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Anchors" showViewToggle={false} onEdgeAnchorChange={args.onEdgeAnchorChange}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("B, node");
    const handle = node.querySelector('.react-flow__handle[data-handleid="bottom"]') as HTMLElement;
    const updater = await waitFor(() => {
      const found = canvasElement.querySelector(".react-flow__edgeupdater-target") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    const from = updater.getBoundingClientRect();
    const to = handle.getBoundingClientRect();
    const start = { clientX: from.left + from.width / 2, clientY: from.top + from.height / 2 };
    const end = { clientX: to.left + to.width / 2, clientY: to.top + to.height / 2 };
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: updater, coords: start },
      { target: handle, coords: { clientX: (start.clientX + end.clientX) / 2, clientY: (start.clientY + end.clientY) / 2 } },
      { target: handle, coords: end },
      { keys: "[/MouseLeft]", target: handle, coords: end },
    ]);
    await waitFor(() => expect(args.onEdgeAnchorChange).toHaveBeenCalledWith("e1", { targetPoint: "bottom" }));
    expect(args.onEdgeAnchorChange).toHaveBeenCalledTimes(1);
  },
};

const SMALL_NODES: GraphCanvasNode[] = [
  { id: "a", label: "Gateway", x: 0, y: 0 },
  { id: "b", label: "Orders", x: 220, y: 0 },
];

/** The scale the canvas's viewport was fitted to. */
const viewportScale = (root: HTMLElement) =>
  Number(/scale\(([\d.]+)\)/.exec((root.querySelector(".react-flow__viewport") as HTMLElement).style.transform)?.[1]);

/** A small graph is enlarged to fill the canvas unless the opening fit is capped at 100%. */
export const OpeningZoomIsCappedForASmallGraph: Story = {
  render: () => (
    <div className="stack">
      <div data-testid="capped"><GraphCanvas nodes={SMALL_NODES} edges={[]} ariaLabel="Capped" fitMaxZoom={1} showViewToggle={false} /></div>
      <div data-testid="uncapped"><GraphCanvas nodes={SMALL_NODES} edges={[]} ariaLabel="Uncapped" showViewToggle={false} /></div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const capped = within(within(canvasElement).getByTestId("capped"));
    const uncapped = within(within(canvasElement).getByTestId("uncapped"));
    await capped.findByLabelText("Gateway, node");
    await uncapped.findByLabelText("Gateway, node");
    await waitFor(() => expect(viewportScale(within(canvasElement).getByTestId("capped"))).toBe(1));
    await waitFor(() => expect(viewportScale(within(canvasElement).getByTestId("uncapped"))).toBeGreaterThan(1));
  },
};

export const ShapedNodesDrawTheirOutlineAndKeepTheirText: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Outlines" showViewToggle={false}
      nodes={[
        { id: "in", label: "Input", x: 0, y: 0, outline: "pointed-right" },
        { id: "out", label: "Output", x: 200, y: 0, outline: "pointed-left" },
        { id: "both", label: "Two-way", x: 400, y: 0, outline: "pointed-both" },
        { id: "dot", label: "Unknown", x: 600, y: 0, outline: "ellipse", dashed: true },
        { id: "plain", label: "Plain", x: 800, y: 0 },
      ]}
      edges={[]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of ["Input", "Output", "Two-way", "Unknown", "Plain"]) {
      await expect(await canvas.findByLabelText(`${name}, node`)).toHaveTextContent(name);
    }
    // Four of the five are drawn as an outline behind the text; the plain node keeps its own box.
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-node-outline")).toHaveLength(4));
    await expect(canvasElement.querySelectorAll("svg.graph-node-outline polygon")).toHaveLength(3);
    await expect(canvasElement.querySelectorAll("svg.graph-node-outline ellipse")).toHaveLength(1);
  },
};

export const ChoosingALineWhileABoxIsSelectedSelectsTheLine: Story = {
  render: () => <Host showViewToggle={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sensor = await canvas.findByLabelText("Sensor, node");
    sensor.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("node:sensor"));
    const line = await canvas.findByLabelText("SPI, connection from Sensor to Gateway");
    line.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("edge:e1"));
  },
};

const LEADER_NODES: GraphCanvasNode[] = [
  { id: "a", label: "Gateway", x: 0, y: 0 },
  { id: "b", label: "Orders", x: 300, y: 0 },
  { id: "note", label: "Check with ops", caption: "Note", x: 120, y: 160, width: 160, height: 60, dashed: true, tone: "warning" },
];

/** The leader lines drawn, by the id the consumer gave them. */
const leaderIds = (root: HTMLElement) => [...root.querySelectorAll(".react-flow__edge.graph-leader")].map((el) => el.getAttribute("data-id"));

/** A leader to a node, to the middle of a line and to a free position is drawn as its own non-selectable line. */
export const LeadersPointAtANodeALineAndAPosition: Story = {
  render: () => (
    <GraphCanvas
      nodes={LEADER_NODES} edges={[{ id: "e1", source: "a", target: "b", label: "REST" }]} ariaLabel="Leaders" showViewToggle={false}
      leaders={[
        { id: "n", from: "note", to: { kind: "node", id: "a" } },
        { id: "l", from: "note", to: { kind: "edge", id: "e1" }, arrow: false },
        { id: "p", from: "note", to: { kind: "point", x: 380, y: 200 } },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Check with ops, node");
    await waitFor(() => expect(leaderIds(canvasElement)).toEqual(["leader:n", "leader:l", "leader:p"]));
    // Only the arrowed leaders have a head, and a leader is not offered as a connection to select.
    const heads = (id: string) => canvasElement.querySelector(`[data-id="leader:${id}"] .react-flow__edge-path`)?.getAttribute("marker-end");
    expect(heads("n")).toBeTruthy();
    expect(heads("l")).toBeFalsy();
    expect(canvas.queryByLabelText(/connection from Check with ops/)).toBeNull();
    expect(canvasElement.querySelectorAll(".graph-leader-end-free").length).toBe(1);
  },
};

/** A leader whose node, target node or target line is not on the canvas (switched off or removed) is not drawn. */
export const ALeaderToSomethingNotDrawnIsLeftOut: Story = {
  render: () => (
    <GraphCanvas
      nodes={LEADER_NODES} edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Hidden leaders" showViewToggle={false}
      leaders={[
        { id: "n", from: "note", to: { kind: "node", id: "gone" } },
        { id: "l", from: "note", to: { kind: "edge", id: "missing" } },
        { id: "s", from: "absent", to: { kind: "node", id: "a" } },
        { id: "ok", from: "note", to: { kind: "node", id: "b" } },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    await waitFor(() => expect(leaderIds(canvasElement)).toEqual(["leader:ok"]));
  },
};

/** A toned node takes its tone's class; one with no tone does not. */
export const ATonedNodeIsTintedInItsTone: Story = {
  render: () => <GraphCanvas nodes={LEADER_NODES} edges={[]} ariaLabel="Tones" showViewToggle={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect((await canvas.findByLabelText("Check with ops, node")).querySelector(".graph-node-tone-warning")).not.toBeNull();
    expect((await canvas.findByLabelText("Gateway, node")).querySelector(".graph-node-tone")).toBeNull();
  },
};

/** Dragging a free leader end reports its new position once, when the drag ends. */
export const DraggingAFreeLeaderEndReportsThePosition: Story = {
  args: { onLeaderTargetChange: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={LEADER_NODES} edges={[]} ariaLabel="Free end" showViewToggle={false}
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 380, y: 200 } }]} onLeaderTargetChange={args.onLeaderTargetChange}
    />
  ),
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    const end = await waitFor(() => {
      const found = canvasElement.querySelector(".react-flow__node-leaderEnd") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    const box = end.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: end, coords: { clientX: x, clientY: y } },
      { target: end, coords: { clientX: x + 20, clientY: y + 20 } },
      { target: end, coords: { clientX: x + 60, clientY: y + 40 } },
      { keys: "[/MouseLeft]", target: end, coords: { clientX: x + 60, clientY: y + 40 } },
    ]);
    await waitFor(() => expect(args.onLeaderTargetChange).toHaveBeenCalled());
    const calls = (args.onLeaderTargetChange as ReturnType<typeof fn>).mock.calls as [string, { kind: string; x: number; y: number }][];
    const last = calls[calls.length - 1];
    expect(last[0]).toBe("p");
    expect(last[1].kind).toBe("point");
    expect(last[1].x).toBeGreaterThan(380);
    expect(last[1].y).toBeGreaterThan(200);
  },
};

/** Read-only: a free leader end cannot be dragged and nothing is reported. */
export const ReadOnlyLeaderEndsAreNotDraggable: Story = {
  args: { onLeaderTargetChange: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={LEADER_NODES} edges={[]} ariaLabel="Read-only leaders" showViewToggle={false} readOnly
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 380, y: 200 } }]} onLeaderTargetChange={args.onLeaderTargetChange}
    />
  ),
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    await waitFor(() => expect(leaderIds(canvasElement)).toEqual(["leader:p"]));
    expect(canvasElement.querySelector(".react-flow__edgeupdater")).toBeNull();
    expect(args.onLeaderTargetChange).not.toHaveBeenCalled();
  },
};

/** A click on empty canvas is reported with its position; a click on a node is not. */
export const AClickOnEmptyCanvasReportsItsPosition: Story = {
  args: { onCanvasClick: fn() },
  render: (args) => <GraphCanvas nodes={LEADER_NODES} edges={[]} ariaLabel="Click" showViewToggle={false} onCanvasClick={args.onCanvasClick} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByLabelText("Gateway, node"));
    expect(args.onCanvasClick).not.toHaveBeenCalled();
    await userEvent.click(canvasElement.querySelector(".react-flow__pane") as HTMLElement);
    await waitFor(() => expect(args.onCanvasClick).toHaveBeenCalledTimes(1));
    const [position] = (args.onCanvasClick as ReturnType<typeof fn>).mock.calls[0] as [{ x: number; y: number }];
    expect(Number.isFinite(position.x) && Number.isFinite(position.y)).toBe(true);
  },
};
