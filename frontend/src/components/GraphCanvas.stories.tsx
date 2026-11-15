import type { Meta, StoryObj } from "@storybook/react-vite";
import { Profiler, useRef, useState } from "react";
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

/** A consumer that undoes a move (its props return to the earlier position) shows the box back where it was, not where it was dragged. */
export const AnUndoneMoveReturnsTheBox: Story = {
  render: () => {
    function UndoHost() {
      const [nodes, setNodes] = useState(NODES);
      const [selection, setSelection] = useState<GraphCanvasSelection | null>(null);
      return (
        <div className="stack">
          <button type="button" onClick={() => setNodes(NODES)}>Undo move</button>
          <GraphCanvas
            nodes={nodes} edges={EDGES} ariaLabel="Telemetry system" selected={selection} onSelect={setSelection}
            onNodesMove={(moves) => setNodes((current) => current.map((n) => ({ ...n, ...moves.find((m) => m.id === n.id) })))}
          />
        </div>
      );
    }
    return <UndoHost />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    const styleOf = () => /transform: [^;]*/.exec(node.closest(".react-flow__node")?.getAttribute("style") ?? "")?.[0] ?? "";
    const before = styleOf();
    const box = node.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: node, coords: { clientX: x, clientY: y } },
      { target: node, coords: { clientX: x + 20, clientY: y + 30 } },
      { target: node, coords: { clientX: x + 40, clientY: y + 60 } },
      { keys: "[/MouseLeft]", target: node, coords: { clientX: x + 40, clientY: y + 60 } },
    ]);
    await waitFor(() => expect(styleOf()).not.toBe(before));
    await userEvent.click(canvas.getByRole("button", { name: "Undo move" }));
    await waitFor(() => expect(styleOf()).toBe(before));
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

/** A double-click on a line asks the consumer to open it, the same contract as a node; a single click only selects. */
export const OpensALineOnDoubleClick: Story = {
  args: { onEdgeOpen: fn() },
  render: (args) => <Host onEdgeOpen={args.onEdgeOpen} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByLabelText("SPI, connection from Sensor to Gateway"));
    await expect(args.onEdgeOpen).not.toHaveBeenCalled();
    // Selecting redraws the line, so it is found again rather than reused.
    await userEvent.dblClick(await canvas.findByLabelText("SPI, connection from Sensor to Gateway"));
    await expect(args.onEdgeOpen).toHaveBeenCalledWith("e1");
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

/** A leader to a node, to the middle of a line and to a free position is drawn as its own line. */
export const LeadersPointAtANodeALineAndAPosition: Story = {
  render: () => (
    <GraphCanvas
      nodes={LEADER_NODES} edges={[{ id: "e1", source: "a", target: "b", label: "REST" }]} ariaLabel="Leaders" showViewToggle={false}
      leaders={[
        { id: "n", from: "note", to: { kind: "node", id: "a" } },
        { id: "l", from: "note", to: { kind: "edge", id: "e1" }, endEnd: "none" },
        { id: "p", from: "note", to: { kind: "point", x: 380, y: 200 } },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Check with ops, node");
    await waitFor(() => expect(leaderIds(canvasElement)).toEqual(["leader:n", "leader:l", "leader:p"]));
    // Only the arrowed leaders have a head, and a leader is not offered as a connection.
    const heads = (id: string) => canvasElement.querySelector(`[data-id="leader:${id}"] .react-flow__edge-path`)?.getAttribute("marker-end");
    expect(heads("n")).toBeTruthy();
    expect(heads("l")).toBeFalsy();
    expect(canvas.queryByLabelText(/connection from Check with ops/)).toBeNull();
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-leader-end-free").length).toBe(1));
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

/** A click on empty canvas is reported as a background click in read-only mode too, and a click on a node is not. */
export const AClickOnEmptyCanvasIsABackgroundClick: Story = {
  args: { onBackgroundClick: fn() },
  render: (args) => <GraphCanvas nodes={LEADER_NODES} edges={[]} ariaLabel="Background" showViewToggle={false} readOnly onBackgroundClick={args.onBackgroundClick} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByLabelText("Gateway, node"));
    expect(args.onBackgroundClick).not.toHaveBeenCalled();
    await userEvent.click(canvasElement.querySelector(".react-flow__pane") as HTMLElement);
    await waitFor(() => expect(args.onBackgroundClick).toHaveBeenCalledTimes(1));
  },
};

/** Comment mode reports a click on empty canvas, on a node and on a line, and selects and moves nothing. */
export const CommentModeReportsWhatAClickLandedOn: Story = {
  args: { onCanvasPoint: fn(), onSelect: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={NODES} edges={EDGES} ariaLabel="Comment mode" showViewToggle={false} mode="comment"
      onCanvasPoint={args.onCanvasPoint} onSelect={args.onSelect}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const report = args.onCanvasPoint as ReturnType<typeof fn>;
    await userEvent.click(await canvas.findByLabelText("Gateway, node"));
    await waitFor(() => expect(report).toHaveBeenCalledTimes(1));
    expect(report.mock.calls[0][1]).toEqual({ kind: "node", id: "gateway" });
    await userEvent.click(canvasElement.querySelector(".react-flow__pane") as HTMLElement);
    await waitFor(() => expect(report).toHaveBeenCalledTimes(2));
    expect(report.mock.calls[1][1]).toEqual({ kind: "none" });
    expect(args.onSelect).not.toHaveBeenCalled();
    expect(canvasElement.querySelector(".graph-canvas-comment")).not.toBeNull();
  },
};

/** A pin is drawn by the consumer's render function at its place, anchored pins follow their node, and a pin whose node is not drawn is detached. */
export const PinsAreDrawnAtOneSizeAndFollowTheirNode: Story = {
  render: () => (
    <GraphCanvas
      nodes={NODES} edges={EDGES} ariaLabel="Pins" showViewToggle={false}
      pins={[
        { id: "free", x: 100, y: 100 },
        { id: "boxed", x: 0, y: 0, anchor: { kind: "node", id: "gateway" } },
        { id: "lined", x: 0, y: 0, anchor: { kind: "edge", id: "e1" } },
        { id: "gone", x: 300, y: 300, anchor: { kind: "node", id: "missing" } },
      ]}
      renderPin={(pin, context) => <button type="button" aria-label={`Pin ${pin.id}${context.detached ? " detached" : ""}`}>{pin.id}</button>}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    expect(await canvas.findByRole("button", { name: "Pin free" })).toBeInTheDocument();
    expect(canvas.getByRole("button", { name: "Pin boxed" })).toBeInTheDocument();
    expect(canvas.getByRole("button", { name: "Pin lined" })).toBeInTheDocument();
    expect(canvas.getByRole("button", { name: "Pin gone detached" })).toBeInTheDocument();
    // The pins are in the layer above the canvas, and the anchored ones are not at their stored (0, 0).
    const left = (name: string) => (canvas.getByRole("button", { name }).closest(".graph-pin") as HTMLElement).style.left;
    expect(left("Pin boxed")).not.toBe(left("Pin free"));
  },
};

/** A movable pin dragged and dropped reports its new place and what it landed on; an unmovable pin reports nothing. */
export const ADraggedPinReportsItsDropPlace: Story = {
  args: { onPinMove: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={NODES} edges={[]} ariaLabel="Move pins" showViewToggle={false} onPinMove={args.onPinMove}
      pins={[{ id: "move", x: 100, y: 200, movable: true }, { id: "fixed", x: 150, y: 200 }]}
      renderPin={(pin) => <button type="button" aria-label={`Pin ${pin.id}`}>{pin.id}</button>}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const move = await canvas.findByRole("button", { name: "Pin move" });
    const box = move.getBoundingClientRect();
    const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    const wrapper = move.closest(".graph-pin") as HTMLElement;
    const fire = (type: string, x: number, y: number) =>
      wrapper.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, pointerId: 1, button: 0 }));
    fire("pointerdown", from.x, from.y);
    fire("pointermove", from.x + 40, from.y + 40);
    fire("pointerup", from.x + 40, from.y + 40);
    await waitFor(() => expect(args.onPinMove).toHaveBeenCalledTimes(1));
    const [id, position, anchor] = (args.onPinMove as ReturnType<typeof fn>).mock.calls[0];
    expect(id).toBe("move");
    expect(Number.isFinite(position.x)).toBe(true);
    expect(anchor).toHaveProperty("kind");
    const fixed = canvas.getByRole("button", { name: "Pin fixed" }).closest(".graph-pin") as HTMLElement;
    expect(fixed.className).not.toContain("graph-pin-movable");
  },
};

