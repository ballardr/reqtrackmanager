import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import corpus from "./diagramCorpus.json";
import reference from "./diagramReference.json";
import { renderDiagram } from "./mermaidRender";

/**
 * The application's diagram renderer against the reference both renderers are held to: every diagram type of the shared
 * corpus must print the same words, and (except where the drawing follows its container) come out the same size, as the
 * reference the browser produced when it was generated (`scripts/generate-diagram-reference.mjs`). The server's renderer
 * is held to the same file (`converter/tests/test_diagram.py`), so a diagram reads the same in a report as on the page.
 */
const meta: Meta = { title: "Utils/mermaidReference", render: () => <p>Compares the renderer with the shared reference.</p> };
export default meta;

type Story = StoryObj;

interface Entry {
  name: string;
  size: string;
  width: number;
  height: number;
  words: Record<string, number>;
}

/** How far a drawing's size may differ from the reference, by the corpus entry's `size` kind (`container` is not compared). */
const TOLERANCE: Record<string, number> = { fixed: 0.05, font: 0.15 };

/** The size and the printed words of a drawing, read as the reference script reads them. */
function structure(svg: string): { width: number; height: number; words: Record<string, number> } {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const box = (doc.documentElement.getAttribute("viewBox") ?? "0 0 0 0").trim().split(/[ ,]+/).map(Number);
  const words: Record<string, number> = {};
  for (const element of Array.from(doc.querySelectorAll("text, tspan, title, desc"))) {
    for (const node of Array.from(element.childNodes)) {
      if (node.nodeType !== Node.TEXT_NODE) continue;
      for (let word of (node.textContent ?? "").split(/\s+/)) {
        word = word.replace(/\/$/, "");
        if (word === "" || /^\d+-[0-9a-f]{7}$/.test(word)) continue;
        words[word] = (words[word] ?? 0) + 1;
      }
    }
  }
  return { width: box[2], height: box[3], words };
}

export const EveryDiagramTypeAgreesWithTheReference: Story = {
  play: async () => {
    const entries = reference as unknown as Entry[]; // the JSON's inferred type is one shape per entry
    await expect(corpus.map((entry) => entry.name)).toEqual(entries.map((entry) => entry.name));
    for (const entry of corpus) {
      const expected = entries.find((candidate) => candidate.name === entry.name);
      if (expected === undefined) throw new Error(`${entry.name} is not in the reference`);
      const drawn = await renderDiagram(entry.source, "light");
      const svg = decodeURIComponent(drawn.src.slice(drawn.src.indexOf(",") + 1));
      const actual = structure(svg);
      await expect(actual.words, `${entry.name}: the words printed`).toEqual(expected.words);
      const tolerance = TOLERANCE[entry.size];
      if (tolerance !== undefined && expected.width > 0) {
        await expect(Math.abs(actual.width / expected.width - 1), `${entry.name}: width`).toBeLessThanOrEqual(tolerance);
        await expect(Math.abs(actual.height / expected.height - 1), `${entry.name}: height`).toBeLessThanOrEqual(tolerance);
      }
    }
  },
};
