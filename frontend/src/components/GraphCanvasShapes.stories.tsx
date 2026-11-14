import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { GraphCanvas, type GraphCanvasEdge, type GraphCanvasNode, type GraphCanvasProps } from "./GraphCanvas";
import { selfLoop, selfLoopPath } from "./graphSelfLoop";

/**
 * The shapes the shared canvas draws beyond a plain box and a straight line: a loop on one node, multi-line line labels,
 * marker nodes (a consumer's drawing, no box) and containers holding the nodes whose `parentId` names them. The stories use
 * a generic order-processing graph, so nothing here depends on a consumer.
 */
const meta: Meta<typeof GraphCanvas> = {
  title: "Components/GraphCanvas/Shapes",
  component: GraphCanvas,
  parameters: { layout: "padded" },
  loaders: [async () => { await import("./GraphCanvasView"); return {}; }],
};
export default meta;

type Story = StoryObj<typeof GraphCanvas>;

const DOT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#64748b"/></svg>';
const DIAMOND =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><polygon points="18,1 35,18 18,35 1,18" fill="none" stroke="#64748b" stroke-width="2"/></svg>';

/** The numbers of a path's `d` (a line's start and end). React Flow starts a line at the outer edge of a 6px handle, up to 3px off the point. */
const pathNumbers = (d: string | null | undefined) => (d ?? "").match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
const near = (value: number | undefined, expected: number) => value !== undefined && Math.abs(value - expected) <= 4;

/** Hosts the canvas with real positions, as a consumer would, so a move is stored and shown. */
function Host({ initial, ...props }: { initial: GraphCanvasNode[] } & Partial<GraphCanvasProps>) {
  const [nodes, setNodes] = useState(initial);
  return (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={nodes} edges={[]}
      onNodesMove={(moves) => {
        props.onNodesMove?.(moves);
        setNodes((current) => current.map((n) => ({ ...n, ...moves.find((m) => m.id === n.id) })));
      }}
      {...props}
    />
  );
}

const PLAIN: GraphCanvasNode[] = [
  { id: "open", label: "Open", x: 0, y: 0 },
  { id: "paid", label: "Paid", x: 300, y: 0 },
];

/** A line from a node to itself is drawn as the fixed loop at the box's top right corner, with the label beside it. */
export const ALineFromANodeToItselfIsDrawnAsALoop: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={PLAIN}
      edges={[
        { id: "retry", source: "open", target: "open", label: "retry" },
        { id: "pay", source: "open", target: "paid", label: "pay" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("retry, connection from Open to Open");
    // Open is the default 160 x 64 at the origin, so its loop is the shared rule's loop for that box.
    const expected = selfLoopPath(selfLoop({ x: 0, y: 0, width: 160, height: 64 }));
    await waitFor(() => {
      const paths = [...canvasElement.querySelectorAll(".react-flow__edge-path")].map((p) => p.getAttribute("d"));
      expect(paths).toContain(expected);
    });
    await waitFor(() => expect(canvasElement.querySelector(".graph-edge-label-corner")).toHaveTextContent("retry"));
    await expect(canvas.getByLabelText("pay, connection from Open to Paid")).toBeInTheDocument();
  },
};

/** A loop on a box follows the box when it is moved, and a loop can be selected like any line. */
export const ALoopFollowsItsNodeAndCanBeSelected: Story = {
  args: { onSelect: fn() },
  render: (args) => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={[{ id: "open", label: "Open", x: 40, y: 80 }]}
      edges={[{ id: "retry", source: "open", target: "open", label: "retry" }]} onSelect={args.onSelect}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const loop = await canvas.findByLabelText("retry, connection from Open to Open");
    loop.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(args.onSelect).toHaveBeenCalledWith({ kind: "edge", id: "retry" }));
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__edge-path")[0]?.getAttribute("d")).toBe(
      selfLoopPath(selfLoop({ x: 40, y: 80, width: 160, height: 64 })),
    ));
  },
};