const SNAP = { snapGrid: 20, snapInvertKey: "Shift" } as const;

/**
 * Drags the node by about `dx`, `dy` canvas units with the pointer, whatever the zoom, and returns the last position reported.
 * The drag lands a few units short of the request (React Flow starts it after a small threshold), so the callers choose
 * distances that stay clear of a grid boundary and assert on the grid, not on an exact free position.
 */
async function dragBy(canvasElement: HTMLElement, name: string, dx: number, dy: number, onMove: ReturnType<typeof fn>) {
  const canvas = within(canvasElement);
  const node = await canvas.findByLabelText(name);
  const frame = node.closest(".react-flow__node") as HTMLElement;
  // The drawn width over the node's own width is the zoom.
  const zoom = frame.getBoundingClientRect().width / 160;
  const box = node.getBoundingClientRect();
  const x = box.left + box.width / 2;
  const y = box.top + box.height / 2;
  const px = dx * zoom;
  const py = dy * zoom;
  const steps = 8;
  const along = (i: number) => ({ clientX: x + (px * i) / steps, clientY: y + (py * i) / steps });
  await userEvent.pointer([
    { keys: "[MouseLeft>]", target: node, coords: along(0) },
    ...Array.from({ length: steps }, (_, i) => ({ target: node, coords: along(i + 1) })),
    // A move is applied one event late, so the last position is repeated before the button is released.
    { target: node, coords: along(steps) },
    { keys: "[/MouseLeft]", target: node, coords: along(steps) },
  ]);
  await waitFor(() => expect(onMove).toHaveBeenCalled());
  const calls = onMove.mock.calls as { id: string; x: number; y: number }[][][];
  return calls[calls.length - 1][0][0];
}

/** The dot grid is drawn only while snapping applies; a canvas given no grid keeps its plain background. */
export const TheGridIsDrawnOnlyWhileSnappingIsOn: Story = {
  render: () => (
    <div className="stack">
      <div data-testid="off"><GraphCanvas nodes={NODES} edges={[]} ariaLabel="Grid off" showViewToggle={false} {...SNAP} snapOn={false} /></div>
      <div data-testid="on"><GraphCanvas nodes={NODES} edges={[]} ariaLabel="Grid on" showViewToggle={false} {...SNAP} snapOn /></div>
      <div data-testid="none"><GraphCanvas nodes={NODES} edges={[]} ariaLabel="No grid" showViewToggle={false} /></div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findAllByLabelText("Sensor, node");
    await waitFor(() => expect(canvas.getByTestId("on").querySelector(".react-flow__background")).not.toBeNull());
    expect(canvas.getByTestId("off").querySelector(".react-flow__background")).toBeNull();
    expect(canvas.getByTestId("none").querySelector(".react-flow__background")).not.toBeNull();
  },
};

