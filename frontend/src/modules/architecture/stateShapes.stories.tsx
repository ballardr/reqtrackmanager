import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { safeSvgImage } from "../../utils/safeSvgImage";
import cases from "./stateShapeCases.json";
import { labelledSvg, markerAttachPoints, markerFrame, STATE_MARKERS, stateShapeTable, type StateMarkerKind } from "./stateShapes";
import { BASE_SIZE } from "./symbolLabelLayout";

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

/** A labelled marker is a larger square drawing at any size, passes the sanitiser and keeps its stroke width. */
export const EveryLabelledMarkerSurvivesTheSanitiserAtAnySizeAndIsLarger: Story = {
  play: async () => {
    for (const kind of Object.keys(BASE_SIZE) as StateMarkerKind[]) {
      for (const size of [BASE_SIZE[kind], 200]) {
        const uri = safeSvgImage(labelledSvg(kind, size));
        await expect(uri).not.toBeNull();
        await expect(decodeURIComponent((uri ?? "").split(",")[1] ?? "")).toContain(`viewBox="0 0 ${size} ${size}"`);
        await expect(size).toBeGreaterThan(STATE_MARKERS[kind].size);
      }
      if (kind !== "initial") await expect(labelledSvg(kind, 200)).toContain('stroke-width="2"');
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
    // A longer label grows the frame, still around the same centre.
    const grown = markerFrame("choice", box, "Is the tank level above the high-level alarm threshold for more than ten seconds");
    await expect(grown.width).toBeGreaterThan(96);
    await expect(grown.x + grown.width / 2).toBe(118);
    await expect(markerFrame("initial", { x: 0, y: 0, width: 200, height: 100 }, "x")).toEqual({ x: 0, y: 0, width: 200, height: 100 });
  },
};

/** A label outside the symbol leaves the frame at the stored box (the text is drawn beside it), and a blank label or one inside is as before. */
export const AMarkerFrameIsTheStoredBoxForALabelOutsideTheSymbol: Story = {
  play: async () => {
    const box = { x: 100, y: 50, width: 36, height: 36 };
    for (const position of ["left", "right", "above", "below"] as const) {
      await expect(markerFrame("choice", box, "A long enough label to need more room", position)).toEqual(box);
    }
    await expect(markerFrame("choice", box, "Full?", "inside")).toEqual({ x: 70, y: 20, width: 96, height: 96 });
  },
};

/** An open line end is not offered the side a label is on; with no label or the label inside, every side is. */
export const AMarkerOffersEverySideExceptTheOneItsLabelIsOn: Story = {
  play: async () => {
    await expect(markerAttachPoints("Go", "inside")).toEqual(["top", "right", "bottom", "left"]);
    await expect(markerAttachPoints("", "left")).toEqual(["top", "right", "bottom", "left"]);
    await expect(markerAttachPoints("Go", "left")).toEqual(["top", "right", "bottom"]);
    await expect(markerAttachPoints("Go", "right")).toEqual(["top", "bottom", "left"]);
    await expect(markerAttachPoints("Go", "above")).toEqual(["right", "bottom", "left"]);
    await expect(markerAttachPoints("Go", "below")).toEqual(["top", "right", "left"]);
  },
};
