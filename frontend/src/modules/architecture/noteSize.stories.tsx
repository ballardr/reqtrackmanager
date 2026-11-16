import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import { GraphCanvas } from "../../components/GraphCanvas";
import { buildDiagramView, buildNote } from "./architectureFixtures";
import { BOX_HEIGHT, canvasNodes, layoutFromView, layoutToSave, nextFreePosition, resizeItems, type EditorLayout } from "./diagramEditorModel";
import { newNote, noteFrame, updateNote, type EditorNote } from "./noteModel";
import { NOTE_CAPTION_HEIGHT, NOTE_PADDING, automaticFrame, drawnSize, noteLines } from "./noteLayout";
import cases from "./noteLayoutCases.json";

function Host() {
  return <p>The size of an annotation note: the layout shared with the server, the automatic frame in the browser and the editor's rules.</p>;
}

const meta: Meta<typeof Host> = {
  title: "Modules/Architecture/NoteSize",
  component: Host,
  // The drawing is a lazily loaded chunk; fetching it before the story runs keeps a cold first load from racing the test.
  loaders: [async () => { await import("../../components/GraphCanvasView"); return {}; }],
};
export default meta;

type Story = StoryObj<typeof Host>;

const CTX = {
  theme: "light" as const, symbolSvg: () => undefined, lockedLabel: (c: string) => c, emptyNote: "Empty note", noteCaption: "Note",
  showNotes: true, hidden: new Set<string>(), covered: new Set<string>(), coverageLabel: () => "", badges: () => [],
};

function layoutWith(...notes: ReturnType<typeof buildNote>[]): EditorLayout {
  return layoutFromView(buildDiagramView({ nodes: [], edges: [], notes }));
}

/** The browser's lines and frames are the server's: the same for every note, at the maximum width, with a caption and at fixed widths. */
export const MatchesTheServersCases: Story = {
  play: async () => {
    for (const c of cases.cases) {
      const at = noteLines(c.title, c.text, 308);
      await expect({ title: at.title, text: at.text }, c.name).toEqual(c.lines);
      await expect(automaticFrame(c.title, c.text, false), c.name).toEqual(c.frame ? { width: c.frame[0], height: c.frame[1] } : null);
      await expect(automaticFrame(c.title, c.text, true), c.name).toEqual(
        c.frame_with_caption ? { width: c.frame_with_caption[0], height: c.frame_with_caption[1] } : null,
      );
      for (const w of c.wrapped) await expect(noteLines(c.title, c.text, w.inner), `${c.name} at ${w.inner}`).toEqual({ title: w.title, text: w.text });
    }
    const sample = cases.cases[0];
    for (const d of cases.drawn) {
      const source = cases.cases.find((c) => c.name === d.name) ?? sample;
      const size = drawnSize({
        sizeMode: d.mode as "automatic" | "manual", tone: d.tone as "none" | "warning", title: source.title, text: source.text, width: 160, height: 60,
      });
      await expect([size.width, size.height], `${d.mode} ${d.tone} ${d.name}`).toEqual(d.size);
    }
  },
};

/** An Automatic note is as large as its text needs, the padding from the words on every side; a toned note adds room for its caption. */
export const AnAutomaticNoteIsDrawnThePaddingFromItsText: Story = {
  play: async () => {
    const plain = automaticFrame("", "Check with ops", false)!;
    await expect(plain.height).toBe(16 + 2 * NOTE_PADDING);
    const toned = automaticFrame("", "Check with ops", true)!;
    await expect(toned).toEqual({ width: plain.width, height: plain.height + NOTE_CAPTION_HEIGHT });
    await expect(automaticFrame("", "", false)).toBeNull();
    await expect(automaticFrame("  ", " \n ", true)).toBeNull();
  },
};

/** A new note is Automatic; the canvas gets the computed frame and the inset for an Automatic note and the stored size for a Manual one. */
export const TheCanvasDrawsTheFrameOfAnAutomaticNoteAndTheStoredSizeOfAManualOne: Story = {
  play: async () => {
    await expect(newNote("k", { x: 0, y: 0 }).sizeMode).toBe("automatic");
    const layout = layoutWith(
      buildNote({ id: "auto", text: "Check with ops", tone: "none", size_mode: "automatic", width: 400, height: 300 }),
      buildNote({ id: "hand", text: "Check with ops", tone: "none", size_mode: "manual", width: 400, height: 300 }),
    );
    const nodes = canvasNodes(layout, CTX);
    const auto = nodes.find((n) => n.id === "note:auto")!;
    const hand = nodes.find((n) => n.id === "note:hand")!;
    await expect([auto.width, auto.height]).toEqual([117, 28]);
    await expect([hand.width, hand.height]).toEqual([400, 300]);
    await expect([auto.inset, hand.inset]).toEqual([NOTE_PADDING, NOTE_PADDING]);
    // The stored size is kept under Automatic, so a return to Manual finds it.
    await expect(layoutToSave(layout).notes.map((n) => [n.size_mode, n.width, n.height])).toEqual([["automatic", 400, 300], ["manual", 400, 300]]);
  },
};