/** With snapping on, a dragged box ends with its corner on the grid. */
export const ADragEndsOnTheGridWhenSnappingIsOn: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const last = await dragBy(canvasElement, "Cloud service, node", 27, 59, args.onNodesMove as ReturnType<typeof fn>);
    expect(last).toMatchObject({ id: "cloud", x: 580, y: 60 });
  },
};

/** With snapping off a drag lands where it was dropped. */
export const ADragIsFreeWhenSnappingIsOff: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn={false} onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const last = await dragBy(canvasElement, "Cloud service, node", 27, 59, args.onNodesMove as ReturnType<typeof fn>);
    expect(last.x % 20).not.toBe(0);
    expect(last.y % 20).not.toBe(0);
  },
};

/** Holding the invert key during a drag snaps when the setting is off, and moves freely when it is on. */
export const TheInvertKeyReversesTheSettingForOneDrag: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn={false} onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    await userEvent.keyboard("{Shift>}");
    const last = await dragBy(canvasElement, "Cloud service, node", 27, 59, args.onNodesMove as ReturnType<typeof fn>);
    await userEvent.keyboard("{/Shift}");
    expect(last).toMatchObject({ id: "cloud", x: 580, y: 60 });
    // The key held for a move over a box does not start a box selection: only the dragged node is reported.
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { id: string }[][][];
    expect(calls.every((c) => c[0].length === 1 && c[0][0].id === "cloud")).toBe(true);
  },
};

export const TheInvertKeySuspendsSnappingForOneDrag: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    await userEvent.keyboard("{Shift>}");
    const last = await dragBy(canvasElement, "Cloud service, node", 27, 59, args.onNodesMove as ReturnType<typeof fn>);
    await userEvent.keyboard("{/Shift}");
    expect(last.x % 20).not.toBe(0);
    expect(last.y % 20).not.toBe(0);
  },
};

/** With snapping on an arrow key moves the selected box by one grid step; with it off, by React Flow's small step. */
export const ArrowKeysMoveByTheGridWhenSnappingIsOn: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}{ArrowRight}{ArrowDown}");
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalledTimes(2));
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { id: string; x: number; y: number }[][][];
    expect(calls[0][0][0]).toMatchObject({ id: "sensor", x: 20, y: 0 });
    expect(calls[1][0][0]).toMatchObject({ id: "sensor", x: 20, y: 20 });
  },
};

/** The invert key held with no pointer press changes nothing about a key-driven move. */
export const TheInvertKeyDoesNotChangeAKeyMove: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host {...SNAP} snapOn onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    // Shift with an arrow moves React Flow's box by a larger factor; the snapped result is still on the grid.
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalled());
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { x: number; y: number }[][][];
    expect(calls[calls.length - 1][0][0].x % 20).toBe(0);
  },
};

/** Alt with an arrow key steps by the grid and puts the moved edge on it when snapping is on. */
export const KeyboardResizeStepsByTheGridWhenSnappingIsOn: Story = {
  args: { onNodesResize: fn() },
  render: (args) => <Host resizable {...SNAP} snapOn onNodesResize={args.onNodesResize} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Sensor, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Alt>}{ArrowRight}{ArrowDown}{/Alt}");
    await waitFor(() => expect(args.onNodesResize).toHaveBeenCalledTimes(2));
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { id: string; x: number; y: number; width: number; height: number }[][][];
    expect(calls[0][0][0]).toMatchObject({ id: "sensor", x: 0, y: 0, width: 180, height: 64 });
    // The bottom edge was at 64; one step down is 84, and the edge lands on the grid line at 80.
    expect(calls[1][0][0]).toMatchObject({ id: "sensor", x: 0, y: 0, width: 180, height: 80 });
  },
};

/** A pointer resize with snapping on ends with the edges it moved on the grid and the top left corner where it was. */
export const APointerResizeEndsOnTheGridWhenSnappingIsOn: Story = {
  args: { onNodesResize: fn() },
  render: (args) => <Host resizable {...SNAP} snapOn onNodesResize={args.onNodesResize} />,
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
    let box = handle.getBoundingClientRect();
    await waitFor(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
      const next = handle.getBoundingClientRect();
      const still = next.left === box.left && next.top === box.top;
      box = next;
      if (!still) throw new Error("handle still moving");
    });
    const zoom = (node.closest(".react-flow__node") as HTMLElement).getBoundingClientRect().width / 160;
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const to = (dx: number, dy: number) => ({ clientX: x + dx * zoom, clientY: y + dy * zoom });
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: handle, coords: to(0, 0) },
      { target: handle, coords: to(13, 9) },
      { target: handle, coords: to(27, 17) },
      { target: handle, coords: to(27, 17) },
      { keys: "[/MouseLeft]", target: handle, coords: to(27, 17) },
    ]);
    await waitFor(() => expect(args.onNodesResize).toHaveBeenCalled());
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { x: number; y: number; width: number; height: number }[][][];
    const last = calls[calls.length - 1][0][0];
    expect(last.x).toBe(0);
    expect(last.y).toBe(0);
    expect((last.x + last.width) % 20).toBe(0);
    expect((last.y + last.height) % 20).toBe(0);
    expect(last.width).toBeGreaterThan(160);
  },
};

/** Hosts the canvas with a badge on the gateway (one target) and on the cloud service (three), and prints what was opened. */
function BadgeHost({ count }: { count?: number }) {
  const [opened, setOpened] = useState("none");
  const nodes: GraphCanvasNode[] = NODES.map((n) => {
    if (n.id === "gateway") {
      return { ...n, badges: [{ id: "machines", label: "Open state machine diagram", icon: <span>M</span>, onActivate: () => setOpened("gateway"), count }] };
    }
    if (n.id === "cloud") {
      return {
        ...n,
        badges: [{
          id: "machines", label: "Open a state machine diagram", icon: <span>M</span>, count: 3,
          items: ["Modes", "Faults", "Updates"].map((name) => ({ id: name, label: name, onSelect: () => setOpened(name) })),
        }],
      };
    }
    return n;
  });
  return (
    <div className="stack">
      <Host nodes={nodes} />
      <span data-testid="opened">{opened}</span>
    </div>
  );
}

