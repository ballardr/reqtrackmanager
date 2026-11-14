import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { safeSvgImage } from "../../utils/safeSvgImage";
import cases from "./stateShapeCases.json";
import { STATE_MARKERS, stateShapeTable } from "./stateShapes";

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