/** Resizing an Automatic note makes it Manual at the size reached, and the editor's frame follows the text until then. */
export const ResizingAnAutomaticNoteMakesItManualAtThatSize: Story = {
  play: async () => {
    let layout = layoutWith(buildNote({ id: "n", text: "Hi", tone: "none", size_mode: "automatic" }));
    const key = layout.notes[0].key;
    await expect(noteFrame(layout.notes[0])).toEqual({ width: 48, height: 28 });
    layout = updateNote(layout, key, { text: "Hi there, this is a longer remark that wraps" });
    await expect(noteFrame(layout.notes[0]).width).toBeGreaterThan(48);
    layout = updateNote(layout, key, { text: "Hi there, this is a longer remark that wraps onto a second line because it goes past the maximum width" });
    await expect(noteFrame(layout.notes[0]).height).toBeGreaterThan(28);
    layout = resizeItems(layout, [{ id: `note:${key}`, x: 10, y: 20, width: 222, height: 77 }]);
    await expect(layout.notes[0]).toMatchObject({ sizeMode: "manual", x: 10, y: 20, width: 222, height: 77 });
    await expect(noteFrame(layout.notes[0])).toEqual({ width: 222, height: 77 });
    // Choosing Automatic again draws the content frame and keeps the size set by hand for a return.
    layout = updateNote(layout, key, { sizeMode: "automatic" });
    await expect(noteFrame(layout.notes[0]).width).toBeLessThanOrEqual(320);
    await expect(layout.notes[0]).toMatchObject({ width: 222, height: 77 });
  },
};

/** A free slot for a new box is found by the frame a note is drawn at, not by its stored size. */
export const AFreeSlotRespectsTheDrawnFrameOfANote: Story = {
  play: async () => {
    // A note on the second row of the grid whose stored size spans the whole row but whose text needs a small corner of it.
    const row = BOX_HEIGHT + 40;
    const note = { id: "a", x: 0, y: row, width: 2000, height: 20, tone: "none" as const, text: "Hi" };
    const automatic = layoutWith(buildNote({ ...note, size_mode: "automatic" }));
    const manual = layoutWith(buildNote({ ...note, size_mode: "manual" }));
    // The fifth free slot: next to the small note on the second row, or (the row being taken) on the third.
    await expect(nextFreePosition(automatic, 4).y).toBe(row);
    await expect(nextFreePosition(manual, 4).y).toBeGreaterThan(row);
  },
};

const SAMPLES: Array<[string, Partial<EditorNote>]> = [
  ["short", { text: "Check with ops" }],
  ["long line", { text: "The flight controller reads the inertial unit and the barometer before it commands the motors at one kilohertz" }],
  ["title and paragraphs", { title: "Redundancy", text: "Single flight controller.\n\nRedundancy is decided separately." }],
  ["wide title", { title: "A fairly long heading for a note", text: "Hi" }],
  ["capitals and signs", { text: "ABS MWM @ 100% WWW MMM" }],
  ["right aligned", { title: "End", text: "Right text that wraps because it is a little longer than the rest", textAlign: "right" }],
];

const TONES = ["none", "warning"] as const;

/** Every sample at each tone, its text ending with the tone so each note has its own name on the canvas. */
const NOTES: EditorNote[] = SAMPLES.flatMap(([name, patch], i) => TONES.map((tone, j) => ({
  ...newNote(`${name}-${tone}`, { x: j * 420, y: i * 140 }), ...patch, text: `${patch.text} (${tone})`, tone,
})));

/** The real browser holds each Automatic note's text without clipping it, and the text starts the padding from the frame's edge. */
export const TheBrowserHoldsEveryAutomaticNoteWithoutClippingItsText: Story = {
  render: () => <GraphCanvas nodes={canvasNodes({ ...layoutWith(), notes: NOTES }, CTX)} edges={[]} ariaLabel="Notes" showViewToggle={false} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const note of NOTES) {
      const name = `${note.key} (${note.textAlign})`;
      const frame = automaticFrame(note.title, note.text, note.tone !== "none")!;
      const label = note.title ? `${note.title}: ${note.text}` : note.text;
      const node = await canvas.findByLabelText(new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\n/g, "\\s*")}, node$`));
      const box = node.querySelector(".graph-node") as HTMLElement;
      await waitFor(() => {
        expect(box.scrollWidth, `${name} width`).toBeLessThanOrEqual(box.clientWidth);
        expect(box.scrollHeight, `${name} height`).toBeLessThanOrEqual(box.clientHeight);
      });
      const scale = box.getBoundingClientRect().width / frame.width;
      const text = box.querySelector(".graph-node-text") as HTMLElement;
      const left = (text.getBoundingClientRect().left - box.getBoundingClientRect().left) / scale;
      // The text block sits the padding from the frame's left edge (the border is inside the padding), whatever its alignment.
      expect(Math.abs(left - NOTE_PADDING), `${name} left gap`).toBeLessThan(1.5);
    }
  },
};