/** A badge is a real button named by its label; one target opens at once, and pressing it neither selects nor opens the box beneath. */
export const ABadgeOpensItsTargetWithoutSelectingTheBox: Story = {
  render: () => <BadgeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const badge = await canvas.findByRole("button", { name: "Open state machine diagram" });
    await userEvent.click(badge);
    await waitFor(() => expect(canvas.getByTestId("opened")).toHaveTextContent("gateway"));
    expect(canvas.getByTestId("selection")).toHaveTextContent("none");
  },
};

/** The badge is reached by Tab and pressed with Enter; the node under it does not take the key. */
export const ABadgeIsOperableFromTheKeyboard: Story = {
  render: () => <BadgeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const badge = await canvas.findByRole("button", { name: "Open state machine diagram" });
    badge.focus();
    expect(badge).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByTestId("opened")).toHaveTextContent("gateway"));
    expect(canvas.getByTestId("selection")).toHaveTextContent("none");
  },
};

/** A badge with several targets opens a list; choosing one calls it and closes the list. */
export const ABadgeWithSeveralTargetsOpensAList: Story = {
  render: () => <BadgeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const badge = await canvas.findByRole("button", { name: "Open a state machine diagram" });
    expect(badge).toHaveTextContent("3");
    await userEvent.click(badge);
    const list = await within(document.body).findByRole("list", { name: "Open a state machine diagram" });
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Modes", "Faults", "Updates"]);
    await userEvent.click(within(list).getByRole("button", { name: "Faults" }));
    await waitFor(() => expect(canvas.getByTestId("opened")).toHaveTextContent("Faults"));
    await waitFor(() => expect(within(document.body).queryByRole("list", { name: "Open a state machine diagram" })).toBeNull());
  },
};

const APPROACH_NODES: GraphCanvasNode[] = [
  { id: "a", label: "Alpha", x: 0, y: 0 },
  { id: "b", label: "Bravo", x: 400, y: 0 },
];

/** A box's handle by attach point. */
const handleOf = (node: HTMLElement, point: string) => node.querySelector(`.react-flow__handle[data-handleid="${point}"]`) as HTMLElement;
/** Whether a handle is drawn: hidden ones keep their size and stay in the page, so only the opacity tells. */
const drawn = (node: HTMLElement) => getComputedStyle(handleOf(node, "top")).opacity === "1";
/** Waits until the opening fit has finished moving the view, so a box's measured place is where it stays. */
const settled = async (root: HTMLElement) => {
  const transform = () => (root.querySelector(".react-flow__viewport") as HTMLElement | null)?.style.transform ?? "";
  let last = "";
  for (let tries = 0; tries < 40; tries += 1) {
    const now = transform();
    if (now !== "" && now === last) return;
    last = now;
    await new Promise((resolve) => setTimeout(resolve, 120));
  }
};
/** Where a pointer a few screen pixels outside the box's left edge, level with its middle, is. */
const justLeftOf = (node: HTMLElement, gap = 10) => {
  const r = node.getBoundingClientRect();
  return { clientX: r.left - gap, clientY: r.top + r.height / 2 };
};

/** At rest no box shows its attach points; the pointer coming near a box shows that box's points and no other's, and leaving hides them. */
export const AttachPointsShowOnlyNearThePointer: Story = {
  render: () => <GraphCanvas nodes={APPROACH_NODES} edges={[]} ariaLabel="Approach" showViewToggle={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const a = await canvas.findByLabelText("Alpha, node");
    const b = await canvas.findByLabelText("Bravo, node");
    await settled(canvasElement);
    await expect(handleOf(a, "top")).toBeInTheDocument();
    await expect(drawn(a)).toBe(false);
    await expect(drawn(b)).toBe(false);
    await userEvent.pointer({ target: canvasElement.querySelector(".react-flow__pane") as HTMLElement, coords: justLeftOf(a) });
    await waitFor(() => expect(drawn(a)).toBe(true));
    await expect(drawn(b)).toBe(false);
    const far = b.getBoundingClientRect();
    await userEvent.pointer({ target: canvasElement.querySelector(".react-flow__pane") as HTMLElement, coords: { clientX: far.right + 200, clientY: far.bottom + 200 } });
    await waitFor(() => expect(drawn(a)).toBe(false));
  },
};

/** The selected box keeps its points drawn while the pointer is elsewhere; a box with keyboard focus shows them too. */
export const SelectedAndFocusedBoxesShowTheirPoints: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sensor = await canvas.findByLabelText("Sensor, node");
    const cloud = await canvas.findByLabelText("Cloud service, node");
    await settled(canvasElement);
    await expect(drawn(sensor)).toBe(false);
    cloud.focus();
    await waitFor(() => expect(drawn(cloud)).toBe(true));
    cloud.blur();
    await userEvent.click(sensor);
    await waitFor(() => expect(canvas.getByTestId("selection")).toHaveTextContent("node:sensor"));
    const pane = canvasElement.querySelector(".react-flow__pane") as HTMLElement;
    const r = pane.getBoundingClientRect();
    await userEvent.pointer({ target: pane, coords: { clientX: r.right - 5, clientY: r.bottom - 5 } });
    await waitFor(() => expect(drawn(cloud)).toBe(false));
    await expect(drawn(sensor)).toBe(true);
  },
};