/** A line break in a label starts a new line of text, on a straight line and on a loop; a label without one is the usual text. */
export const MultiLineLabelsKeepTheirLineBreaks: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={PLAIN}
      edges={[
        { id: "pay", source: "open", target: "paid", label: "pay\n[card ok]\n/ charge" },
        { id: "retry", source: "open", target: "open", label: "retry\n[3 times]" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll(".graph-edge-label")).toHaveLength(2));
    const labels = [...canvasElement.querySelectorAll<HTMLElement>(".graph-edge-label")];
    await expect(labels.map((l) => l.textContent)).toEqual(expect.arrayContaining(["pay\n[card ok]\n/ charge", "retry\n[3 times]"]));
    await expect(getComputedStyle(labels[0]).whiteSpace).toBe("pre-line");
    // The label is text, never markup.
    await expect(canvasElement.querySelector(".graph-edge-label *")).toBeNull();
  },
};

/** A single-line label keeps the built-in text, so a graph with no line breaks draws as it always did. */
export const ASingleLineLabelIsDrawnAsBefore: Story = {
  render: () => <GraphCanvas ariaLabel="Order processing" showViewToggle={false} nodes={PLAIN} edges={[{ id: "pay", source: "open", target: "paid", label: "pay" }]} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelector(".react-flow__edge-text")).toHaveTextContent("pay"));
    await expect(canvasElement.querySelector(".graph-edge-label")).toBeNull();
  },
};

const MARKERS: GraphCanvasNode[] = [
  { id: "start", label: "Start", x: 0, y: 40, width: 20, height: 20, marker: true, symbolSvg: DOT },
  { id: "check", label: "Payment check", x: 300, y: 28, width: 36, height: 36, marker: true, symbolSvg: DIAMOND },
  { id: "open", label: "Open", x: 100, y: 20, },
];

/** A marker is only its drawing: no box, no text, four side handles, no resize handles; its name is still spoken. */
export const MarkerNodesDrawOnlyTheirDrawing: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={MARKERS} resizable
      edges={[{ id: "begin", source: "start", target: "open" }, { id: "decide", source: "open", target: "check" }]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const start = (await canvas.findByLabelText("Start, node")).closest(".react-flow__node") as HTMLElement;
    const check = (await canvas.findByLabelText("Payment check, node")).closest(".react-flow__node") as HTMLElement;
    await expect(start.querySelector(".graph-node-marker-image")).not.toBeNull();
    await expect(start.querySelector(".graph-node-text")).toBeNull();
    await expect(start).not.toHaveTextContent("Start");
    const sides = (node: HTMLElement) => [...node.querySelectorAll(".react-flow__handle")].map((h) => h.getAttribute("data-handleid")).sort();
    await expect(sides(check)).toEqual(["bottom", "left", "right", "top"]);
    const open = (await canvas.findByLabelText("Open, node")).closest(".react-flow__node") as HTMLElement;
    await expect(open.querySelectorAll(".react-flow__handle")).toHaveLength(8);
    // The marker is not resizable even when the canvas is.
    check.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvasElement.querySelectorAll(".react-flow__node.selected")).toHaveLength(1));
    await expect(check.querySelector(".react-flow__resize-control")).toBeNull();
  },
};

/** A line to a marker meets it at the middle of a side, never at a corner of its frame. */
export const ALineToAMarkerMeetsAMiddleOfASide: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false}
      nodes={[
        { id: "open", label: "Open", x: 0, y: 200 },
        { id: "check", label: "Payment check", x: 300, y: 0, width: 36, height: 36, marker: true, symbolSvg: DIAMOND },
      ]}
      edges={[{ id: "decide", source: "open", target: "check" }]}
    />
  ),
  play: async ({ canvasElement }) => {
    // The marker (36 square at 300, 0) is up and to the right of Open. Its nearest point is the middle of its bottom side,
    // (318, 36), not the bottom left corner of its frame, (300, 36); Open's nearest point is its top right corner.
    await waitFor(() => {
      const [x1, y1, x2, y2] = pathNumbers(canvasElement.querySelector(".react-flow__edge-path")?.getAttribute("d"));
      expect([near(x1, 160), near(y1, 200), near(x2, 318), near(y2, 36)]).toEqual([true, true, true, true]);
    });
  },
};

