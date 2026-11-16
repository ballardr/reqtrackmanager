import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { BASE_SIZE, fitLabel, holds, LABEL_PADDING, MAX_SIZE, SIZE_STEP, textSide, textWidth, wrapLabel, type SymbolLabelLayout } from "./symbolLabelLayout";
import cases from "./symbolLabelCases.json";
import type { StateMarkerKind } from "./stateShapes";

function Host() {
  return <p>Runs the browser copy of the symbol label layout against the cases the server produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Architecture/SymbolLabelLayout", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

/** The browser's layout is the server's layout: the same size, lines and fit for every label on every symbol, and the same widths. */
export const MatchesTheServersCases: Story = {
  play: async () => {
    for (const c of cases.cases) {
      const layout = fitLabel(c.kind as StateMarkerKind, c.label) as SymbolLabelLayout;
      await expect({ size: layout.size, lines: layout.lines, fits: layout.fits }, c.name).toEqual({ size: c.size, lines: c.lines, fits: c.fits });
    }
    for (const w of cases.widths) await expect(textWidth(w.text), w.text).toBe(w.width);
  },
};

/** A label breaks between words and after a hyphen only, and the symbol grows in whole steps from its base size. */
export const AWordIsNeverSplitAndTheSymbolGrowsInSteps: Story = {
  play: async () => {
    const kinds: StateMarkerKind[] = ["initial", "final", "choice"];
    for (const kind of kinds) {
      const layout = fitLabel(kind, "Is the tank level above the high-level alarm threshold for more than ten seconds") as SymbolLabelLayout;
      await expect(layout.fits).toBe(true);
      await expect(layout.size).toBeGreaterThan(BASE_SIZE[kind]);
      await expect((layout.size - BASE_SIZE[kind]) % SIZE_STEP).toBe(0);
      await expect(layout.size).toBeLessThanOrEqual(MAX_SIZE);
      await expect(layout.lines.join(" ").replace(/- /g, "-")).toBe("Is the tank level above the high-level alarm threshold for more than ten seconds");
      await expect(holds(kind, layout.size, layout.lines)).toBe(true);
      await expect(textSide(kind, layout.size)).toBeGreaterThan(0);
    }
  },
};

/** A word longer than the largest symbol is kept whole on its own line and reported as not fitting; a blank label has no layout. */
export const AnOverLongWordIsKeptWholeAndReported: Story = {
  play: async () => {
    const layout = fitLabel("choice", `before ${"x".repeat(60)} after`) as SymbolLabelLayout;
    await expect(layout).toEqual({ size: MAX_SIZE, lines: ["before", "x".repeat(60), "after"], fits: false });
    await expect(fitLabel("choice", "  \n ")).toBeNull();
  },
};

/** A hyphen and a full-width character are places to break, and a line break the person typed is kept. */
export const HyphensFullWidthCharactersAndTypedBreaksAreBreakPlaces: Story = {
  play: async () => {
    await expect(wrapLabel("well-known fact", textWidth("well-") + 1)).toEqual(["well-", "known", "fact"]);
    await expect(wrapLabel("電源電源", textWidth("電源") + 1)).toEqual(["電源", "電源"]);
    await expect(wrapLabel("a\n\nb", 1e9)).toEqual(["a", "b"]);
  },
};

/** Text keeps the padding from the symbol's inner edge: a short label holds at the base size, text as wide as the symbol does not. */
export const TextKeepsItsPaddingFromTheInnerEdge: Story = {
  play: async () => {
    await expect(LABEL_PADDING).toBe(4);
    for (const kind of ["initial", "final", "choice"] as StateMarkerKind[]) {
      await expect(holds(kind, BASE_SIZE[kind], ["Go"])).toBe(true);
      await expect(holds(kind, BASE_SIZE[kind], ["W".repeat(10)])).toBe(false);
    }
  },
};