/** While a line is drawn from a box, that box's start point stays drawn and a box the pointer nears shows its points to end on. */
export const DrawingALineShowsPointsOnTheBoxItNears: Story = {
  render: () => <GraphCanvas nodes={APPROACH_NODES} edges={[]} ariaLabel="Drawing" showViewToggle={false} onConnect={() => undefined} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const a = await canvas.findByLabelText("Alpha, node");
    const b = await canvas.findByLabelText("Bravo, node");
    await settled(canvasElement);
    const pane = canvasElement.querySelector(".react-flow__pane") as HTMLElement;
    const start = handleOf(a, "right");
    const from = start.getBoundingClientRect();
    const origin = { clientX: from.left + from.width / 2, clientY: from.top + from.height / 2 };
    // Approach the handle first, as a person does, so it is drawn and can be pressed.
    await userEvent.pointer({ target: pane, coords: origin });
    await waitFor(() => expect(drawn(a)).toBe(true));
    await userEvent.pointer([{ keys: "[MouseLeft>]", target: start, coords: origin }]);
    const into = justLeftOf(b, 12);
    await userEvent.pointer([
      { target: pane, coords: { clientX: (origin.clientX + into.clientX) / 2, clientY: origin.clientY } },
      { target: pane, coords: into },
    ]);
    await waitFor(() => expect(drawn(b)).toBe(true));
    await expect(getComputedStyle(handleOf(a, "right")).opacity).toBe("1");
    await userEvent.pointer([{ keys: "[/MouseLeft]", target: pane, coords: into }]);
  },
};

/** A consumer can ask for the points to stay drawn on every box. */
export const AttachPointsCanAlwaysBeShown: Story = {
  render: () => <GraphCanvas nodes={APPROACH_NODES} edges={[]} ariaLabel="Always" showViewToggle={false} attachPointVisibility="always" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const a = await canvas.findByLabelText("Alpha, node");
    const b = await canvas.findByLabelText("Bravo, node");
    await expect(drawn(a)).toBe(true);
    await expect(drawn(b)).toBe(true);
  },
};

const MANY_NODES: GraphCanvasNode[] = Array.from({ length: 120 }, (_, i) => ({ id: `n${i}`, label: `Box ${i}`, x: (i % 12) * 220, y: Math.floor(i / 12) * 120 }));

/** A large drawing that counts what React commits in a data attribute, written to the page directly so counting renders nothing itself. */
function CountedDrawing() {
  const counter = useRef<HTMLOutputElement>(null);
  const commits = useRef(0);
  return (
    <div>
      <Profiler id="canvas" onRender={() => { commits.current += 1; if (counter.current) counter.current.dataset.commits = String(commits.current); }}>
        <GraphCanvas nodes={MANY_NODES} edges={[]} ariaLabel="Large" showViewToggle={false} />
      </Profiler>
      <output ref={counter} data-testid="commits" data-commits="0" />
    </div>
  );
}

/** Moving the pointer over a large drawing changes the points through the page only: React commits nothing. */
export const MovingThePointerOverALargeDrawingRendersNothing: Story = {
  render: () => <CountedDrawing />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = await canvas.findByLabelText("Box 0, node");
    const read = () => canvas.getByTestId("commits").dataset.commits;
    // Let the opening fit and measuring settle before counting.
    await new Promise((resolve) => setTimeout(resolve, 600));
    const before = read();
    const pane = canvasElement.querySelector(".react-flow__pane") as HTMLElement;
    const r = first.getBoundingClientRect();
    for (let step = 0; step < 12; step += 1) {
      await userEvent.pointer({ target: pane, coords: { clientX: r.left + step * 12, clientY: r.top + step * 6 } });
    }
    await waitFor(() => expect(canvasElement.querySelector('.react-flow__node[data-attach-near="true"]')).not.toBeNull());
    await expect(read()).toBe(before);
  },
};

// --- Vertices ---------------------------------------------------------------------------------------------------

const ROUTE_NODES: GraphCanvasNode[] = [{ id: "a", label: "A", x: 0, y: 0 }, { id: "b", label: "B", x: 300, y: 0 }];
const SELECTED_LINE: GraphCanvasSelection = { kind: "edge", id: "e1" };

/** Hosts one line `e1` between two boxes with real state for its vertices, as a consumer would. */
function RouteHost({ initial = [], smooth = false, readOnly = false, routable, onChange }: {
  initial?: { x: number; y: number }[]; smooth?: boolean; readOnly?: boolean; routable?: boolean; onChange?: (points: { x: number; y: number }[]) => void;
}) {
  const [points, setPoints] = useState(initial);
  return (
    <GraphCanvas
      nodes={ROUTE_NODES} edges={[{ id: "e1", source: "a", target: "b", points, smooth, routable }]} ariaLabel="Routes" showViewToggle={false}
      readOnly={readOnly} selected={SELECTED_LINE}
      onEdgePointsChange={(_id, next) => { setPoints(next); onChange?.(next); }}
    />
  );
}

/** The path's numbers, in order. */
function pathNumbers(root: HTMLElement, edgeId = "e1"): number[] {
  return lineEnds(root, edgeId);
}

/** A line with vertices is drawn through them: the path passes each vertex in order between its two ends. */
export const ALineIsDrawnThroughItsVertices: Story = {
  render: () => <RouteHost initial={[{ x: 150, y: 200 }, { x: 250, y: 200 }]} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    await waitFor(() => {
      const numbers = pathNumbers(canvasElement);
      expect(numbers).toHaveLength(8);
      expect(numbers.slice(2, 6)).toEqual([150, 200, 250, 200]);
    });
  },
};

/** A smooth line is drawn as a curve through the same points. */
export const ASmoothLineIsDrawnAsACurve: Story = {
  render: () => <RouteHost initial={[{ x: 150, y: 200 }]} smooth />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    await waitFor(() => {
      const d = canvasElement.querySelector('.react-flow__edge[data-id="e1"] path.react-flow__edge-path')?.getAttribute("d") ?? "";
      expect(d.startsWith("M ")).toBe(true);
      expect(d.match(/ C /g)).toHaveLength(2); // one curve into the vertex and one out of it
    });
  },
};

