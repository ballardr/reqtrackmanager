import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { safeSvgImage } from "../../utils/safeSvgImage";
import cases from "./stateShapeCases.json";
import { LABELLED_MARKERS, markerFrame, STATE_MARKERS, stateShapeTable } from "./stateShapes";

function Host() {
  return <p>Runs the browser copy of the state shape table against the table the server produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Architecture/StateShapes", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

/** The browser's table is the server's table: markers (size and markup), the state's sizes and the composite frame's. */
export const MatchesTheServersTable: Story = {
  play: async () => {
    await expect(stateShapeTable()).toEqual(cases);
  },
};

/** Every marker is a square drawing that passes the canvas's own sanitiser and draws something. */
export const EveryMarkerSurvivesTheSanitiser: Story = {
  play: async () => {
    for (const marker of Object.values(STATE_MARKERS)) {
      const uri = safeSvgImage(marker.svg);
      await expect(uri).not.toBeNull();
      const drawing = decodeURIComponent((uri ?? "").split(",")[1] ?? "");
      await expect(drawing).toMatch(/<(circle|polygon)/);
      await expect(drawing).toContain(`viewBox="0 0 ${marker.size} ${marker.size}"`);
    }
  },
};

/** Every labelled marker is a larger square drawing that passes the sanitiser and keeps room for its text. */
export const EveryLabelledMarkerSurvivesTheSanitiserAndIsLarger: Story = {
  play: async () => {
    for (const [kind, marker] of Object.entries(LABELLED_MARKERS)) {
      const uri = safeSvgImage(marker.svg);
      await expect(uri).not.toBeNull();
      await expect(decodeURIComponent((uri ?? "").split(",")[1] ?? "")).toContain(`viewBox="0 0 ${marker.size} ${marker.size}"`);
      await expect(marker.size).toBeGreaterThan(STATE_MARKERS[kind as keyof typeof STATE_MARKERS].size);
      await expect(marker.textWidth).toBeLessThan(marker.size);
    }
  },
};

/** A label grows the drawn symbol around the stored box's centre; none (or blank) leaves the box alone, and a larger box is kept. */
export const AMarkerFrameGrowsAroundItsCentreOnlyForALabel: Story = {
  play: async () => {
    const box = { x: 100, y: 50, width: 36, height: 36 };
    await expect(markerFrame("choice", box, "")).toEqual(box);
    await expect(markerFrame("choice", box, "   ")).toEqual(box);
    const frame = markerFrame("choice", box, "Full?");
    await expect(frame).toEqual({ x: 70, y: 20, width: 96, height: 96 });
    await expect(frame.x + frame.width / 2).toBe(118);
    await expect(markerFrame("initial", { x: 0, y: 0, width: 200, height: 100 }, "x")).toEqual({ x: 0, y: 0, width: 200, height: 100 });
  },
};
