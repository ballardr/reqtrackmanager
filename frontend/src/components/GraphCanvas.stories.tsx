import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { GraphCanvas, type GraphCanvasEdge, type GraphCanvasNode, type GraphCanvasProps, type GraphCanvasSelection } from "./GraphCanvas";

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