/** The selected line shows a handle on each vertex and one on the middle of each segment. */
export const ASelectedLineShowsVertexAndSegmentHandles: Story = {
  render: () => <RouteHost initial={[{ x: 150, y: 200 }]} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    await waitFor(() => {
      expect(canvasElement.querySelectorAll(".graph-waypoint")).toHaveLength(1);
      expect(canvasElement.querySelectorAll(".graph-segment-handle")).toHaveLength(2);
    });
    expect(canvasElement.querySelector(".graph-waypoint")?.getAttribute("aria-label")).toContain("Vertex 1");
  },
};

/** Drags the centre of `handle` by `dx`, `dy` screen pixels with the pointer. */
async function dragHandle(handle: Element, dx: number, dy: number) {
  const box = handle.getBoundingClientRect();
  const start = { clientX: box.left + box.width / 2, clientY: box.top + box.height / 2 };
  const along = (i: number) => ({ clientX: start.clientX + (dx * i) / 6, clientY: start.clientY + (dy * i) / 6 });
  await userEvent.pointer([
    { keys: "[MouseLeft>]", target: handle, coords: along(0) },
    ...Array.from({ length: 6 }, (_, i) => ({ target: handle, coords: along(i + 1) })),
    { keys: "[/MouseLeft]", target: handle, coords: along(6) },
  ]);
}

/** Dragging the middle of a segment adds one vertex, reported once with the whole list. */
export const DraggingASegmentMiddleAddsAVertex: Story = {
  args: { onEdgePointsChange: fn() },
  render: () => {
    const onChange = fn();
    // The canvas reports through the host's state; the spy is read back through the DOM below.
    return <div data-testid="route"><RouteHost onChange={(points) => { onChange(points); document.body.dataset.vertices = String(points.length); }} /></div>;
  },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    const handle = await waitFor(() => {
      const found = canvasElement.querySelector(".graph-segment-handle");
      expect(found).not.toBeNull();
      return found as Element;
    });
    await dragHandle(handle, 0, 80);
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-waypoint")).toHaveLength(1));
    expect(document.body.dataset.vertices).toBe("1");
    // The line now passes below its old straight course: the middle numbers of the path are the new vertex.
    const numbers = pathNumbers(canvasElement);
    expect(numbers).toHaveLength(6);
    expect(numbers[3]).toBeGreaterThan(numbers[1]);
  },
};

/** Dragging a vertex moves it. */
export const DraggingAVertexMovesIt: Story = {
  render: () => <RouteHost initial={[{ x: 150, y: 100 }]} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    const vertex = await waitFor(() => {
      const found = canvasElement.querySelector(".graph-waypoint");
      expect(found).not.toBeNull();
      return found as Element;
    });
    const before = pathNumbers(canvasElement);
    await dragHandle(vertex, 0, 60);
    await waitFor(() => expect(pathNumbers(canvasElement)[3]).toBeGreaterThan(before[3]));
    expect(pathNumbers(canvasElement)[2]).toBeCloseTo(before[2], -1);
  },
};

/** Double-clicking a vertex removes it. */
export const DoubleClickingAVertexRemovesIt: Story = {
  render: () => <RouteHost initial={[{ x: 150, y: 100 }]} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    const vertex = await waitFor(() => {
      const found = canvasElement.querySelector(".graph-waypoint");
      expect(found).not.toBeNull();
      return found as Element;
    });
    await userEvent.dblClick(vertex);
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-waypoint")).toHaveLength(0));
  },
};

/** One routed line with real state and a delete handler that records that it was called. */
function DeleteKeyHost() {
  const [points, setPoints] = useState([{ x: 150, y: 100 }]);
  return (
    <GraphCanvas
      nodes={ROUTE_NODES} edges={[{ id: "e1", source: "a", target: "b", points }]} ariaLabel="Routes" showViewToggle={false}
      selected={SELECTED_LINE} onEdgePointsChange={(_id, next) => setPoints(next)}
      onDelete={() => { document.body.dataset.deleted = "yes"; }}
    />
  );
}

/** Delete on a focused vertex removes the vertex, and never asks to delete the line. */
export const DeleteOnAVertexRemovesTheVertexNotTheLine: Story = {
  render: () => <DeleteKeyHost />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    delete document.body.dataset.deleted;
    const vertex = await waitFor(() => {
      const found = canvasElement.querySelector(".graph-waypoint") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    vertex.focus();
    await userEvent.keyboard("{Delete}");
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-waypoint")).toHaveLength(0));
    expect(document.body.dataset.deleted).toBeUndefined();
  },
};

/** A read-only canvas draws the route but offers no handles; a line the consumer cannot route offers none either. */
export const ReadOnlyAndUnroutableLinesOfferNoVertexHandles: Story = {
  render: () => (
    <div className="stack">
      <div data-testid="read-only"><RouteHost initial={[{ x: 150, y: 100 }]} readOnly /></div>
      <div data-testid="fixed"><RouteHost initial={[{ x: 150, y: 100 }]} routable={false} /></div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findAllByLabelText("B, node");
    await waitFor(() => expect(pathNumbers(canvas.getByTestId("read-only"))).toHaveLength(6));
    expect(canvasElement.querySelectorAll(".graph-waypoint")).toHaveLength(0);
    expect(canvasElement.querySelectorAll(".graph-segment-handle")).toHaveLength(0);
  },
};

/** An open end follows the vertex beside it: a vertex above the boxes draws the line from their tops. */
export const AnOpenEndFollowsTheVertexBesideIt: Story = {
  render: () => <RouteHost initial={[{ x: 230, y: -200 }]} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("B, node");
    await waitFor(() => {
      const numbers = pathNumbers(canvasElement);
      expect(numbers).toHaveLength(6);
      // Both ends sit on the top edge (y = 0) of their boxes, not on the facing sides (y = 40).
      expect(numbers[1]).toBeLessThan(10);
      expect(numbers[5]).toBeLessThan(10);
    });
  },
};