const GROUP: GraphCanvasNode[] = [
  { id: "group", label: "Fulfilment", x: 0, y: 0, width: 420, height: 220, container: true },
  { id: "pick", label: "Pick", x: 40, y: 80, parentId: "group" },
  { id: "pack", label: "Pack", x: 220, y: 80, parentId: "group" },
  { id: "ship", label: "Ship", x: 520, y: 80 },
];

const rect = (el: Element) => el.getBoundingClientRect();
const nodeEl = (canvas: ReturnType<typeof within>, name: string) => canvas.getByLabelText(`${name}, node`).closest(".react-flow__node") as HTMLElement;

/** Children are drawn inside their container, above it, and keep the consumer's absolute coordinates. */
export const AContainerDrawsItsChildrenInsideIt: Story = {
  render: () => <Host initial={GROUP} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Pick, node");
    await waitFor(() => {
      const frame = rect(nodeEl(canvas, "Fulfilment"));
      for (const name of ["Pick", "Pack"]) {
        const child = rect(nodeEl(canvas, name));
        expect(child.left).toBeGreaterThan(frame.left);
        expect(child.right).toBeLessThan(frame.right);
        expect(child.top).toBeGreaterThan(frame.top);
        expect(child.bottom).toBeLessThan(frame.bottom);
      }
      expect(rect(nodeEl(canvas, "Ship")).left).toBeGreaterThan(frame.right);
    });
    await expect(canvasElement.querySelectorAll(".graph-node-container")).toHaveLength(1);
  },
};

/** Moving a container reports it and every node inside it (all at the new absolute position); a node outside is not reported. */
export const MovingAContainerMovesAndReportsItsChildren: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host initial={GROUP} onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const frame = await canvas.findByLabelText("Fulfilment, node");
    frame.focus();
    await userEvent.keyboard("{Enter}{ArrowRight}{ArrowRight}");
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalled());
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { id: string; x: number; y: number }[][][];
    const reported = new Map(calls.flatMap((c) => c[0]).map((m) => [m.id, m]));
    await expect([...reported.keys()].sort()).toEqual(["group", "pack", "pick"]);
    const group = reported.get("group")!;
    await expect(group.x).toBeGreaterThan(0);
    // Each child moved by the same step as its parent, so it is still where it was inside the frame.
    await expect(reported.get("pick")!.x - 40).toBe(group.x);
    await expect(reported.get("pack")!.x - 220).toBe(group.x);
    await expect(reported.get("pick")!.y).toBe(80);
  },
};

/** Moving a child reports only the child, at its absolute position, and it stays inside the container. */
export const MovingAChildReportsOnlyTheChildInAbsoluteUnits: Story = {
  args: { onNodesMove: fn() },
  render: (args) => <Host initial={GROUP} onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const pick = await canvas.findByLabelText("Pick, node");
    pick.focus();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowDown}");
    await waitFor(() => expect(args.onNodesMove).toHaveBeenCalled());
    const calls = (args.onNodesMove as ReturnType<typeof fn>).mock.calls as { id: string; x: number; y: number }[][][];
    const moves = calls.flatMap((c) => c[0]);
    await expect(new Set(moves.map((m) => m.id))).toEqual(new Set(["pick"]));
    await expect(moves[moves.length - 1].y).toBeGreaterThan(80);
    await expect(moves[moves.length - 1].x).toBe(40);
  },
};

