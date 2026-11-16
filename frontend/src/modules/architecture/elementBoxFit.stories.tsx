import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { GraphCanvas } from "../../components/GraphCanvas";
import { buildDiagramView, buildViewNode } from "./architectureFixtures";
import {
  BOX_HEIGHT, BOX_WIDTH, boxFrame, canvasNodes, layoutFromView, layoutToSave, nextFreePosition, resizeItems, type EditorLayout,
} from "./diagramEditorModel";
import { SYMBOL_HEIGHT, drawnBoxSize, fitBox } from "./elementBoxFit";
import cases from "./elementBoxFitCases.json";

function Host() {
  return <p>The size of an element box: the drawn frame holds the symbol, the code and the name whole.</p>;
}

const meta: Meta<typeof Host> = {
  title: "Modules/Architecture/ElementBoxFit",
  component: Host,
  // The drawing is a lazily loaded chunk; fetching it before the story runs keeps a cold first load from racing the test.
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
};
export default meta;

type Story = StoryObj<typeof Host>;

const SYMBOL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect x="2" y="2" width="36" height="36" fill="none" stroke="currentColor" stroke-width="3"/></svg>';

const CTX = {
  theme: "light" as const, symbolSvg: (id: string) => (id === "sym" ? SYMBOL : undefined), lockedLabel: (c: string) => `${c} (not visible)`,
  emptyNote: "Empty note", noteCaption: "Note", showNotes: true, hidden: new Set<string>(), covered: new Set<string>(),
  coverageLabel: () => "", badges: () => [],
};

const LONG = "Flight controller and motor driver board";

function layoutOf(...nodes: ReturnType<typeof buildViewNode>[]): EditorLayout {
  return layoutFromView(buildDiagramView({ nodes, edges: [], notes: [] }));
}

/** The browser's fit is the server's: the same lines, minimum and drawn size for every box, at each stored width. */
export const MatchesTheServersCases: Story = {
  play: async () => {
    for (const c of cases.cases) {
      for (const f of c.fits) {
        const fit = fitBox(c.has_symbol, c.caption, c.element_name, f.width);
        await expect({ minWidth: fit.minWidth, minHeight: fit.minHeight, lines: fit.lines }, `${c.name} at ${f.width}`).toEqual({
          minWidth: f.min_width, minHeight: f.min_height, lines: f.lines,
        });
      }
    }
    for (const d of cases.drawn) {
      const source = cases.cases.find((c) => c.name === d.name)!;
      const size = drawnBoxSize(source.has_symbol, source.caption, source.element_name, d.stored[0], d.stored[1]);
      await expect([size.width, size.height], `${d.name} from ${d.stored.join("x")}`).toEqual(d.size);
    }
  },
};

/** Boxes at the default size with a symbol and names of increasing length. */
const NODES = [
  { id: "a", name: LONG, symbol_id: "sym" },
  { id: "b", name: "Telemetry downlink for the ground segment operations", symbol_id: "sym" },
  { id: "c", name: "Supercalifragilisticexpialidocious", symbol_id: "sym" },
  { id: "d", name: `${LONG} without a symbol`, symbol_id: null },
].map((n, i) => buildViewNode({
  placement_id: `p-${n.id}`, element_id: n.id, unique_code: `ELM-00${i + 1}`, name: n.name, symbol_id: n.symbol_id,
  x: (i % 2) * 520, y: Math.floor(i / 2) * 320, width: 160, height: 80, element_type_name: "Subsystem",
}));

/** The real browser shows every box's whole text: nothing is clipped by the box, no name line is squeezed and the symbol keeps its height. */
export const TheBrowserShowsEveryBoxWithItsTextWhole: Story = {
  render: () => <GraphCanvas nodes={canvasNodes(layoutFromView(buildDiagramView({ nodes: NODES, edges: [], notes: [] })), CTX)} edges={[]} ariaLabel="Boxes" showViewToggle={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const n of NODES) {
      const node = await canvas.findByLabelText(new RegExp(`^${n.name}, node$`));
      const box = node.querySelector(".graph-node") as HTMLElement;
      const label = box.querySelector(".graph-node-label") as HTMLElement;
      await waitFor(() => {
        expect(box.scrollWidth, `${n.name} box width`).toBeLessThanOrEqual(box.clientWidth);
        expect(box.scrollHeight, `${n.name} box height`).toBeLessThanOrEqual(box.clientHeight);
        expect(label.scrollWidth, `${n.name} label width`).toBeLessThanOrEqual(label.clientWidth);
        expect(label.scrollHeight, `${n.name} label height`).toBeLessThanOrEqual(label.clientHeight);
        const caption = box.querySelector(".graph-node-caption") as HTMLElement;
        expect(caption.scrollWidth, `${n.name} caption width`).toBeLessThanOrEqual(caption.clientWidth);
      });
      const symbol = box.querySelector(".graph-node-symbol") as HTMLElement | null;
      if (n.symbol_id) {
        // The symbol is drawn at its fixed side, scaled with the canvas like the box.
        const scale = box.getBoundingClientRect().width / boxFrame(layoutOf(n).boxes[0]).width;
        await expect(Math.round(symbol!.getBoundingClientRect().height / scale)).toBe(SYMBOL_HEIGHT);
      } else await expect(symbol).toBeNull();
    }
  },
};