/** A double-click on the dot over a selected line's middle opens the line, as a double-click on the line itself does. */
export const DoubleClickingASegmentHandleOpensTheLine: Story = {
  args: { onEdgeOpen: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={ROUTE_NODES} edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Routes" showViewToggle={false}
      selected={SELECTED_LINE} onEdgePointsChange={() => undefined} onEdgeOpen={args.onEdgeOpen}
    />
  ),
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByLabelText("B, node");
    const handle = await waitFor(() => {
      const found = canvasElement.querySelector(".graph-segment-handle");
      expect(found).not.toBeNull();
      return found as Element;
    });
    await userEvent.dblClick(handle);
    await waitFor(() => expect(args.onEdgeOpen).toHaveBeenCalledWith("e1"));
    expect(args.onEdgeOpen).toHaveBeenCalledTimes(1);
  },
};

const DRAW_NODES: GraphCanvasNode[] = [
  { id: "note", label: "Check with ops", x: 0, y: 200, width: 160, height: 60, tone: "warning" },
  { id: "a", label: "Alpha", x: 0, y: 0 },
  { id: "b", label: "Bravo", x: 400, y: 0 },
];

/** The centre of an element on the screen. */
const centreOf = (el: Element) => {
  const r = el.getBoundingClientRect();
  return { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
};

/** Presses a handle of `node`, moves to `to` and releases there. */
async function drawFrom(root: HTMLElement, node: HTMLElement, point: string, to: { clientX: number; clientY: number }, target?: Element) {
  const handle = handleOf(node, point);
  const origin = centreOf(handle);
  const pane = root.querySelector(".react-flow__pane") as HTMLElement;
  await userEvent.pointer([
    { keys: "[MouseLeft>]", target: handle, coords: origin },
    { target: pane, coords: { clientX: (origin.clientX + to.clientX) / 2, clientY: (origin.clientY + to.clientY) / 2 } },
    { target: target ?? pane, coords: to },
    { keys: "[/MouseLeft]", target: target ?? pane, coords: to },
  ]);
}

/** A leader line is selectable and reports itself as a leader, under the id the consumer gave it, not as a connection. */
export const ALeaderIsSelectableAndReportsItselfAsALeader: Story = {
  args: { onSelect: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Selectable leaders" showViewToggle={false} onSelect={args.onSelect}
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 80, y: 100 } }]}
    />
  ),
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    const line = await waitFor(() => {
      const found = canvasElement.querySelector('.react-flow__edge[data-id="leader:p"]') as HTMLElement | null;
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(line.getAttribute("aria-label")).toBe("Leader line from Check with ops");
    await userEvent.click(line.querySelector(".react-flow__edge-interaction") as Element);
    await waitFor(() => expect(args.onSelect).toHaveBeenCalledWith({ kind: "leader", id: "p" }));
  },
};

/** A selected leader is drawn in the accent, and so is each leader of the selected node. */
export const ASelectedLeaderAndTheLeadersOfASelectedNoteAreHighlighted: Story = {
  render: () => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Highlighted" showViewToggle={false} selected={{ kind: "leader", id: "p" }}
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 80, y: 100 } }, { id: "q", from: "note", to: { kind: "point", x: 20, y: 100 } }]}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    await waitFor(() => expect(canvasElement.querySelector('.react-flow__edge[data-id="leader:p"]')?.classList.contains("selected")).toBe(true));
    expect(canvasElement.querySelector('.react-flow__edge[data-id="leader:q"]')?.classList.contains("selected")).toBe(false);
  },
};

/** Each end of a leader is plain, an arrowhead or a dot; the end defaults to an arrowhead and the start to plain. */
export const ALeaderDrawsAnArrowheadOrADotAtEitherEnd: Story = {
  render: () => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Ends" showViewToggle={false}
      leaders={[
        { id: "default", from: "note", to: { kind: "point", x: 80, y: 100 } },
        { id: "dots", from: "note", to: { kind: "point", x: 20, y: 100 }, startEnd: "dot", endEnd: "dot" },
        { id: "plain", from: "note", to: { kind: "point", x: 140, y: 100 }, endEnd: "none" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    const marks = (id: string) => {
      const path = canvasElement.querySelector(`[data-id="leader:${id}"] .react-flow__edge-path`);
      return { start: path?.getAttribute("marker-start") ?? null, end: path?.getAttribute("marker-end") ?? null };
    };
    await waitFor(() => expect(marks("default").end).toBeTruthy());
    expect(marks("default").start).toBeNull();
    expect(marks("dots").start).toContain("graph-dot-");
    expect(marks("dots").end).toContain("graph-dot-");
    expect(marks("plain")).toEqual({ start: null, end: null });
    // The dot is defined once, as a circle, and the markers point at it.
    const id = /#([^')]+)/.exec(marks("dots").start ?? "")?.[1] ?? "";
    expect(canvasElement.querySelector(`marker[id="${id}"] circle`)).not.toBeNull();
  },
};

/** A leader with vertices is drawn through them; on the selected leader the vertex and segment handles are offered and report the whole list. */
export const ALeaderWithVerticesIsDrawnThroughThemAndShowsHandlesWhenSelected: Story = {
  args: { onLeaderPointsChange: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Leader vertices" showViewToggle={false} selected={{ kind: "leader", id: "p" }}
      onLeaderPointsChange={args.onLeaderPointsChange}
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 300, y: 100 }, points: [{ x: 200, y: 150 }], fromPoint: "right" }]}
    />
  ),
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-waypoint").length).toBe(1));
    expect(canvasElement.querySelectorAll(".graph-segment-handle").length).toBe(2);
    const d = canvasElement.querySelector('[data-id="leader:p"] .react-flow__edge-path')?.getAttribute("d") ?? "";
    expect(d).toMatch(/ 200 150 /);
    // Pressing Delete on the vertex removes it: the consumer is told the new, empty list.
    const vertex = canvasElement.querySelector(".graph-waypoint") as HTMLElement;
    vertex.focus();
    await userEvent.keyboard("{Delete}");
    await waitFor(() => expect(args.onLeaderPointsChange).toHaveBeenCalledWith("p", []));
  },
};