/** A line to a child and a loop on a container are drawn between the absolute boxes, not the relative ones. */
export const LinesJoinNodesInsideAContainerAtTheirAbsoluteBoxes: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} nodes={GROUP}
      edges={[{ id: "next", source: "pick", target: "pack", label: "next" }, { id: "out", source: "pack", target: "ship", label: "out" }]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("next, connection from Pick to Pack");
    await waitFor(() => {
      const paths = [...canvasElement.querySelectorAll(".react-flow__edge-path")].map((p) => pathNumbers(p.getAttribute("d")));
      // Pick (40..200 x 80..144) to Pack (220..380): the facing sides, at the absolute height 112.
      expect(paths.some(([x1, y1, x2, y2]) => near(x1, 200) && near(y1, 112) && near(x2, 220) && near(y2, 112))).toBe(true);
    });
  },
};

/** An unknown parent, a node as its own parent and a loop of parents are ignored: every node is drawn, none nested. */
export const AnInvalidParentLeavesTheNodeUnnested: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" showViewToggle={false} edges={[]}
      nodes={[
        { id: "a", label: "Alpha", x: 0, y: 0, parentId: "missing" },
        { id: "b", label: "Beta", x: 200, y: 0, parentId: "b" },
        { id: "c", label: "Gamma", x: 400, y: 0, parentId: "d" },
        { id: "d", label: "Delta", x: 600, y: 0, parentId: "c" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of ["Alpha", "Beta", "Gamma", "Delta"]) await canvas.findByLabelText(`${name}, node`);
    await expect(canvasElement.querySelectorAll(".react-flow__node")).toHaveLength(4);
  },
};

/** The list view still names every node and line, including a marker and a loop, as the text alternative. */
export const TheListViewNamesMarkersAndLoops: Story = {
  render: () => (
    <GraphCanvas
      ariaLabel="Order processing" initialView="list" nodes={MARKERS}
      edges={[{ id: "retry", source: "open", target: "open", label: "retry" }] as GraphCanvasEdge[]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Start")).toBeInTheDocument();
    await expect(canvas.getByText("Payment check")).toBeInTheDocument();
    await expect(canvas.getByText("retry")).toBeInTheDocument();
  },
};

/** Resizing a container from its top left corner moves its edge, not the nodes inside: they stay where they are, unreported. */
export const ResizingAContainerFromItsTopLeftLeavesItsChildrenInPlace: Story = {
  args: { onNodesResize: fn(), onNodesMove: fn() },
  render: (args) => <Host initial={GROUP} resizable onNodesResize={args.onNodesResize} onNodesMove={args.onNodesMove} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const frame = await canvas.findByLabelText("Fulfilment, node");
    frame.focus();
    await userEvent.keyboard("{Enter}");
    const handle = await waitFor(() => {
      const found = canvasElement.querySelector(".react-flow__resize-control.handle.top.left");
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
    const before = rect(nodeEl(canvas, "Pick"));
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: handle, coords: { clientX: x, clientY: y } },
      { target: handle, coords: { clientX: x + 10, clientY: y + 8 } },
      { target: handle, coords: { clientX: x + 20, clientY: y + 16 } },
      { keys: "[/MouseLeft]", target: handle, coords: { clientX: x + 20, clientY: y + 16 } },
    ]);
    await waitFor(() => expect(args.onNodesResize).toHaveBeenCalled());
    const calls = (args.onNodesResize as ReturnType<typeof fn>).mock.calls as { id: string; x: number; y: number; width: number }[][][];
    const last = calls[calls.length - 1][0][0];
    await expect(last.id).toBe("group");
    await expect(last.x).toBeGreaterThan(0);
    await expect(last.width).toBeLessThan(420);
    const after = rect(nodeEl(canvas, "Pick"));
    await expect(Math.abs(after.left - before.left)).toBeLessThan(1);
    await expect(Math.abs(after.top - before.top)).toBeLessThan(1);
    await expect(args.onNodesMove).not.toHaveBeenCalled();
  },
};
