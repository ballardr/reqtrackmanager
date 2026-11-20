import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./markdownRoundTripCases.json";
import { escapeBlockMarker, fenceFor, findVisualBlocker, looksLikeMarkdown, roundTripMarkdown } from "./visualMarkdown";

/** The visual editor's Markdown round trip: what it holds without change, and what it refuses. */
const meta: Meta = { title: "Utils/visualMarkdown", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const EverySupportedTextRoundTripsWithoutChange: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const [name, source] of Object.entries(cases.supported)) {
      const written = roundTripMarkdown(source);
      if (findVisualBlocker(source, written) !== null) failures.push(`${name}: changed meaning`);
      // Writing is stable: reading what was written and writing it again gives the same text.
      else if (roundTripMarkdown(written) !== written) failures.push(`${name}: not stable`);
    }
    await expect(failures).toEqual([]);
    await expect(Object.keys(cases.supported).length).toBeGreaterThan(80);
  },
};

export const EveryUnsupportedTextIsReportedNotChanged: Story = {
  play: async () => {
    const accepted = Object.entries(cases.unsupported)
      .filter(([, source]) => findVisualBlocker(source, roundTripMarkdown(source)) === null)
      .map(([name]) => name);
    await expect(accepted).toEqual([]);
  },
};

export const MathematicsIsNamedAsTheReason: Story = {
  play: async () => {
    await expect(findVisualBlocker("Energy is $E = mc^2$.", "Energy is $E = mc^2$.")).toBe("mathematics");
    await expect(findVisualBlocker("<div>x</div>", roundTripMarkdown("<div>x</div>"))).toBe("unsupported");
  },
};

export const BlockMarkersAtTheStartOfALineAreEscaped: Story = {
  play: async () => {
    await expect(escapeBlockMarker("1. text")).toBe("1\\. text");
    await expect(escapeBlockMarker("# text")).toBe("\\# text");
    await expect(escapeBlockMarker("- text")).toBe("\\- text");
    await expect(escapeBlockMarker("---")).toBe("\\---");
    // Emphasis and ordinary text are left alone.
    await expect(escapeBlockMarker("**bold** and 1.5 and a-b")).toBe("**bold** and 1.5 and a-b");
  },
};

export const ACodeBlockFenceIsLongerThanItsText: Story = {
  play: async () => {
    await expect(fenceFor("plain")).toBe("```");
    await expect(fenceFor("a ``` b")).toBe("````");
    await expect(roundTripMarkdown("````\n```\ninner\n```\n````")).toBe("````\n```\ninner\n```\n````");
  },
};

export const OnlyMarkdownSyntaxIsOfferedForConversion: Story = {
  play: async () => {
    await expect(looksLikeMarkdown("## Heading\n\ntext")).toBe(true);
    await expect(looksLikeMarkdown("a **bold** word")).toBe(true);
    await expect(looksLikeMarkdown("- one\n- two")).toBe(true);
    await expect(looksLikeMarkdown("| a | b |\n| - | - |")).toBe(true);
    await expect(looksLikeMarkdown("Just a plain sentence, with 2 * 3 maths.")).toBe(false);
  },
};
