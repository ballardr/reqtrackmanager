import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { markdownPlainText } from "./markdownPlain";

/** The one-line plain text of a Markdown value, for a cell, a card or a subtitle (the server's `plain_text`, in the browser). */
const meta: Meta = { title: "Utils/markdownPlain", render: () => <p>Pure helper; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const MarksAreRemovedAndBlocksJoinedWithSpaces: Story = {
  play: async () => {
    await expect(markdownPlainText("# Title\n\nSome **bold** and _italic_ text\n\n- one\n- two")).toBe("Title Some bold and italic text one two");
    await expect(markdownPlainText("| a | b |\n|---|---|\n| 1 | 2 |")).toBe("a b 1 2");
    await expect(markdownPlainText("A [link](https://example.com) and `code`")).toBe("A link and code");
  },
};

export const ADiagramIsNamedAndACodeBlockKeepsItsText: Story = {
  play: async () => {
    await expect(markdownPlainText("Before\n\n```mermaid\ngraph TD; A-->B\n```\n\nAfter")).toBe("Before [Diagram] After");
    await expect(markdownPlainText("```\nlet x = 1;\n```")).toBe("let x = 1;");
  },
};

export const EquationsKeepTheirTexOnlyWhenAsked: Story = {
  play: async () => {
    await expect(markdownPlainText("Range \\( x_1 \\) metres", { math: true })).toBe("Range x_1 metres");
    await expect(markdownPlainText("Range \\( x_1 \\) metres")).toBe("Range ( x_1 ) metres");
  },
};

export const ALongTextEndsInAnEllipsisAtTheLimit: Story = {
  play: async () => {
    const text = markdownPlainText("one two three four five six", { limit: 12 });
    await expect(text.length).toBeLessThanOrEqual(12);
    await expect(text.endsWith("…")).toBe(true);
    await expect(markdownPlainText("short", { limit: 12 })).toBe("short");
  },
};

export const HostileMarkupIsOnlyText: Story = {
  play: async () => {
    await expect(markdownPlainText("<script>alert(1)</script> [x](javascript:alert(1))")).toBe("<script>alert(1)</script> [x](javascript:alert(1))");
    await expect(markdownPlainText("")).toBe("");
  },
};

export const APictureIsItsAlternativeText: Story = {
  play: async () => {
    await expect(markdownPlainText("See ![the plot](attachment:3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f) here")).toBe("See the plot here");
    await expect(markdownPlainText("![a \\[b\\] c](attachment:3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f)")).toBe("a [b] c");
  },
};