/** Setting a symbol, a longer name or a longer type grows the drawn box and leaves the stored size alone, and a bigger stored size wins. */
export const TheDrawnBoxGrowsAndTheStoredSizeIsKept: Story = {
  play: async () => {
    const plain = layoutOf(buildViewNode({ name: LONG, symbol_id: null, width: 160, height: 80 }));
    const symbol = layoutOf(buildViewNode({ name: LONG, symbol_id: "sym", width: 160, height: 80 }));
    await expect(boxFrame(plain.boxes[0])).toEqual({ width: 160, height: 80 });
    const grown = boxFrame(symbol.boxes[0]);
    await expect(grown.width).toBe(160);
    await expect(grown.height).toBeGreaterThan(80 + SYMBOL_HEIGHT);
    // The canvas node is the drawn frame and carries the fit as the resize minimum and the symbol's fixed height.
    const [node] = canvasNodes(symbol, CTX);
    await expect([node.width, node.height]).toEqual([grown.width, grown.height]);
    await expect(node.minHeight).toBe(grown.height);
    await expect(node.symbolHeight).toBe(SYMBOL_HEIGHT);
    // Saving writes the stored size, not the drawn one.
    await expect(layoutToSave(symbol).placements.map((b) => [b.width, b.height])).toEqual([[160, 80]]);
    // A stored size larger than the fit is the size drawn.
    const large = layoutOf(buildViewNode({ name: LONG, symbol_id: "sym", width: 400, height: 300 }));
    await expect(boxFrame(large.boxes[0])).toEqual({ width: 400, height: 300 });
    // A long word widens the box.
    const word = layoutOf(buildViewNode({ name: "Supercalifragilisticexpialidocious".repeat(2), symbol_id: null, width: 160, height: 80 }));
    await expect(boxFrame(word.boxes[0]).width).toBeGreaterThan(160);
  },
};

/** A resize releases at the size reached (the person's choice) and the drawn box is still never below the fit. */
export const AResizeIsStoredAndTheFitStillApplies: Story = {
  play: async () => {
    const layout = layoutOf(buildViewNode({ element_id: "a", name: LONG, symbol_id: "sym", width: 160, height: 80 }));
    const resized = resizeItems(layout, [{ id: "a", x: 0, y: 0, width: 200, height: 90 }]);
    await expect([resized.boxes[0].width, resized.boxes[0].height]).toEqual([200, 90]);
    await expect(boxFrame(resized.boxes[0]).height).toBeGreaterThanOrEqual(fitBox(true, "ELM-001 · Subsystem", LONG, 200).minHeight);
  },
};

/** A free slot for a new box is found by the frame the boxes are drawn at, not by their stored size. */
export const AFreeSlotRespectsTheDrawnFrameOfABox: Story = {
  play: async () => {
    // The first slot's box is stored small but drawn tall (a symbol and a long name), reaching into the second row's slot.
    const tall = layoutOf(buildViewNode({ element_id: "a", name: LONG, symbol_id: "sym", x: 0, y: 0, width: BOX_WIDTH, height: 10 }));
    const frame = boxFrame(tall.boxes[0]);
    await expect(frame.height).toBeGreaterThan(BOX_HEIGHT);
    // Slots are BOX_HEIGHT + gap apart; the second row's first slot (index 3 of four columns is on row 0, index 4 on row 1).
    const second = nextFreePosition(tall, 3);
    await expect(second.y + 1).toBeGreaterThan(0);
    const stored = layoutOf(buildViewNode({ element_id: "a", name: "A", symbol_id: null, x: 0, y: 0, width: BOX_WIDTH, height: 10 }));
    await expect(nextFreePosition(stored, 0)).toEqual({ x: BOX_WIDTH + 40, y: 0 });
  },
};

const onNodesResize = fn();

/** A node's own resize minimum holds for the keyboard: Alt with the arrow keys stops at the fit, not at the default minimum. */
export const KeyboardResizeStopsAtTheFit: Story = {
  beforeEach: () => { onNodesResize.mockClear(); },
  render: () => (
    <GraphCanvas
      nodes={[{ id: "n", label: "Named box", x: 0, y: 0, width: 200, height: 120, minWidth: 150, minHeight: 100 }]}
      edges={[]} ariaLabel="Boxes" showViewToggle={false} resizable onNodesResize={onNodesResize}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = await canvas.findByLabelText("Named box, node");
    node.focus();
    await userEvent.keyboard("{Enter}");
    for (let i = 0; i < 20; i += 1) await userEvent.keyboard("{Alt>}{ArrowLeft}{ArrowUp}{/Alt}");
    const calls = onNodesResize.mock.calls as { width: number; height: number }[][][];
    const last = calls[calls.length - 1][0][0];
    await expect([last.width, last.height]).toEqual([150, 100]);
  },
};