/** Without `onLeaderPointsChange` a selected leader offers no vertex handles. */
export const ALeaderOffersNoVertexHandlesUnlessTheConsumerKeepsThem: Story = {
  render: () => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="No handles" showViewToggle={false} selected={{ kind: "leader", id: "p" }}
      leaders={[{ id: "p", from: "note", to: { kind: "point", x: 300, y: 100 }, points: [{ x: 200, y: 150 }] }]}
    />
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByLabelText("Check with ops, node");
    await waitFor(() => expect(canvasElement.querySelector('[data-id="leader:p"]')).not.toBeNull());
    expect(canvasElement.querySelectorAll(".graph-waypoint").length).toBe(0);
  },
};

/** A line drawn from a note's attach point and released on empty canvas is reported with the point it started from. */
export const DrawingFromAnAttachPointOntoEmptyCanvasReportsAPosition: Story = {
  args: { onConnectEmpty: fn(), onConnect: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Draw to canvas" showViewToggle={false} attachPointVisibility="always"
      onConnect={args.onConnect} onConnectEmpty={args.onConnectEmpty}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const note = await within(canvasElement).findByLabelText("Check with ops, node");
    await settled(canvasElement);
    const origin = centreOf(handleOf(note, "right"));
    await drawFrom(canvasElement, note, "right", { clientX: origin.clientX + 160, clientY: origin.clientY + 20 });
    await waitFor(() => expect(args.onConnectEmpty).toHaveBeenCalledTimes(1));
    const [source, to, via] = (args.onConnectEmpty as ReturnType<typeof fn>).mock.calls[0] as [string, { kind: string; x: number; y: number }, { sourcePoint: string }];
    expect(source).toBe("note");
    expect(to.kind).toBe("point");
    expect(Number.isFinite(to.x) && Number.isFinite(to.y)).toBe(true);
    expect(via).toEqual({ sourcePoint: "right" });
    expect(args.onConnect).not.toHaveBeenCalled();
  },
};

/** A line released on another box's attach point is a connect, with the point it started from. */
export const DrawingFromAnAttachPointOntoABoxHandleReportsAConnectWithTheStartPoint: Story = {
  args: { onConnectEmpty: fn(), onConnect: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[]} ariaLabel="Draw to box" showViewToggle={false} attachPointVisibility="always"
      onConnect={args.onConnect} onConnectEmpty={args.onConnectEmpty}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const note = await within(canvasElement).findByLabelText("Check with ops, node");
    const bravo = await within(canvasElement).findByLabelText("Bravo, node");
    await settled(canvasElement);
    const end = handleOf(bravo, "bottom");
    await drawFrom(canvasElement, note, "top", centreOf(end), end);
    await waitFor(() => expect(args.onConnect).toHaveBeenCalledWith("note", "b", { sourcePoint: "top" }));
    expect(args.onConnectEmpty).not.toHaveBeenCalled();
  },
};

/** A line released on a drawn line is reported as ending on that line, by its id; a leader is never offered as that target. */
export const DrawingFromAnAttachPointOntoALineReportsTheLine: Story = {
  args: { onConnectEmpty: fn() },
  render: (args) => (
    <GraphCanvas
      nodes={DRAW_NODES} edges={[{ id: "e1", source: "a", target: "b" }]} ariaLabel="Draw to line" showViewToggle={false}
      attachPointVisibility="always" onConnect={() => undefined} onConnectEmpty={args.onConnectEmpty}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const note = await within(canvasElement).findByLabelText("Check with ops, node");
    await settled(canvasElement);
    const path = await waitFor(() => {
      const found = canvasElement.querySelector('.react-flow__edge[data-id="e1"] .react-flow__edge-interaction') as Element | null;
      expect(found).not.toBeNull();
      return found as Element;
    });
    await drawFrom(canvasElement, note, "right", centreOf(path), path);
    await waitFor(() => expect(args.onConnectEmpty).toHaveBeenCalledWith("note", { kind: "edge", id: "e1" }, { sourcePoint: "right" }));
  },
};

/** Read-only: no line can be drawn from a note, so nothing is reported. */
export const ReadOnlyCanvasDrawsNoLeaders: Story = {
  args: { onConnectEmpty: fn() },
  render: (args) => (
    <GraphCanvas nodes={DRAW_NODES} edges={[]} ariaLabel="Read-only draw" showViewToggle={false} readOnly onConnectEmpty={args.onConnectEmpty} />
  ),
  play: async ({ canvasElement, args }) => {
    const note = await within(canvasElement).findByLabelText("Check with ops, node");
    await settled(canvasElement);
    const origin = centreOf(note);
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: note, coords: origin },
      { target: canvasElement.querySelector(".react-flow__pane") as HTMLElement, coords: { clientX: origin.clientX + 200, clientY: origin.clientY + 100 } },
      { keys: "[/MouseLeft]", target: canvasElement.querySelector(".react-flow__pane") as HTMLElement, coords: { clientX: origin.clientX + 200, clientY: origin.clientY + 100 } },
    ]);
    expect(args.onConnectEmpty).not.toHaveBeenCalled();
  },
};
